import { requestJson } from './client'

export type ReportTargetType = 'product' | 'user' | 'message' | 'order'

export interface ReportEvidence {
  id: string
  original_filename: string
  media_type: string
  size_bytes: number
  created_at: string
}

export interface ReportEvent {
  id: string
  from_status: string | null
  to_status: string
  public_note: string | null
  created_at: string
}

export interface ReportItem {
  id: string
  target_type: ReportTargetType
  target_id: string
  reason_code: string
  details: string | null
  status: 'open' | 'reviewing' | 'resolved' | 'dismissed' | 'withdrawn' | 'appealed'
  public_result: string | null
  version: number
  evidence: ReportEvidence[]
  events: ReportEvent[]
  created_at: string
  updated_at: string
}

export async function createReport(
  accessToken: string,
  payload: {
    target_type: ReportTargetType
    target_id: string
    reason_code: string
    details: string
  },
) {
  return requestJson<ReportItem>('/api/v1/reports', {
    method: 'POST',
    accessToken,
    body: payload,
    acceptedStatuses: [201],
  })
}

export async function uploadReportEvidence(accessToken: string, reportId: string, evidence: File) {
  const form = new FormData()
  form.append('evidence', evidence)
  return requestJson<ReportEvidence>(`/api/v1/reports/${reportId}/evidence`, {
    method: 'POST',
    accessToken,
    body: form,
    acceptedStatuses: [201],
  })
}

export async function listReports(accessToken: string) {
  return requestJson<{ items: ReportItem[] }>('/api/v1/reports', { accessToken })
}

export async function withdrawReport(accessToken: string, reportId: string) {
  return requestJson<ReportItem>(`/api/v1/reports/${reportId}/withdraw`, {
    method: 'POST',
    accessToken,
  })
}
