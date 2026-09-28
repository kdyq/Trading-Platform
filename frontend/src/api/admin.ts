import { requestBlob, requestJson } from './client'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface AdminCapabilities {
  roles: string[]
  permissions: string[]
  must_change_password: boolean
}

export interface Staff {
  id: string
  username: string | null
  email: string
  display_name: string
  status: string
  roles: string[]
  created_at: string
}

export interface ManagedUser {
  id: string
  username: string | null
  email: string
  display_name: string
  status: string
  campus_status: string
  created_at: string
}

export interface ManagedProduct {
  id: string
  title: string
  seller_id: string
  seller_name: string
  status: string
  report_penalty_active: boolean
  price: string
  version: number
  created_at: string
}

export interface ManagedCategory {
  id: string
  parent_id: string | null
  code: string
  slug: string
  name: string
  level: number
  display_order: number
  is_active: boolean
  deleted_at: string | null
  version: number
}

export interface ManagedCampus {
  id: string
  school_id: string
  school_name: string
  code: string
  name: string
  display_order: number
  is_active: boolean
  deleted_at: string | null
  version: number
}

export interface CampusAppeal {
  id: string
  user_id: string
  campus_id: string
  status: string
  reason: string
  original_filename: string
  created_at: string
  reviewed_at: string | null
  review_reason: string | null
}

export interface DashboardMetrics {
  starts_at: string
  ends_at: string
  registered_users: number
  verified_campus: number
  published_products: number
  completed_orders: number
  submitted_reports: number
  pending_products_now: number
  active_sessions_now: number
}

export interface AuditEntry {
  id: string
  actor_id: string | null
  action: string
  target_type: string
  target_id: string | null
  audit_data: Record<string, unknown>
  created_at: string
}

export interface AuditExport {
  id: string
  status: string
  created_at: string
  expires_at: string
  revoked: boolean
  failure_code: string | null
}

function query(params: Record<string, string | number | null | undefined>) {
  const values = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') values.set(key, String(value))
  }
  return values.toString()
}

export function adminCapabilities(token: string) {
  return requestJson<AdminCapabilities>('/api/v1/admin/me', { accessToken: token })
}

export function listStaff(token: string, page: number) {
  return requestJson<Page<Staff>>(`/api/v1/admin/staff?${query({ page })}`, { accessToken: token })
}

export function inviteStaff(token: string, email: string, role: string, reason: string) {
  return requestJson<Staff>('/api/v1/admin/staff/invitations', {
    method: 'POST',
    accessToken: token,
    body: { email, confirm_email: email, role, reason },
    acceptedStatuses: [201],
  })
}

export function updateStaffRoles(token: string, targetId: string, roles: string[], reason: string) {
  return requestJson<Staff>(`/api/v1/admin/staff/${targetId}/roles`, {
    method: 'PUT',
    accessToken: token,
    body: { roles, reason, confirm_target: targetId },
  })
}

export function updateStaffStatus(token: string, targetId: string, status: string, reason: string) {
  return requestJson<Staff>(`/api/v1/admin/staff/${targetId}/status`, {
    method: 'PATCH',
    accessToken: token,
    body: { status, reason, confirm_target: targetId },
  })
}

export function listUsers(token: string, page: number, search: string, status: string) {
  return requestJson<Page<ManagedUser>>(
    `/api/v1/admin/users?${query({ page, query: search, status })}`,
    { accessToken: token },
  )
}

export function updateUserStatus(token: string, targetId: string, status: string, reason: string) {
  return requestJson<ManagedUser>(`/api/v1/admin/users/${targetId}/status`, {
    method: 'PATCH',
    accessToken: token,
    body: { status, reason, confirm_target: targetId },
  })
}

export function listProducts(token: string, page: number, search: string, status: string) {
  return requestJson<Page<ManagedProduct>>(
    `/api/v1/admin/products?${query({ page, query: search, status })}`,
    { accessToken: token },
  )
}

export function manageProduct(
  token: string,
  product: ManagedProduct,
  action: 'hide' | 'restore',
  reason: string,
) {
  return requestJson<ManagedProduct>(`/api/v1/moderation/products/${product.id}/decisions`, {
    method: 'POST',
    accessToken: token,
    body: {
      action,
      version: product.version,
      reason_code: action === 'hide' ? 'operations' : 'cleared',
      public_note: reason,
      request_id: crypto.randomUUID().replaceAll('-', ''),
      confirm_target: product.id,
    },
  })
}

export function listCampusAppeals(token: string, page: number, status = 'pending') {
  return requestJson<Page<CampusAppeal>>(
    `/api/v1/admin/campus-appeals?${query({ page, status })}`,
    { accessToken: token },
  )
}

export function listCategories(token: string, page: number) {
  return requestJson<Page<ManagedCategory>>(`/api/v1/admin/categories?${query({ page })}`, {
    accessToken: token,
  })
}

export function listCampuses(token: string, page: number) {
  return requestJson<Page<ManagedCampus>>(`/api/v1/admin/campuses?${query({ page })}`, {
    accessToken: token,
  })
}

export function updateCatalogItem(
  token: string,
  kind: 'categories' | 'campuses',
  item: ManagedCategory | ManagedCampus,
  reason: string,
) {
  return requestJson<ManagedCategory | ManagedCampus>(`/api/v1/catalog/admin/${kind}/${item.id}`, {
    method: 'PATCH',
    accessToken: token,
    body: {
      version: item.version,
      display_order: item.display_order,
      is_active: item.is_active,
      reason,
      confirm_target: item.id,
    },
  })
}

export function decideCampusAppeal(token: string, id: string, action: string, reason: string) {
  return requestJson<CampusAppeal>(`/api/v1/admin/campus-appeals/${id}/decisions`, {
    method: 'POST',
    accessToken: token,
    body: { action, reason, confirm_target: id },
  })
}

export function campusAppealMaterial(token: string, id: string) {
  return requestBlob(`/api/v1/campus/appeals/${id}/material`, token)
}

export function dashboardMetrics(token: string) {
  return requestJson<DashboardMetrics>('/api/v1/admin/dashboard', { accessToken: token })
}

export function listAudit(token: string, page: number, action: string) {
  return requestJson<Page<AuditEntry>>(`/api/v1/admin/audit?${query({ page, action })}`, {
    accessToken: token,
  })
}

export function createAuditExport(token: string, reason: string, action: string) {
  const now = new Date()
  return requestJson<AuditExport>('/api/v1/admin/audit-exports', {
    method: 'POST',
    accessToken: token,
    body: {
      starts_at: new Date(now.getTime() - 7 * 86400000).toISOString(),
      ends_at: now.toISOString(),
      action: action || null,
      reason,
    },
    acceptedStatuses: [202],
  })
}

export function getAuditExport(token: string, id: string) {
  return requestJson<AuditExport>(`/api/v1/admin/audit-exports/${id}`, { accessToken: token })
}

export function listAuditExports(token: string, page: number) {
  return requestJson<Page<AuditExport>>(`/api/v1/admin/audit-exports?${query({ page })}`, {
    accessToken: token,
  })
}

export function downloadAuditExport(token: string, id: string) {
  return requestBlob(`/api/v1/admin/audit-exports/${id}/download`, token)
}

export function revokeAuditExport(token: string, id: string) {
  return requestJson<AuditExport>(`/api/v1/admin/audit-exports/${id}`, {
    method: 'DELETE',
    accessToken: token,
  })
}
