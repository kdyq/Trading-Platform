import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MarketView from '../src/views/MarketView.vue'

function jsonResponse(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
}

function mockMarketFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/categories')) {
      return jsonResponse([{ id: 'category-1', code: 'books', name: '教材书籍' }])
    }
    if (url.includes('/campuses')) {
      return jsonResponse([{ id: 'campus-1', name: '东校区', school_name: '测试大学' }])
    }
    return jsonResponse({
      items: [],
      total: 0,
      page: 1,
      page_size: 12,
      next_cursor: null,
    })
  })
}

async function renderMarket(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/market', component: MarketView }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(MarketView, { global: { plugins: [router] } })
  await flushPromises()
  return { router, wrapper }
}

beforeEach(() => {
  vi.stubGlobal('fetch', mockMarketFetch())
  vi.stubGlobal('scrollTo', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('market search', () => {
  it('restores filters from the URL and requests matching products', async () => {
    const { wrapper } = await renderMarket(
      '/market?category=books&condition=good&page=2&cursor=test-cursor',
    )

    const category = wrapper.get('#desktop-filter-category').element as HTMLSelectElement
    const condition = wrapper.get('#desktop-filter-condition').element as HTMLSelectElement
    expect(category.value).toBe('books')
    expect(condition.value).toBe('good')
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('category=books'),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('page=2'),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('cursor=test-cursor'),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    wrapper.unmount()
  })

  it('debounces keywords into a shareable URL', async () => {
    const { router, wrapper } = await renderMarket('/market')
    await wrapper.get('#market-keyword').setValue('高数')
    await new Promise((resolve) => window.setTimeout(resolve, 350))
    await flushPromises()

    expect(router.currentRoute.value.query.keyword).toBe('高数')
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining(`keyword=${encodeURIComponent('高数')}`),
      expect.any(Object),
    )
    wrapper.unmount()
  })

  it('opens the mobile filter dialog and clears filters', async () => {
    const { router, wrapper } = await renderMarket('/market?category=books')
    await wrapper.get('.mobile-filter-button').trigger('click')
    const dialog = document.body.querySelector<HTMLElement>('[role="dialog"]')
    expect(dialog?.textContent).toContain('筛选商品')

    const category = document.body.querySelector<HTMLSelectElement>('#mobile-filter-category')
    expect(category).not.toBeNull()
    category!.value = 'books'
    category!.dispatchEvent(new Event('change'))
    document.body.querySelector<HTMLButtonElement>('[role="dialog"] .ui-button-secondary')!.click()
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
    wrapper.unmount()
  })

  it('aborts an unfinished product request when the URL changes', async () => {
    let productRequestCount = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void init
      const url = String(input)
      if (url.includes('/categories')) return jsonResponse([])
      if (url.includes('/campuses')) return jsonResponse([])
      productRequestCount += 1
      if (productRequestCount === 1) return new Promise<Response>(() => undefined)
      return jsonResponse({
        items: [],
        total: 0,
        page: 1,
        page_size: 12,
        next_cursor: null,
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const { router, wrapper } = await renderMarket('/market')
    const firstProductCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('/products'),
    )
    const firstSignal = firstProductCall?.[1]?.signal
    expect(firstSignal?.aborted).toBe(false)

    await router.push('/market?category=books')
    await flushPromises()
    expect(firstSignal?.aborted).toBe(true)
    expect(productRequestCount).toBe(2)
    wrapper.unmount()
  })

  it('moves to the next page, requests its URL state, and scrolls to the top', async () => {
    const fetchMock = mockMarketFetch()
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/categories')) return jsonResponse([])
      if (url.includes('/campuses')) return jsonResponse([])
      return jsonResponse({
        items: [],
        total: 25,
        page: 1,
        page_size: 12,
        next_cursor: 'next-page',
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const { router, wrapper } = await renderMarket('/market')
    await wrapper.get('nav[aria-label="商品分页"] button:last-child').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.page).toBe('2')
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('page=2'), expect.any(Object))
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('cursor=next-page'),
      expect.any(Object),
    )
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
    wrapper.unmount()
  })

  it('does not reuse a stale cursor while the next page is loading', async () => {
    let productRequests = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/categories') || url.includes('/campuses')) return jsonResponse([])
      productRequests += 1
      if (productRequests > 1) return new Promise<Response>(() => undefined)
      return jsonResponse({
        items: [],
        total: 36,
        page: 1,
        page_size: 12,
        next_cursor: 'page-two',
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const { router, wrapper } = await renderMarket('/market')
    const next = wrapper.get('nav[aria-label="商品分页"] button:last-child')
    await next.trigger('click')
    await flushPromises()
    await next.trigger('click')

    expect(router.currentRoute.value.query.page).toBe('2')
    expect(productRequests).toBe(2)
    wrapper.unmount()
  })

  it('disables previous navigation when a deep link has no session cursor history', async () => {
    const fetchMock = mockMarketFetch()
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/categories') || url.includes('/campuses')) return jsonResponse([])
      return jsonResponse({
        items: [],
        total: 36,
        page: 3,
        page_size: 12,
        next_cursor: null,
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const { router, wrapper } = await renderMarket('/market?page=3&cursor=current-page')
    const previous = wrapper.get('nav[aria-label="商品分页"] button:first-child')
    expect(previous.attributes('disabled')).toBeDefined()
    expect(router.currentRoute.value.query).toEqual({ page: '3', cursor: 'current-page' })
    wrapper.unmount()
  })
})
