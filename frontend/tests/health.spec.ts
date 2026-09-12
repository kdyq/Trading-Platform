import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, getJson } from '../src/api/client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('API client', () => {
  it('returns typed JSON for an accepted response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ready' }), { status: 200 })),
    )

    await expect(getJson<{ status: string }>('/api/v1/health/ready')).resolves.toEqual({
      status: 'ready',
    })
  })

  it('reports an unexpected status without exposing the response body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('private detail', { status: 500 })),
    )

    await expect(getJson('/api/v1/health/ready')).rejects.toEqual(
      new ApiError('服务返回了无法处理的响应', 500),
    )
  })
})
