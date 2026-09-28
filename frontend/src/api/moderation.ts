import { requestBlob, requestJson } from './client'
import type { ReportEvidence } from './reports'

export interface ModerationProduct {
  id: string
  seller_id: string
  seller_name: string
  title: string
  description: string
  price: string
  status: string
  version: number
  image_urls: string[]
  moderation_reason_code: string | null
  moderation_public_note: string | null
  created_at: string
  updated_at: string
}

export async function listModerationProducts(
  accessToken: string,
  status = 'pending_review',
  page = 1,
) {
  return requestJson<{
    items: ModerationProduct[]
    page: number
    page_size: number
    total: number
  }>(`/api/v1/moderation/products?status=${encodeURIComponent(status)}&page=${page}`, {
    accessToken,
  })
}

export async function decideModerationProduct(
  accessToken: string,
  product: ModerationProduct,
  action: 'approve' | 'reject' | 'hide' | 'restore',
  reasonCode: string,
  publicNote: string,
) {
  return requestJson<ModerationProduct>(`/api/v1/moderation/products/${product.id}/decisions`, {
    method: 'POST',
    accessToken,
    body: {
      action,
      version: product.version,
      reason_code: reasonCode,
      public_note: publicNote,
      request_id: crypto.randomUUID().replaceAll('-', ''),
      confirm_target: product.id,
    },
  })
}

export interface ModerationReport {
  id: string
  reporter_id: string
  subject_user_id: string | null
  target_type: string
  target_id: string
  reason_code: string
  details: string | null
  status: string
  public_result: string | null
  version: number
  evidence_ids: string[]
  created_at: string
  updated_at: string
}

export async function listModerationReports(accessToken: string, page = 1) {
  return requestJson<{ items: ModerationReport[]; page: number; page_size: number; total: number }>(
    `/api/v1/moderation/reports?page=${page}`,
    {
      accessToken,
    },
  )
}

export async function decideModerationReport(
  accessToken: string,
  report: ModerationReport,
  payload: {
    action: 'review' | 'dismiss' | 'violate'
    penalty_code: 'none' | 'warn' | 'hide' | 'suspend'
    penalty_points: number
    public_result: string
    internal_reason: string
  },
) {
  return requestJson<ModerationReport>(`/api/v1/moderation/reports/${report.id}/decisions`, {
    method: 'POST',
    accessToken,
    body: {
      ...payload,
      version: report.version,
      evidence_ids: report.evidence_ids,
      request_id: crypto.randomUUID().replaceAll('-', ''),
      confirm_target: report.id,
    },
  })
}

export interface ReportAppeal {
  id: string
  report_id: string
  status: string
  details: string
  review_reason: string | null
  evidence_ids: string[]
  created_at: string
  updated_at: string
}

export async function uploadAppealEvidence(accessToken: string, appealId: string, evidence: File) {
  const form = new FormData()
  form.append('evidence', evidence)
  return requestJson<ReportEvidence>(`/api/v1/moderation/appeals/${appealId}/evidence`, {
    method: 'POST',
    accessToken,
    body: form,
    acceptedStatuses: [201],
  })
}

export function downloadAppealEvidence(accessToken: string, appealId: string, evidenceId: string) {
  return requestBlob(`/api/v1/moderation/appeals/${appealId}/evidence/${evidenceId}`, accessToken)
}

export async function createReportAppeal(accessToken: string, reportId: string, details: string) {
  return requestJson<ReportAppeal>(`/api/v1/moderation/reports/${reportId}/appeals`, {
    method: 'POST',
    accessToken,
    body: { details },
    acceptedStatuses: [201],
  })
}

export async function listReportAppeals(accessToken: string, page = 1) {
  return requestJson<{ items: ReportAppeal[]; page: number; page_size: number; total: number }>(
    `/api/v1/moderation/appeals?page=${page}`,
    { accessToken },
  )
}

export async function reviewReportAppeal(
  accessToken: string,
  appealId: string,
  action: 'uphold' | 'reverse',
  reason: string,
) {
  return requestJson<ReportAppeal>(`/api/v1/moderation/appeals/${appealId}/decisions`, {
    method: 'POST',
    accessToken,
    body: {
      action,
      reason,
      request_id: crypto.randomUUID().replaceAll('-', ''),
      confirm_target: appealId,
    },
  })
}
