import { getJson, requestJson } from './client'

export interface PublicCategory {
  id: string
  code: string
  name: string
}

export interface PublicProduct {
  id: string
  title: string
  price: string
  status: 'on_sale' | 'reserved' | 'sold'
  published_at: string | null
  campus_name: string
  school_name: string
  seller_name: string
  seller_verified: boolean
  category_code: string
  category_name: string
  condition: 'new' | 'like_new' | 'good' | 'fair'
  is_negotiable: boolean
  view_count: number
  image_url: string | null
  image_alt: string | null
}

export interface PublicCampus {
  id: string
  name: string
  school_name: string
}

export interface ProductSearchParams {
  keyword?: string
  category?: string
  campus?: string
  min_price?: string
  max_price?: string
  condition?: string
  negotiable?: string
  status?: string
  sort?: string
  page?: string
}

export interface PublicProductList {
  items: PublicProduct[]
  total: number
  page: number
  page_size: number
}

export interface PublicMarketSummary {
  available_products: number
  active_campuses: number
  verified_sellers: number
}

export async function getMarketCategories() {
  return getJson<PublicCategory[]>('/api/v1/market/categories')
}

export async function getMarketCampuses() {
  return getJson<PublicCampus[]>('/api/v1/market/campuses')
}

export async function searchProducts(params: ProductSearchParams, signal?: AbortSignal) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) query.set(key, value)
  }
  return requestJson<PublicProductList>(`/api/v1/market/products?${query}`, { signal })
}

export async function getLatestProducts(limit = 8) {
  return getJson<PublicProductList>(`/api/v1/market/products?limit=${limit}`)
}

export async function getMarketSummary() {
  return getJson<PublicMarketSummary>('/api/v1/market/summary')
}
