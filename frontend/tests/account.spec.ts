import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ForgotPasswordView from '../src/views/ForgotPasswordView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function mountForgotPassword(path = '/forgot-password') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/forgot-password', component: ForgotPasswordView }],
  })
  await router.push(path)
  await router.isReady()
  return mount(ForgotPasswordView, { global: { plugins: [router] } })
}

describe('account recovery', () => {
  it('shows the generic reset-request response', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ message: '如果该账户存在，重置邮件将很快送达' }, 202))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountForgotPassword()

    await wrapper.get('input[type="email"]').setValue('student@example.com')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('如果该账户存在，重置邮件将很快送达')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/account/password-reset-requests',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
  })

  it('uses the reset token from the URL and checks confirmation locally', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ message: '密码已重置，请重新登录' }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountForgotPassword(
      '/forgot-password?token=reset-token-value-1234567890123456',
    )
    const fields = wrapper.findAll('input[type="password"]')

    await fields[0].setValue('newmarket2027')
    await fields[1].setValue('different2027')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('两次输入的密码不一致')
    expect(fetchMock).not.toHaveBeenCalled()

    await fields[1].setValue('newmarket2027')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/account/password-resets',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          token: 'reset-token-value-1234567890123456',
          new_password: 'newmarket2027',
        }),
      }),
    )
  })
})
