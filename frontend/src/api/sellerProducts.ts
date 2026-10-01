import { requestBlob, requestJson } from './client'

export interface CatalogCategory {
  id: string
  code: string
  slug: string
  name: string
  display_order: number
  children: CatalogCategory[]
}

export interface SellerProductImage {
  id: string
  url: string
  thumbnail_url: string
  alt_text: string | null
  display_order: number
}

export interface SellerProduct {
  id: string
  title: string
  description: string
  price: string
  original_price: string | null
  category_id: string
  campus_id: string
  condition: string
  is_negotiable: boolean
  delivery_notes: string | null
  status: string
  appeal_report_id?: string | null
  version: number
  updated_at: string
  images: SellerProductImage[]
}

export interface ProductImageUpload {
  id: string
  original_filename: string
  media_type: string
  size_bytes: number
  width: number
  height: number
  expires_at: string
  preview_url: string
}

export interface SellerProductInput {
  title: string
  description: string
  price: string
  original_price: string | null
  category_id: string
  campus_id: string
  condition: string
  is_negotiable: boolean
  delivery_notes: string | null
}

export interface ProductImageReference {
  kind: 'existing' | 'upload'
  id: string
}

export function getCatalogCategories() {
  return requestJson<CatalogCategory[]>('/api/v1/catalog/categories')
}

export function createSellerProduct(accessToken: string, input: SellerProductInput) {
  return requestJson<SellerProduct>('/api/v1/seller/products', {
    method: 'POST',
    accessToken,
    body: input,
    acceptedStatuses: [201],
  })
}

export function listSellerProducts(accessToken: string) {
  return requestJson<{ items: SellerProduct[] }>('/api/v1/seller/products', { accessToken })
}

export function getSellerProduct(accessToken: string, productId: string) {
  return requestJson<SellerProduct>(`/api/v1/seller/products/${productId}`, { accessToken })
}

export function updateSellerProduct(
  accessToken: string,
  productId: string,
  version: number,
  input: SellerProductInput,
  images: ProductImageReference[],
) {
  return requestJson<SellerProduct>(`/api/v1/seller/products/${productId}`, {
    method: 'PATCH',
    accessToken,
    body: { ...input, version, images },
  })
}

export function transitionSellerProduct(
  accessToken: string,
  productId: string,
  action: 'submit' | 'withdraw' | 'hide' | 'sold',
  version: number,
) {
  return requestJson<SellerProduct>(`/api/v1/seller/products/${productId}/${action}`, {
    method: 'POST',
    accessToken,
    body: { version },
  })
}

export function uploadProductImage(accessToken: string, file: File, signal?: AbortSignal) {
  const form = new FormData()
  form.set('image', file)
  return requestJson<ProductImageUpload>('/api/v1/product-images/uploads', {
    method: 'POST',
    accessToken,
    body: form,
    signal,
    acceptedStatuses: [201],
  })
}

export function discardProductImage(accessToken: string, uploadId: string) {
  return requestJson<never>(`/api/v1/product-images/uploads/${uploadId}`, {
    method: 'DELETE',
    accessToken,
    acceptedStatuses: [204],
  })
}

export function getProductImagePreview(accessToken: string, uploadId: string) {
  return requestBlob(`/api/v1/product-images/uploads/${uploadId}/preview`, accessToken)
}

export function getSellerProductImage(accessToken: string, path: string) {
  return requestBlob(path, accessToken)
}
