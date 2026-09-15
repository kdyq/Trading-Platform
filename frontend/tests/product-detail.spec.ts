import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ProductGallery from '../src/components/market/ProductGallery.vue'
import ProductDetailView from '../src/views/ProductDetailView.vue'
import { useAuthStore } from '../src/stores/auth'

const product = {
  id: 'product-1',
  title: '高等数学教材',
  price: '18.50',
  status: 'on_sale',
  published_at: '2026-09-14T08:00:00Z',
  campus_name: '东校区',
  school_name: '测试大学',
  seller_name: '小林',
  seller_verified: true,
  category_code: 'books',
  category_name: '教材书籍',
  condition: 'good',
  is_negotiable: true,
  view_count: 12,
  image_url: null,
  image_alt: null,
  description: '少量笔记，无缺页。',
  seller: {
    id: 'seller-1',
    display_name: '小林',
    campus_verified: true,
    review_count: 2,
    average_rating: '4.50',
    completed_orders: 3,
  },
  images: [{ id: 'image-1', url: '/api/v1/market/product-images/image-1', alt_text: '教材封面' }],
  similar_products: [],
}

async function renderDetail(
  body: object = product,
  status = 200,
  fetchImplementation?: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
) {
  vi.stubGlobal(
    'fetch',
    fetchImplementation ??
      vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  )
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/products/:id', component: ProductDetailView },
      { path: '/login', component: { template: '<div>登录</div>' } },
      { path: '/campus-verification', component: { template: '<div>认证</div>' } },
      { path: '/market', component: { template: '<div>市场</div>' } },
    ],
  })
  await router.push('/products/product-1')
  await router.isReady()
  const wrapper = mount(ProductDetailView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { pinia, router, wrapper }
}

beforeEach(() => {
  document.title = '拾光集市'
  document.head.querySelector('meta[name="description"]')?.remove()
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('product detail', () => {
  it('renders trustworthy facts, SEO metadata, and the visitor login gate', async () => {
    const { wrapper } = await renderDetail()
    expect(wrapper.text()).toContain('少量笔记，无缺页。')
    expect(wrapper.text()).toContain('校园身份已认证')
    expect(document.title).toBe('高等数学教材｜拾光集市')
    expect(document.querySelector('meta[name="description"]')?.getAttribute('content')).toContain(
      '测试大学东校区',
    )

    await wrapper.get('.product-main-actions .ui-button-primary').trigger('click')
    expect(document.body.textContent).toContain('登录后继续')
    wrapper.unmount()
    expect(document.querySelector('meta[name="description"]')).toBeNull()
  })

  it('routes an authenticated but unverified buyer to campus verification', async () => {
    const { wrapper } = await renderDetail()
    useAuthStore().applySession('token', {
      id: 'buyer-1',
      login_email: 'buyer@example.edu.cn',
      display_name: '买家',
      status: 'active',
      campus_verification_status: 'pending',
    })
    await wrapper.get('.product-main-actions .ui-button-primary').trigger('click')
    expect(document.body.textContent).toContain('完成校园认证')
    wrapper.unmount()
  })

  it.each([
    ['own product', { ...product }, 'seller-1', '这是你发布的商品'],
    ['sold product', { ...product, status: 'sold' }, 'buyer-1', '商品已售出'],
  ])('disables actions for %s', async (_label, body, userId, reason) => {
    const { wrapper } = await renderDetail(body)
    useAuthStore().applySession('token', {
      id: userId,
      login_email: 'user@example.edu.cn',
      display_name: '用户',
      status: 'active',
      campus_verification_status: 'verified',
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.product-main-actions .ui-button-primary').attributes('disabled')).toBe('')
    expect(wrapper.text()).toContain(reason)
    wrapper.unmount()
  })

  it('uses one generic public state for missing and non-public products', async () => {
    const { wrapper } = await renderDetail(
      { code: 'product_not_found', message: '商品不存在或不可见' },
      404,
    )
    expect(wrapper.text()).toContain('这件商品暂时不在摊位上')
    expect(wrapper.text()).not.toContain('审核')
    wrapper.unmount()
  })

  it('keeps the report entry available when a product is sold', async () => {
    const { wrapper } = await renderDetail({ ...product, status: 'sold' })
    useAuthStore().applySession('token', {
      id: 'buyer-1',
      login_email: 'user@example.edu.cn',
      display_name: '用户',
      status: 'active',
      campus_verification_status: 'pending',
    })
    await wrapper.get('.report-entry').trigger('click')
    expect(document.body.textContent).toContain('举报入口已保留')
    wrapper.unmount()
  })

  it('does not retain the previous product SEO when a reused route fails', async () => {
    const { router, wrapper } = await renderDetail()
    expect(document.title).toBe('高等数学教材｜拾光集市')
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ code: 'internal_error', message: '服务暂时不可用' }), {
        status: 500,
      }),
    )

    await router.push('/products/product-2')
    await flushPromises()
    expect(wrapper.text()).toContain('商品详情暂时无法加载')
    expect(document.title).toBe('商品详情｜拾光集市')
    expect(
      document.querySelector('meta[name="description"]')?.getAttribute('content'),
    ).not.toContain('高等数学教材')
    wrapper.unmount()
  })

  it('ignores an aborted old route request when the next product succeeds', async () => {
    let requestCount = 0
    let firstSignal: AbortSignal | undefined
    const secondProduct = { ...product, id: 'product-2', title: '线性代数教材' }
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      requestCount += 1
      if (requestCount === 1) {
        firstSignal = init?.signal ?? undefined
        return new Promise<Response>((_resolve, reject) => {
          firstSignal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'))
          })
        })
      }
      return Promise.resolve(new Response(JSON.stringify(secondProduct), { status: 200 }))
    })
    const { router, wrapper } = await renderDetail(product, 200, fetchMock)

    await router.push('/products/product-2')
    await flushPromises()
    expect(firstSignal?.aborted).toBe(true)
    expect(wrapper.text()).toContain('线性代数教材')
    expect(wrapper.text()).not.toContain('商品详情暂时无法加载')
    expect(document.title).toBe('线性代数教材｜拾光集市')
    wrapper.unmount()
  })
})

describe('product gallery', () => {
  it('supports arrow-key navigation and image failure fallback', async () => {
    const wrapper = mount(ProductGallery, {
      props: {
        title: '测试商品',
        images: [
          { url: '/one.jpg', alt: '第一张' },
          { url: '/two.jpg', alt: '第二张' },
        ],
      },
    })
    const stage = wrapper.get('.product-gallery-stage')
    expect(wrapper.get('img').attributes('src')).toBe('/one.jpg')
    await stage.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.get('img').attributes('src')).toBe('/two.jpg')
    await wrapper.get('img').trigger('error')
    expect(wrapper.text()).toContain('图片暂未开放')
    wrapper.unmount()
  })
})
