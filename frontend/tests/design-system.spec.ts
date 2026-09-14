import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it } from 'vitest'

import ProductCard from '../src/components/market/ProductCard.vue'
import UiButton from '../src/components/ui/UiButton.vue'
import UiDialog from '../src/components/ui/UiDialog.vue'

afterEach(() => {
  document.body.innerHTML = ''
})

describe('design system primitives', () => {
  it('renders the four product card states without hiding key information', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [] })
    const states = ['available', 'sold', 'pending'] as const

    for (const state of states) {
      const wrapper = mount(ProductCard, {
        props: {
          id: 'product-id',
          title: '台灯（组件示例）',
          price: '36',
          campus: '校区示例',
          department: '学院示例',
          condition: '九成新',
          publishedAt: '今天',
          state,
        },
        global: { plugins: [router] },
      })
      expect(wrapper.text()).toContain('台灯（组件示例）')
      expect(wrapper.text()).toContain('¥36')
      expect(wrapper.text()).toContain('校区示例')
      if (state === 'sold') expect(wrapper.text()).toContain('已售出')
      if (state === 'pending') expect(wrapper.text()).toContain('待审核')
      wrapper.unmount()
    }

    const loading = mount(ProductCard, {
      props: { state: 'loading' },
      global: { plugins: [router] },
    })
    expect(loading.findAll('.ui-skeleton')).toHaveLength(4)
  })

  it('exposes disabled and busy button state to the browser', () => {
    const wrapper = mount(UiButton, { props: { busy: true }, slots: { default: '保存' } })
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button').attributes('aria-busy')).toBe('true')
  })

  it('closes the dialog with Escape', async () => {
    const wrapper = mount(UiDialog, {
      props: { open: true, title: '测试对话框' },
      slots: { default: '<button type="button">第一项</button>' },
      attachTo: document.body,
    })
    const panel = document.body.querySelector<HTMLElement>('[role="dialog"]')
    expect(panel).not.toBeNull()
    panel?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})
