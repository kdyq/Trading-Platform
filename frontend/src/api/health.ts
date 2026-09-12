import { getJson } from './client'

type DependencyState = {
  status: 'ready' | 'unavailable'
  reason: 'not_configured' | 'connection_failed' | null
}

export type ReadinessResponse = {
  status: 'ready' | 'not_ready'
  dependencies: {
    database: DependencyState
    redis: DependencyState
  }
}

export function getReadiness(): Promise<ReadinessResponse> {
  return getJson<ReadinessResponse>('/api/v1/health/ready', [200, 503])
}
