import { getJson, requestJson } from './client'

export interface CreditSummary {
  balance: number
  level: string
  rule_version: string
}

export interface PublicCreditSummary {
  level: string
  range_label: string
}

export interface CreditLedger {
  id: string
  event_type: string
  delta: number
  balance_after: number
  reason: string
  created_at: string
}

export interface CreditLedgerPage {
  items: CreditLedger[]
  next_cursor: string | null
}

export function getMyCredit(accessToken: string) {
  return requestJson<CreditSummary>('/api/v1/credit/me', { accessToken })
}

export function getMyCreditLedgers(accessToken: string, cursor?: string) {
  const suffix = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return requestJson<CreditLedgerPage>(`/api/v1/credit/me/ledgers${suffix}`, { accessToken })
}

export function getPublicCredit(userId: string) {
  return getJson<PublicCreditSummary>(`/api/v1/credit/users/${userId}/summary`)
}
