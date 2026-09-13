import { requestBlob, requestJson } from './client'

export interface CampusSummary {
  id: string
  name: string
}

export interface SchoolSummary {
  id: string
  name: string
  campuses: CampusSummary[]
  email_domains: string[]
}

export interface CampusAppeal {
  id: string
  status: string
  original_filename: string
  retention_until: string
}

export interface CampusStatus {
  status: string
  verification_id: string | null
  campus_id: string | null
  campus_email: string | null
  verified_at: string | null
  expires_at: string | null
  appeal: CampusAppeal | null
}

export interface CampusPolicy {
  verification_days: number
  appeal_retention_days: number
  appeal_max_bytes: number
  appeal_media_types: string[]
}

export function getCampusPolicy() {
  return requestJson<CampusPolicy>('/api/v1/campus/policy')
}

export function getSchools() {
  return requestJson<SchoolSummary[]>('/api/v1/campus/schools')
}

export function getCampusStatus(accessToken: string) {
  return requestJson<CampusStatus>('/api/v1/campus/status', { accessToken })
}

export function requestCampusCode(
  accessToken: string,
  input: { school_id: string; campus_id: string; campus_email: string },
) {
  return requestJson<{ verification_id: string; message: string }>(
    '/api/v1/campus/email-verifications',
    {
      method: 'POST',
      accessToken,
      body: input,
      acceptedStatuses: [202],
    },
  )
}

export function confirmCampusCode(accessToken: string, verificationId: string, code: string) {
  return requestJson<CampusStatus>('/api/v1/campus/email-verifications/confirm', {
    method: 'POST',
    accessToken,
    body: { verification_id: verificationId, code },
  })
}

export function submitCampusAppeal(
  accessToken: string,
  input: { campusId: string; reason: string; material: File },
) {
  const form = new FormData()
  form.set('campus_id', input.campusId)
  form.set('reason', input.reason)
  form.set('material', input.material)
  return requestJson<CampusAppeal>('/api/v1/campus/appeals', {
    method: 'POST',
    accessToken,
    body: form,
    acceptedStatuses: [201],
  })
}

export function downloadCampusAppeal(accessToken: string, appealId: string) {
  return requestBlob(`/api/v1/campus/appeals/${appealId}/material`, accessToken)
}
