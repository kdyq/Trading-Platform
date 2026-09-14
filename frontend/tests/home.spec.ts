import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import HomeView from '../src/views/HomeView.vue'

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function marketFetch(products: unknown[] = []) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/market/categories')) {
      return Promise.resolve(jsonResponse([{ id: 'category', code: 'books', name: '教材书籍' }]))
    }
    if (url.includes('/market/products')) {
      return Promise.resolve(
        jsonResponse({ items: products, total: products.length, page: 1, page_size: 8 }),
      )
    }
    if (url.includes('/market/summary')) {
      return Promise.resolve(
        jsonResponse({
          available_products: products.length,
          active_campuses: 0,
          verified_sellers: 0,
        }),
      )
    }
    return Promise.resolve(jsonResponse({ status: 'ready', dependencies: {} }))
  })
}

async function renderHome() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: HomeView },
      { path: '/market', component: { template: '<div>市场</div>' } },
      { path: '/login', component: { template: '<div>登录</div>' } },
      { path: '/my-products', component: { template: '<div>发布</div>' } },
      { path: '/campus-verification', component: { template: '<div>认证</div>' } },
      { path: '/account', component: { template: '<div>账户</div>' } },
      { path: '/products/:id', component: { template: '<div>商品</div>' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(HomeView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return wrapper
}

afterEach(() => vi.unstubAllGlobals())

describe('public market home', () => {
  it('shows an honest empty state to visitors', async () => {
    vi.stubGlobal('fetch', marketFetch())
    const wrapper = await renderHome()
    expect(wrapper.text()).toContain('第一件好物还没摆上来')
    expect(wrapper.text()).toContain('登录后发布')
    expect(wrapper.text()).toContain('教材书籍')
    expect(wrapper.text()).not.toContain('99%')
    wrapper.unmount()
  })

  it('renders product facts returned by the public API', async () => {
    vi.stubGlobal(
      'fetch',
      marketFetch([
        {
          id: 'product-id',
          title: '高等数学教材',
          price: '18.50',
          status: 'on_sale',
          published_at: '2026-09-14T00:00:00Z',
          campus_name: '东校区',
          school_name: '测试学校',
          seller_name: '小林',
          seller_verified: true,
          category_code: 'books',
          category_name: '教材书籍',
          image_url: null,
          image_alt: null,
        },
      ]),
    )
    const wrapper = await renderHome()
    expect(wrapper.text()).toContain('高等数学教材')
    expect(wrapper.text()).toContain('¥18.50')
    expect(wrapper.text()).toContain('东校区')
    expect(wrapper.text()).toContain('小林')
    wrapper.unmount()
  })

  it('offers a retry when the market request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    const wrapper = await renderHome()
    expect(wrapper.text()).toContain('市集暂时没有连上')
    expect(wrapper.get('button').text()).toContain('重新加载')
    wrapper.unmount()
  })
})
