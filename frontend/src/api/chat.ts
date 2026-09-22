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
  is_buyer: boolean
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

export interface NotificationItem {
  id: string
  category: 'chat' | 'order' | 'moderation' | 'report'
  title: string
  summary: string
  target_type: string
  target_id: string | null
  read_at: string | null
  created_at: string
}

export interface NotificationPreferences {
  chat: boolean
  order: boolean
  moderation: boolean
  report: boolean
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

export async function listNotifications(accessToken: string) {
  return requestJson<{ items: NotificationItem[]; unread_count: number }>(
    '/api/v1/chat/notifications',
    { accessToken },
  )
}

export async function readNotification(accessToken: string, notificationId: string) {
  return requestJson<NotificationItem>(`/api/v1/chat/notifications/${notificationId}/read`, {
    method: 'PUT',
    accessToken,
  })
}

export async function readAllNotifications(accessToken: string) {
  return requestJson<{ updated_count: number }>('/api/v1/chat/notifications/read-all', {
    method: 'PUT',
    accessToken,
  })
}

export async function getNotificationPreferences(accessToken: string) {
  return requestJson<NotificationPreferences>('/api/v1/chat/notification-preferences', {
    accessToken,
  })
}

export async function setNotificationPreference(
  accessToken: string,
  category: keyof NotificationPreferences,
  enabled: boolean,
) {
  return requestJson<NotificationPreferences>('/api/v1/chat/notification-preferences', {
    method: 'PUT',
    accessToken,
    body: { category, enabled },
  })
}

export async function blockChatUser(accessToken: string, userId: string) {
  return requestJson<void>(`/api/v1/chat/blocks/${userId}`, {
    method: 'PUT',
    accessToken,
    acceptedStatuses: [204],
  })
}

export async function reportChatMessage(
  accessToken: string,
  conversationId: string,
  messageId: string,
  reasonCode: 'harassment' | 'fraud' | 'spam' | 'unsafe' | 'other',
  details: string,
) {
  return requestJson<{ id: string; status: string }>(
    `/api/v1/chat/conversations/${conversationId}/reports`,
    {
      method: 'POST',
      accessToken,
      acceptedStatuses: [201],
      body: { message_id: messageId, reason_code: reasonCode, details: details || null },
    },
  )
}
