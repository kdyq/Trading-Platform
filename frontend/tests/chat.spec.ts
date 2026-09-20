import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../src/stores/auth'
import ChatView from '../src/views/ChatView.vue'

const conversation = {
  id: 'conversation-1',
  product_id: 'product-1',
  product_title: '高等数学教材',
  product_price: '18.50',
  product_status: 'on_sale',
  other_user_id: 'seller-1',
  other_display_name: '小林',
  last_message_at: '2026-09-20T08:00:00Z',
  last_message_preview: '教材还在',
  unread_count: 1,
}

const initialMessage = {
  id: 'message-1',
  conversation_id: conversation.id,
  sender_id: 'seller-1',
  client_message_id: 'seller_message_1',
  body: '教材还在',
  created_at: '2026-09-20T08:00:00Z',
}

class FakeWebSocket {
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(readonly url: string) {
    queueMicrotask(() => this.onopen?.())
  }

  send() {}

  close() {
    this.onclose?.()
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('chat workspace', () => {
  it('loads a private thread and persists an optimistic message', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/ws-tickets')) {
        return Promise.resolve(
          new Response(JSON.stringify({ ticket: 'opaque-ticket-value', expires_in: 30 }), {
            status: 201,
          }),
        )
      }
      if (url.includes('/messages') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { client_message_id: string; body: string }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...initialMessage,
              id: 'message-2',
              sender_id: 'buyer-1',
              client_message_id: body.client_message_id,
              body: body.body,
            }),
            { status: 201 },
          ),
        )
      }
      if (url.endsWith('/read-position')) {
        return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
      }
      if (url.endsWith('/messages')) {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [initialMessage], next_cursor: null }), {
            status: 200,
          }),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify({ items: [conversation] }), { status: 200 }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('WebSocket', FakeWebSocket)

    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().applySession('access-token', {
      id: 'buyer-1',
      login_email: 'buyer@example.edu.cn',
      display_name: '买家',
      status: 'active',
      campus_verification_status: 'verified',
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/messages/:id?', component: ChatView },
        { path: '/products/:id', component: { template: '<div />' } },
      ],
    })
    await router.push('/messages/conversation-1')
    await router.isReady()

    const wrapper = mount(ChatView, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('高等数学教材 · ¥18.50')
    expect(wrapper.text()).toContain('教材还在')
    expect(wrapper.text()).toContain('请勿发送身份证、验证码或支付密码')

    await wrapper.get('#chat-message').setValue('周三中午图书馆见')
    await wrapper.get('.composer').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('周三中午图书馆见')
    expect(wrapper.text()).toContain('已发送')
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => String(input).includes('/messages') && init?.method === 'POST',
      ),
    ).toBe(true)
    wrapper.unmount()
  })
})
