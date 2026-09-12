import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.vue'
import router from '../src/router'

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 'ready',
          dependencies: {
            database: { status: 'ready', reason: null },
            redis: { status: 'ready', reason: null },
          },
        }),
        { status: 200 },
      ),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function renderRoute(path: string) {
  await router.push(path)
  await router.isReady()

  const wrapper = mount(App, {
    global: {
      plugins: [createPinia(), router],
    },
  })
  await flushPromises()
  return wrapper
}

describe('application routes', () => {
  it.each([
    ['/', '闲置好物'],
    ['/login', '登录拾光集市'],
    ['/admin', '管理端工程已就绪'],
    ['/missing', '这个摊位还没有摆出来'],
  ])('renders %s', async (path, expectedText) => {
    const wrapper = await renderRoute(path)
    expect(wrapper.text()).toContain(expectedText)
    wrapper.unmount()
  })
})
