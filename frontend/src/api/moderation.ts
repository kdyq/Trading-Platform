import { requestJson } from './client'

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

export async function listModerationProducts(accessToken: string, status = 'pending_review') {
  return requestJson<{ items: ModerationProduct[] }>(
    `/api/v1/moderation/products?status=${encodeURIComponent(status)}`,
    { accessToken },
  )
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
    },
  })
}
