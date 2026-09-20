export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly code: string | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

interface ApiErrorPayload {
  code?: string
  message?: string
}

interface RequestOptions {
  method?: string
  body?: unknown
  accessToken?: string | null
  acceptedStatuses?: number[]
  signal?: AbortSignal
}

export async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 5000)
  const abortFromCaller = () => controller.abort()
  options.signal?.addEventListener('abort', abortFromCaller, { once: true })

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(options.body === undefined || options.body instanceof FormData
          ? {}
          : { 'Content-Type': 'application/json' }),
        ...(options.accessToken ? { Authorization: `Bearer ${options.accessToken}` } : {}),
      },
      body:
        options.body === undefined
          ? undefined
          : options.body instanceof FormData
            ? options.body
            : JSON.stringify(options.body),
      signal: controller.signal,
    })
    if (!(options.acceptedStatuses ?? [200]).includes(response.status)) {
      let payload: ApiErrorPayload = {}
      try {
        payload = (await response.json()) as ApiErrorPayload
      } catch {
        // Non-JSON failures use the stable fallback below.
      }
      throw new ApiError(
        payload.message ?? '服务返回了无法处理的响应',
        response.status,
        payload.code ?? null,
      )
    }
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    const message =
      error instanceof DOMException && error.name === 'AbortError' ? '连接服务超时' : '无法连接服务'
    throw new ApiError(message, null)
  } finally {
    window.clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abortFromCaller)
  }
}

export async function requestBlob(path: string, accessToken: string): Promise<Blob> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 5000)
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      credentials: 'include',
      headers: { Authorization: `Bearer ${accessToken}` },
      signal: controller.signal,
    })
    if (!response.ok) {
      let payload: ApiErrorPayload = {}
      try {
        payload = (await response.json()) as ApiErrorPayload
      } catch {
        // Non-JSON failures use the stable fallback below.
      }
      throw new ApiError(
        payload.message ?? '服务返回了无法处理的响应',
        response.status,
        payload.code ?? null,
      )
    }
    return response.blob()
  } catch (error) {
    if (error instanceof ApiError) throw error
    const message =
      error instanceof DOMException && error.name === 'AbortError' ? '连接服务超时' : '无法连接服务'
    throw new ApiError(message, null)
  } finally {
    window.clearTimeout(timeout)
  }
}

export async function getJson<T>(path: string, acceptedStatuses: number[] = [200]): Promise<T> {
  return requestJson<T>(path, { acceptedStatuses })
}
