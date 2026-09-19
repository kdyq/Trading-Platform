import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.vue'
import router from '../src/router'
import { useAuthStore } from '../src/stores/auth'

const campusId = '22222222-2222-4222-8222-222222222222'
const categoryId = '33333333-3333-4333-8333-333333333333'

function session(pinia: ReturnType<typeof createPinia>) {
  useAuthStore(pinia).applySession('token', {
    id: '11111111-1111-4111-8111-111111111111',
    login_email: 'student@example.edu',
    display_name: '测试同学',
    status: 'active',
    campus_verification_status: 'verified',
  })
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      const payload = url.includes('/catalog/categories')
        ? [
            {
              id: categoryId,
              code: 'books',
              slug: 'books',
              name: '教材书籍',
              display_order: 0,
              children: [],
            },
          ]
        : url.includes('/campus/status')
          ? {
              status: 'verified',
              verification_id: 'verification',
              campus_id: campusId,
              campus_email: 'student@example.edu',
              verified_at: '2026-09-01T00:00:00Z',
              expires_at: '2027-09-01T00:00:00Z',
              appeal: null,
            }
          : { items: [] }
      return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }))
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('product publishing form', () => {
  it('restores a local draft and keeps the verified campus', async () => {
    localStorage.setItem(
      'shiguang-product-draft:new',
      JSON.stringify({
        step: 2,
        form: {
          title: '高等数学教材',
          description: '有少量课堂笔记，页面完整，没有缺页和明显污损。',
          price: '18.50',
          categoryId,
        },
      }),
    )
    const pinia = createPinia()
    session(pinia)
    await router.push('/sell')
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('发布一件校园好物')
    expect((wrapper.get('input[required]').element as HTMLInputElement).value).toBe('高等数学教材')
    expect(wrapper.text()).toContain('上传真实商品图片')
    expect(localStorage.getItem('shiguang-product-draft:new')).toContain(campusId)
    wrapper.unmount()
  })
})
