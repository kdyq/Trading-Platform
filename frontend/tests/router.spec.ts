import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.vue'
import router from '../src/router'
import { useAuthStore } from '../src/stores/auth'

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      const payload = url.includes('/seller/products')
        ? { items: [] }
        : url.endsWith('/api/v1/favorites')
          ? { items: [], total: 0, page: 1, page_size: 1 }
          : url.includes('/market/categories') || url.includes('/market/campuses')
            ? []
            : url.includes('/market/products')
              ? { items: [], total: 0, page: 1, page_size: 4 }
              : url.includes('/market/summary')
                ? { available_products: 0, active_campuses: 0, verified_sellers: 0 }
                : {
                    status: 'ready',
                    dependencies: {
                      database: { status: 'ready', reason: null },
                      redis: { status: 'ready', reason: null },
                    },
                  }
      return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }))
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function renderRoute(path: string, authenticated = false) {
  const pinia = createPinia()
  if (authenticated) {
    useAuthStore(pinia).applySession('test-token', {
      id: '11111111-1111-4111-8111-111111111111',
      login_email: 'student@example.edu',
      display_name: '测试同学',
      status: 'active',
      campus_verification_status: 'verified',
    })
  }
  await router.push(path)
  await router.isReady()

  const wrapper = mount(App, {
    global: {
      plugins: [pinia, router],
    },
  })
  await flushPromises()
  return wrapper
}

describe('application routes', () => {
  it.each([
    ['/', '闲置好物', false],
    ['/login', '登录拾光集市', false],
    ['/register', '注册拾光集市', false],
    ['/forgot-password', '找回密码', false],
    ['/my-products', '我的发布', true],
    ['/favorites', '我的收藏', true],
    ['/orders', '我的订单', false],
    ['/admin', '管理端工程已就绪', false],
    ['/missing', '这个摊位还没有摆出来', false],
  ])('renders %s', async (path, expectedText, authenticated) => {
    const wrapper = await renderRoute(path, authenticated)
    expect(wrapper.text()).toContain(expectedText)
    wrapper.unmount()
  })
})
