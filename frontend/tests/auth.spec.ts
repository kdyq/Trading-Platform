import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import LoginView from '../src/views/LoginView.vue'
import RegisterView from '../src/views/RegisterView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('account forms', () => {
  it('submits login credentials and reports a safe API error', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ code: 'invalid_credentials', message: '邮箱或密码不正确' }, 401),
      )
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(LoginView, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: true },
        mocks: { $router: { push: vi.fn() } },
      },
    })

    await wrapper.get('input[name="email"]').setValue('student@example.com')
    await wrapper.get('input[name="password"]').setValue('wrong123')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/login',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
    expect(wrapper.text()).toContain('邮箱或密码不正确')
  })

  it('requests a registration code without exposing account state', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ message: '如果该邮箱可以注册，验证码邮件将很快送达' }, 202))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(RegisterView, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: true },
        mocks: { $router: { push: vi.fn() } },
      },
    })

    await wrapper.get('input[name="email"]').setValue('student@example.com')
    await wrapper.get('button[type="button"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('验证码邮件将很快送达')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('accepts a password that meets the documented browser constraints', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const wrapper = mount(RegisterView, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: true },
        mocks: { $router: { push: vi.fn() } },
      },
    })
    const password = wrapper.get<HTMLInputElement>('input[name="password"]')

    await password.setValue('market2026')

    expect(password.element.validity.patternMismatch).toBe(false)
    expect(password.element.checkValidity()).toBe(true)
  })
})
