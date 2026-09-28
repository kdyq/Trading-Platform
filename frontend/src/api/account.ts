import { requestJson } from './client'

export interface Profile {
  id: string
  login_email: string | null
  display_name: string
  has_avatar: boolean
  campus_verification_status: string
  credit_status: string
  active_products: number
  favorites: number
  orders: number
}

export interface AccountSession {
  id: string
  user_agent: string | null
  ip_address: string | null
  created_at: string
  last_used_at: string | null
  expires_at: string
  is_current: boolean
}

export function requestPasswordReset(email: string) {
  return requestJson<{ message: string }>('/api/v1/account/password-reset-requests', {
    method: 'POST',
    body: { email },
    acceptedStatuses: [202],
  })
}

export function resetPassword(token: string, newPassword: string) {
  return requestJson<{ message: string }>('/api/v1/account/password-resets', {
    method: 'POST',
    body: { token, new_password: newPassword },
  })
}

export function getProfile(accessToken: string) {
  return requestJson<Profile>('/api/v1/account/profile', { accessToken })
}

export function updateProfile(accessToken: string, displayName: string) {
  return requestJson<Profile>('/api/v1/account/profile', {
    method: 'PATCH',
    accessToken,
    body: { display_name: displayName },
  })
}

export function changePassword(accessToken: string, currentPassword: string, newPassword: string) {
  return requestJson<{ message: string }>('/api/v1/account/password-change', {
    method: 'POST',
    accessToken,
    body: { current_password: currentPassword, new_password: newPassword },
  })
}

export function getSessions(accessToken: string) {
  return requestJson<AccountSession[]>('/api/v1/account/sessions', { accessToken })
}

export function revokeSession(accessToken: string, sessionId: string) {
  return requestJson<{ message: string }>(`/api/v1/account/sessions/${sessionId}`, {
    method: 'DELETE',
    accessToken,
  })
}
