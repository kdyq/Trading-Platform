import { API_BASE_URL, requestJson } from './client'

export interface ConversationSummary {
  id: string
  product_id: string
  product_title: string
  product_price: string
  product_status: 'on_sale' | 'reserved' | 'sold'
  other_user_id: string
  other_display_name: string
  last_message_at: string | null
  last_message_preview: string | null
  unread_count: number
}

export interface ChatMessage {
  id: string
  conversation_id: string
  sender_id: string
  client_message_id: string
  body: string
  created_at: string
}

export interface MessagePage {
  items: ChatMessage[]
  next_cursor: string | null
}

interface WebSocketTicket {
  ticket: string
  expires_in: number
}

export async function createConversation(accessToken: string, productId: string) {
  return requestJson<ConversationSummary>('/api/v1/chat/conversations', {
    method: 'POST',
    accessToken,
    acceptedStatuses: [201],
    body: { product_id: productId },
  })
}

export async function listConversations(accessToken: string) {
  return requestJson<{ items: ConversationSummary[] }>('/api/v1/chat/conversations', {
    accessToken,
  })
}

export async function listMessages(
  accessToken: string,
  conversationId: string,
  cursor?: string | null,
) {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return requestJson<MessagePage>(`/api/v1/chat/conversations/${conversationId}/messages${query}`, {
    accessToken,
  })
}

export async function sendMessage(
  accessToken: string,
  conversationId: string,
  clientMessageId: string,
  body: string,
) {
  return requestJson<ChatMessage>(`/api/v1/chat/conversations/${conversationId}/messages`, {
    method: 'POST',
    accessToken,
    acceptedStatuses: [201],
    body: { client_message_id: clientMessageId, body },
  })
}

export async function markConversationRead(
  accessToken: string,
  conversationId: string,
  messageId: string,
) {
  return requestJson(`/api/v1/chat/conversations/${conversationId}/read-position`, {
    method: 'PUT',
    accessToken,
    body: { message_id: messageId },
  })
}

export async function issueWebSocketTicket(accessToken: string) {
  return requestJson<WebSocketTicket>('/api/v1/chat/ws-tickets', {
    method: 'POST',
    accessToken,
    acceptedStatuses: [201],
  })
}

export function chatWebSocketUrl(ticket: string) {
  const base = API_BASE_URL || window.location.origin
  const url = new URL('/api/v1/chat/ws', base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('ticket', ticket)
  return url.toString()
}
