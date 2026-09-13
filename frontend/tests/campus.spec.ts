import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../src/stores/auth'
import CampusVerificationView from '../src/views/CampusVerificationView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function renderCampus(fetchMock: ReturnType<typeof vi.fn>, settle = true) {
  vi.stubGlobal('fetch', fetchMock)
  const pinia = createPinia()
  useAuthStore(pinia).applySession('campus-access', {
    id: '11111111-1111-1111-1111-111111111111',
    login_email: 'login@example.com',
    display_name: '小橘同学',
    status: 'active',
    campus_verification_status: 'unapplied',
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/campus-verification', component: CampusVerificationView },
      { path: '/login', component: { template: '<p>登录</p>' } },
    ],
  })
  await router.push('/campus-verification')
  await router.isReady()
  const wrapper = mount(CampusVerificationView, { global: { plugins: [pinia, router] } })
  if (settle) await flushPromises()
  return wrapper
}

describe('campus verification', () => {
  it('completes the email-code flow with separate campus email copy', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/campus/schools')) {
        return jsonResponse([
          {
            id: 'school-1',
            name: '测试学校',
            campuses: [{ id: 'campus-1', name: '主校区' }],
            email_domains: ['*.campus.edu'],
          },
        ])
      }
      if (url.endsWith('/campus/policy')) {
        return jsonResponse({
          verification_days: 365,
          appeal_retention_days: 180,
          appeal_max_bytes: 10 * 1024 * 1024,
          appeal_media_types: ['application/pdf', 'image/png', 'image/jpeg'],
        })
      }
      if (url.endsWith('/campus/status') && init?.method !== 'POST') {
        return jsonResponse({
          status: 'unapplied',
          verification_id: null,
          campus_id: null,
          campus_email: null,
          verified_at: null,
          expires_at: null,
          appeal: null,
        })
      }
      if (url.endsWith('/campus/email-verifications/confirm')) {
        return jsonResponse({
          status: 'verified',
          verification_id: 'verification-1',
          campus_id: 'campus-1',
          campus_email: 'student@campus.edu',
          verified_at: '2026-09-13T09:00:00Z',
          expires_at: '2027-09-13T09:00:00Z',
          appeal: null,
        })
      }
      if (url.endsWith('/campus/email-verifications')) {
        return jsonResponse(
          { verification_id: 'verification-1', message: '校园认证验证码已发送' },
          202,
        )
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const wrapper = await renderCampus(fetchMock)

    expect(wrapper.text()).toContain('登录邮箱只用于账户登录')
    expect(wrapper.text()).toContain('支持域名：*.campus.edu')
    await wrapper.get('input[type="email"]').setValue('student@campus.edu')
    await wrapper.findAll('form')[0].trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('校园认证验证码已发送')

    await wrapper.get('input[inputmode="numeric"]').setValue('123456')
    const confirmForm = wrapper.findAll('form').find((form) => form.text().includes('确认验证码'))
    await confirmForm?.trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('校园身份认证成功')
    expect(wrapper.text()).toContain('已通过')
  })

  it('shows an honest empty state when no schools are configured', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/campus/schools')) return jsonResponse([])
      if (String(input).endsWith('/campus/policy')) {
        return jsonResponse({
          verification_days: 365,
          appeal_retention_days: 180,
          appeal_max_bytes: 10 * 1024 * 1024,
          appeal_media_types: ['application/pdf', 'image/png', 'image/jpeg'],
        })
      }
      return jsonResponse({
        status: 'unapplied',
        verification_id: null,
        campus_id: null,
        campus_email: null,
        verified_at: null,
        expires_at: null,
        appeal: null,
      })
    })
    const wrapper = await renderCampus(fetchMock)

    expect(wrapper.text()).toContain('尚未配置学校')
    expect(wrapper.text()).toContain('管理员配置学校、校区和校园邮箱域名后即可开始认证')
  })

  it('separates loading from the real empty state', async () => {
    let resolveSchools: ((response: Response) => void) | undefined
    const schoolsResponse = new Promise<Response>((resolve) => {
      resolveSchools = resolve
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/campus/schools')) return schoolsResponse
      if (url.endsWith('/campus/policy')) {
        return jsonResponse({
          verification_days: 365,
          appeal_retention_days: 180,
          appeal_max_bytes: 10 * 1024 * 1024,
          appeal_media_types: ['application/pdf', 'image/png', 'image/jpeg'],
        })
      }
      return jsonResponse({
        status: 'unapplied',
        verification_id: null,
        campus_id: null,
        campus_email: null,
        verified_at: null,
        expires_at: null,
        appeal: null,
      })
    })
    const wrapper = await renderCampus(fetchMock, false)

    expect(wrapper.text()).toContain('正在加载认证信息')
    expect(wrapper.text()).not.toContain('尚未配置学校')
    resolveSchools?.(jsonResponse([]))
    await flushPromises()
    expect(wrapper.text()).toContain('尚未配置学校')
  })

  it('does not present a request failure as an empty school list', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/campus/schools')) return jsonResponse({}, 500)
      return jsonResponse({})
    })
    const wrapper = await renderCampus(fetchMock)

    expect(wrapper.text()).toContain('认证信息加载失败')
    expect(wrapper.text()).not.toContain('尚未配置学校')
  })
})
