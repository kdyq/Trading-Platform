import { requestJson } from './client'

export interface UserSummary {
  id: string
  login_email: string
  display_name: string
  status: string
  campus_verification_status: string
}

export interface AuthResponse {
  access_token: string
  access_token_expires_at: string
  token_type: 'bearer'
  user: UserSummary
}

export function requestRegistrationCode(email: string) {
  return requestJson<{ message: string }>('/api/v1/auth/email-verifications', {
    method: 'POST',
    body: { email, purpose: 'registration' },
    acceptedStatuses: [202],
  })
}

export function registerAccount(input: {
  email: string
  code: string
  display_name: string
  password: string
  accept_user_agreement: boolean
  accept_privacy_policy: boolean
}) {
  return requestJson<AuthResponse>('/api/v1/auth/register', {
    method: 'POST',
    body: input,
    acceptedStatuses: [201],
  })
}

export function loginAccount(email: string, password: string) {
  return requestJson<AuthResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: { email, password },
  })
}

export function refreshAccount() {
  return requestJson<AuthResponse>('/api/v1/auth/refresh', { method: 'POST' })
}

export function logoutAccount() {
  return requestJson<{ message: string }>('/api/v1/auth/logout', { method: 'POST' })
}
