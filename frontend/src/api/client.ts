const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function getJson<T>(path: string, acceptedStatuses: number[] = [200]): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 5000)

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    if (!acceptedStatuses.includes(response.status)) {
      throw new ApiError('服务返回了无法处理的响应', response.status)
    }
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    const message =
      error instanceof DOMException && error.name === 'AbortError' ? '连接服务超时' : '无法连接服务'
    throw new ApiError(message, null)
  } finally {
    window.clearTimeout(timeout)
  }
}
