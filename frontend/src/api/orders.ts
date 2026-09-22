import { requestJson } from './client'

export type OrderStatus =
  | 'pending_seller_confirmation'
  | 'accepted'
  | 'scheduled'
  | 'seller_delivered'
  | 'completed'
  | 'cancelled'
  | 'expired'
  | 'disputed'

export interface OrderSummary {
  id: string
  product_id: string
  amount: string
  status: OrderStatus
  role: 'buying' | 'selling'
  product_title: string
  campus_name: string
  counterparty_name: string
  payment_mode: string
  image_url: string | null
  scheduled_for: string | null
  created_at: string
}

export interface MeetingProposal {
  id: string
  order_id: string
  proposer_id: string
  proposed_for: string
  location_text: string
  status: 'pending' | 'accepted' | 'superseded' | 'withdrawn'
  buyer_confirmed_at: string | null
  seller_confirmed_at: string | null
  created_at: string
}

export interface OrderEvent {
  id: string
  actor_id: string | null
  from_status: OrderStatus | null
  to_status: OrderStatus
  note: string | null
  created_at: string
}

export interface Review {
  id: string
  reviewer_id: string
  reviewer_name: string
  reviewee_id: string
  rating: number
  tags: string[]
  content: string | null
  created_at: string
}

export interface OrderDetail {
  id: string
  product_id: string
  conversation_id: string | null
  buyer_id: string
  seller_id: string
  amount: string
  status: OrderStatus
  product_title: string
  campus_name: string
  buyer_display_name: string
  seller_display_name: string
  payment_mode: string
  expires_at: string | null
  scheduled_for: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  cancellation_reason_code: string | null
  cancellation_note: string | null
  dispute_reason_code: string | null
  dispute_details: string | null
  seller_delivered_at: string | null
  events: OrderEvent[]
  meeting_proposals: MeetingProposal[]
  reviews: Review[]
  can_review: boolean
  review_deadline: string | null
}

export interface OrderList {
  items: OrderSummary[]
  next_cursor: string | null
}

export function actionId(prefix: string) {
  return `${prefix}_${crypto.randomUUID()}`
}

export function listOrders(
  accessToken: string,
  role: 'buying' | 'selling',
  status?: OrderStatus,
  cursor?: string,
) {
  const query = new URLSearchParams({ role, limit: '20' })
  if (status) query.set('status', status)
  if (cursor) query.set('cursor', cursor)
  return requestJson<OrderList>(`/api/v1/orders?${query}`, { accessToken })
}

export function getOrder(accessToken: string, orderId: string) {
  return requestJson<OrderDetail>(`/api/v1/orders/${orderId}`, { accessToken })
}

export function createOrder(accessToken: string, productId: string, conversationId?: string) {
  return requestJson<OrderDetail>('/api/v1/orders', {
    method: 'POST',
    accessToken,
    acceptedStatuses: [201],
    body: {
      product_id: productId,
      conversation_id: conversationId,
      idempotency_key: actionId('create'),
    },
  })
}

function orderAction(accessToken: string, orderId: string, action: string) {
  return requestJson<OrderDetail>(`/api/v1/orders/${orderId}/${action}`, {
    method: 'POST',
    accessToken,
    body: { client_action_id: actionId(action) },
  })
}

export const acceptOrder = (token: string, id: string) => orderAction(token, id, 'accept')
export const deliverOrder = (token: string, id: string) => orderAction(token, id, 'deliver')
export const completeOrder = (token: string, id: string) => orderAction(token, id, 'complete')

export function proposeMeeting(
  accessToken: string,
  orderId: string,
  proposedFor: string,
  locationText: string,
) {
  return requestJson<MeetingProposal>(`/api/v1/orders/${orderId}/meeting-proposals`, {
    method: 'POST',
    accessToken,
    acceptedStatuses: [201],
    body: {
      client_action_id: actionId('meeting'),
      proposed_for: proposedFor,
      location_text: locationText,
    },
  })
}

export function confirmMeeting(accessToken: string, orderId: string, proposalId: string) {
  return requestJson<MeetingProposal>(
    `/api/v1/orders/${orderId}/meeting-proposals/${proposalId}/confirm`,
    {
      method: 'POST',
      accessToken,
      body: { client_action_id: actionId('confirm') },
    },
  )
}

export function cancelOrder(
  accessToken: string,
  orderId: string,
  reasonCode: string,
  note?: string,
) {
  return requestJson<OrderDetail>(`/api/v1/orders/${orderId}/cancel`, {
    method: 'POST',
    accessToken,
    body: { client_action_id: actionId('cancel'), reason_code: reasonCode, note },
  })
}

export function disputeOrder(
  accessToken: string,
  orderId: string,
  reasonCode: string,
  details: string,
) {
  return requestJson<OrderDetail>(`/api/v1/orders/${orderId}/dispute`, {
    method: 'POST',
    accessToken,
    body: { client_action_id: actionId('dispute'), reason_code: reasonCode, details },
  })
}

export function createReview(
  accessToken: string,
  orderId: string,
  rating: number,
  tags: string[],
  content: string,
) {
  return requestJson<Review>(`/api/v1/orders/${orderId}/reviews`, {
    method: 'POST',
    accessToken,
    acceptedStatuses: [201],
    body: { rating, tags, content: content || null },
  })
}
