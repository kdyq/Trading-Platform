<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  chatWebSocketUrl,
  issueWebSocketTicket,
  listConversations,
  listMessages,
  markConversationRead,
  sendMessage,
} from '../api/chat'
import type { ChatMessage, ConversationSummary } from '../api/chat'
import UiButton from '../components/ui/UiButton.vue'
import { useAuthStore } from '../stores/auth'

type DeliveryState = 'sending' | 'sent' | 'failed'
type DisplayMessage = ChatMessage & { delivery?: DeliveryState }

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const conversations = ref<ConversationSummary[]>([])
const messages = ref<DisplayMessage[]>([])
const selectedId = ref<string | null>(null)
const nextCursor = ref<string | null>(null)
const loading = ref(true)
const loadingMessages = ref(false)
const loadingOlder = ref(false)
const draft = ref('')
const error = ref('')
const connection = ref<'connecting' | 'live' | 'retrying' | 'offline'>('offline')
const composer = ref<HTMLTextAreaElement | null>(null)
let socket: WebSocket | null = null
let heartbeat: number | undefined
let reconnect: number | undefined
let reconnectAttempt = 0
let stopped = false

const selected = computed(
  () => conversations.value.find((item) => item.id === selectedId.value) ?? null,
)
const showThread = computed(() => selectedId.value !== null)
const connectionLabel = computed(() => {
  if (connection.value === 'live') return '实时连接正常'
  if (connection.value === 'connecting') return '正在连接'
  if (connection.value === 'retrying') return '正在重连，消息仍可发送'
  return '实时连接暂不可用，已启用历史补拉'
})

function clientMessageId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2)}`
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function dateLabel(value: string) {
  const date = new Date(value)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) return '今天'
  return date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
}

function beginsDateGroup(index: number) {
  if (index === 0) return true
  return (
    new Date(messages.value[index - 1]!.created_at).toDateString() !==
    new Date(messages.value[index]!.created_at).toDateString()
  )
}

async function refreshConversations() {
  if (!auth.accessToken) return
  const result = await listConversations(auth.accessToken)
  conversations.value = result.items
}

async function readLatest() {
  const latest = messages.value.at(-1)
  if (!auth.accessToken || !selectedId.value || !latest || latest.sender_id === auth.user?.id)
    return
  try {
    await markConversationRead(auth.accessToken, selectedId.value, latest.id)
    const conversation = conversations.value.find((item) => item.id === selectedId.value)
    if (conversation) conversation.unread_count = 0
  } catch {
    // Read receipts are retried when this conversation is opened again.
  }
}

async function openConversation(id: string, replaceRoute = false) {
  if (!auth.accessToken || selectedId.value === id) return
  selectedId.value = id
  messages.value = []
  nextCursor.value = null
  loadingMessages.value = true
  error.value = ''
  await router[replaceRoute ? 'replace' : 'push'](`/messages/${id}`)
  try {
    const page = await listMessages(auth.accessToken, id)
    if (selectedId.value !== id) return
    messages.value = page.items.map((message) => ({ ...message, delivery: 'sent' }))
    nextCursor.value = page.next_cursor
    await readLatest()
    await nextTick()
    composer.value?.focus()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '消息暂时无法加载'
  } finally {
    if (selectedId.value === id) loadingMessages.value = false
  }
}

async function loadOlder() {
  if (!auth.accessToken || !selectedId.value || !nextCursor.value || loadingOlder.value) return
  loadingOlder.value = true
  try {
    const page = await listMessages(auth.accessToken, selectedId.value, nextCursor.value)
    messages.value = [
      ...page.items.map((message) => ({ ...message, delivery: 'sent' as const })),
      ...messages.value,
    ]
    nextCursor.value = page.next_cursor
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '更早消息加载失败'
  } finally {
    loadingOlder.value = false
  }
}

async function deliver(message: DisplayMessage) {
  if (!auth.accessToken || !selectedId.value) return
  message.delivery = 'sending'
  try {
    const saved = await sendMessage(
      auth.accessToken,
      selectedId.value,
      message.client_message_id,
      message.body,
    )
    Object.assign(message, saved, { delivery: 'sent' })
    await refreshConversations()
  } catch (caught) {
    message.delivery = 'failed'
    error.value = caught instanceof Error ? caught.message : '消息发送失败，请重试'
  }
}

async function submit() {
  const body = draft.value.trim()
  if (!body || !selectedId.value || !auth.user) return
  const optimistic: DisplayMessage = {
    id: clientMessageId(),
    conversation_id: selectedId.value,
    sender_id: auth.user.id,
    client_message_id: clientMessageId(),
    body,
    created_at: new Date().toISOString(),
    delivery: 'sending',
  }
  messages.value.push(optimistic)
  draft.value = ''
  await deliver(optimistic)
}

function closeSocket() {
  if (heartbeat) window.clearInterval(heartbeat)
  if (reconnect) window.clearTimeout(reconnect)
  heartbeat = undefined
  reconnect = undefined
  socket?.close()
  socket = null
}

function scheduleReconnect() {
  if (stopped || reconnect) return
  connection.value = 'retrying'
  const delay = Math.min(1000 * 2 ** reconnectAttempt, 15_000)
  reconnectAttempt += 1
  reconnect = window.setTimeout(() => {
    reconnect = undefined
    void connectRealtime()
  }, delay)
}

async function catchUp() {
  await refreshConversations()
  const active = selectedId.value
  if (!active || !auth.accessToken) return
  const page = await listMessages(auth.accessToken, active)
  messages.value = page.items.map((message) => ({ ...message, delivery: 'sent' }))
  nextCursor.value = page.next_cursor
  await readLatest()
}

async function connectRealtime() {
  if (!auth.accessToken || stopped) return
  connection.value = reconnectAttempt ? 'retrying' : 'connecting'
  try {
    const { ticket } = await issueWebSocketTicket(auth.accessToken)
    if (stopped) return
    socket = new WebSocket(chatWebSocketUrl(ticket))
    socket.onopen = () => {
      reconnectAttempt = 0
      connection.value = 'live'
      heartbeat = window.setInterval(() => socket?.send(JSON.stringify({ type: 'ping' })), 20_000)
      void catchUp()
    }
    socket.onmessage = (event) => {
      let packet: { type?: string; data?: ChatMessage }
      try {
        packet = JSON.parse(String(event.data)) as typeof packet
      } catch {
        return
      }
      if (packet.type !== 'chat.message.created' || !packet.data) return
      const message = packet.data
      if (message.conversation_id === selectedId.value) {
        const current = messages.value.find(
          (item) =>
            item.id === message.id ||
            (item.sender_id === message.sender_id &&
              item.client_message_id === message.client_message_id),
        )
        if (current) Object.assign(current, message, { delivery: 'sent' })
        else messages.value.push({ ...message, delivery: 'sent' })
        void readLatest()
      }
      void refreshConversations()
    }
    socket.onclose = () => {
      if (heartbeat) window.clearInterval(heartbeat)
      heartbeat = undefined
      scheduleReconnect()
    }
    socket.onerror = () => socket?.close()
  } catch {
    connection.value = 'offline'
    scheduleReconnect()
  }
}

async function initialize() {
  if (!auth.accessToken) {
    loading.value = false
    return
  }
  try {
    await refreshConversations()
    const routeId = typeof route.params.id === 'string' ? route.params.id : null
    if (routeId && conversations.value.some((item) => item.id === routeId)) {
      await openConversation(routeId, true)
    }
    void connectRealtime()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '会话列表暂时无法加载'
  } finally {
    loading.value = false
  }
}

watch(
  () => route.params.id,
  (value) => {
    if (typeof value === 'string' && value !== selectedId.value) void openConversation(value, true)
    else if (value === undefined) selectedId.value = null
  },
)

onMounted(initialize)
onUnmounted(() => {
  stopped = true
  closeSocket()
})
</script>

<template>
  <section class="container chat-page" aria-labelledby="chat-title">
    <header class="chat-heading">
      <div>
        <p class="eyebrow">校内沟通</p>
        <h1 id="chat-title">消息</h1>
      </div>
      <span class="connection-state" :class="connection" role="status">
        <i aria-hidden="true" />{{ connectionLabel }}
      </span>
    </header>

    <div v-if="!auth.user" class="chat-auth-card">
      <h2>登录后查看消息</h2>
      <p>聊天只对会话双方开放，登录状态不会通过链接暴露。</p>
      <RouterLink class="button button-primary" to="/login?redirect=/messages">去登录</RouterLink>
    </div>

    <div v-else class="chat-shell" :class="{ 'has-thread': showThread }">
      <aside class="conversation-pane" aria-label="会话列表">
        <p v-if="loading" class="chat-state">正在整理会话…</p>
        <p v-else-if="!conversations.length" class="chat-state">
          暂无会话。去商品详情页联系卖家吧。
        </p>
        <button
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-row"
          :class="{ active: conversation.id === selectedId }"
          type="button"
          @click="openConversation(conversation.id)"
        >
          <span class="conversation-avatar" aria-hidden="true">
            {{ conversation.other_display_name.slice(0, 1) }}
          </span>
          <span class="conversation-copy">
            <span class="conversation-title-line">
              <strong>{{ conversation.other_display_name }}</strong>
              <time v-if="conversation.last_message_at" :datetime="conversation.last_message_at">
                {{ formatTime(conversation.last_message_at) }}
              </time>
            </span>
            <span class="conversation-product">{{ conversation.product_title }}</span>
            <span class="conversation-preview">
              {{ conversation.last_message_preview || '还没有消息，先打个招呼吧' }}
            </span>
          </span>
          <span v-if="conversation.unread_count" class="unread-badge" aria-label="未读消息">
            {{ conversation.unread_count > 99 ? '99+' : conversation.unread_count }}
          </span>
        </button>
      </aside>

      <article v-if="selected" class="thread-pane" aria-label="当前会话">
        <header class="thread-header">
          <button
            class="mobile-back"
            type="button"
            aria-label="返回会话列表"
            @click="router.push('/messages')"
          >
            ←
          </button>
          <div>
            <strong>{{ selected.other_display_name }}</strong>
            <RouterLink :to="`/products/${selected.product_id}`">
              {{ selected.product_title }} · ¥{{ selected.product_price }}
            </RouterLink>
          </div>
          <button class="order-entry" type="button" disabled title="交易功能将在下一阶段开放">
            发起交易
          </button>
        </header>

        <div class="message-history" aria-live="polite" :aria-busy="loadingMessages">
          <button v-if="nextCursor" class="load-older" type="button" @click="loadOlder">
            {{ loadingOlder ? '加载中…' : '查看更早消息' }}
          </button>
          <p v-if="loadingMessages" class="chat-state">正在加载消息…</p>
          <template v-for="(message, index) in messages" :key="message.client_message_id">
            <p v-if="beginsDateGroup(index)" class="date-divider">
              <span>{{ dateLabel(message.created_at) }}</span>
            </p>
            <div class="message-row" :class="{ mine: message.sender_id === auth.user.id }">
              <div class="message-bubble">
                <p>{{ message.body }}</p>
                <span>
                  {{ formatTime(message.created_at) }}
                  <template v-if="message.sender_id === auth.user.id">
                    ·
                    {{
                      message.delivery === 'sending'
                        ? '发送中'
                        : message.delivery === 'failed'
                          ? '发送失败'
                          : '已发送'
                    }}
                  </template>
                </span>
                <button
                  v-if="message.delivery === 'failed'"
                  type="button"
                  @click="deliver(message)"
                >
                  重试
                </button>
              </div>
            </div>
          </template>
          <p v-if="!loadingMessages && !messages.length" class="chat-state">
            从礼貌问候开始，确认物品状态和当面交易地点。
          </p>
        </div>

        <form class="composer" @submit.prevent="submit">
          <label class="sr-only" for="chat-message">输入消息</label>
          <textarea
            id="chat-message"
            ref="composer"
            v-model="draft"
            maxlength="2000"
            rows="2"
            placeholder="输入消息，建议只在校内公共区域当面交易"
            @keydown.ctrl.enter="submit"
            @keydown.meta.enter="submit"
          />
          <UiButton type="submit" :disabled="!draft.trim()">发送</UiButton>
          <p>请勿发送身份证、验证码或支付密码；平台客服不会在聊天中索要敏感信息。</p>
        </form>
      </article>

      <div v-else class="thread-empty">
        <span aria-hidden="true">✦</span>
        <h2>选择一段会话</h2>
        <p>消息会在持久化后送达；重连时会自动补拉历史，不会只依赖在线状态。</p>
      </div>
    </div>

    <p v-if="error" class="chat-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.chat-page {
  padding-block: 38px 56px;
}
.chat-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
}
.chat-heading h1 {
  margin: 2px 0 0;
  font-size: clamp(2rem, 5vw, 3.4rem);
}
.connection-state {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-2);
  font-size: 0.84rem;
}
.connection-state i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #9b8b7b;
}
.connection-state.live i {
  background: var(--leaf);
  box-shadow: 0 0 0 4px var(--leaf-soft);
}
.connection-state.retrying i,
.connection-state.connecting i {
  background: var(--sun);
}
.chat-shell {
  display: grid;
  grid-template-columns: minmax(260px, 330px) minmax(0, 1fr);
  min-height: 650px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--card);
  box-shadow: var(--shadow);
}
.conversation-pane {
  overflow-y: auto;
  border-right: 1px solid var(--line);
  background: #fffaf3;
}
.conversation-row {
  position: relative;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 12px;
  width: 100%;
  min-height: 92px;
  padding: 16px;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.conversation-row:hover,
.conversation-row.active {
  background: white;
}
.conversation-row.active::before {
  position: absolute;
  inset: 14px auto 14px 0;
  width: 4px;
  border-radius: 0 4px 4px 0;
  background: var(--primary);
  content: '';
}
.conversation-avatar {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: var(--peach);
  color: var(--primary-deep);
  font-weight: 800;
}
.conversation-copy,
.conversation-title-line {
  display: flex;
  min-width: 0;
}
.conversation-copy {
  flex-direction: column;
  gap: 3px;
}
.conversation-title-line {
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.conversation-title-line time {
  color: var(--ink-2);
  font-size: 0.73rem;
}
.conversation-product,
.conversation-preview {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conversation-product {
  color: var(--primary-deep);
  font-size: 0.78rem;
  font-weight: 700;
}
.conversation-preview {
  color: var(--ink-2);
  font-size: 0.83rem;
}
.unread-badge {
  position: absolute;
  right: 14px;
  bottom: 13px;
  min-width: 20px;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--primary);
  color: white;
  font: 700 0.7rem var(--font-number);
  text-align: center;
}
.thread-pane {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-width: 0;
  background: linear-gradient(180deg, #fff 0, #fff9f0 100%);
}
.thread-header {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 76px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--line);
  background: rgb(255 255 255 / 88%);
}
.thread-header > div {
  display: grid;
  flex: 1;
  gap: 3px;
}
.thread-header a {
  color: var(--primary-deep);
  font-size: 0.82rem;
}
.order-entry {
  min-height: 40px;
  padding: 0 14px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--bg);
  color: var(--ink-2);
}
.mobile-back {
  display: none;
  width: 42px;
  height: 42px;
  border: 0;
  border-radius: 12px;
  background: var(--bg);
  font-size: 1.25rem;
}
.message-history {
  overflow-y: auto;
  padding: 22px clamp(16px, 4vw, 42px);
}
.date-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 18px 0;
  color: var(--ink-2);
  font-size: 0.75rem;
}
.date-divider::before,
.date-divider::after {
  flex: 1;
  height: 1px;
  background: var(--line);
  content: '';
}
.message-row {
  display: flex;
  margin: 9px 0;
}
.message-row.mine {
  justify-content: flex-end;
}
.message-bubble {
  max-width: min(76%, 560px);
  padding: 10px 13px 8px;
  border: 1px solid var(--line);
  border-radius: 6px 17px 17px;
  background: white;
  box-shadow: 0 5px 14px rgb(90 60 30 / 6%);
}
.mine .message-bubble {
  border-color: #ffd1b9;
  border-radius: 17px 6px 17px 17px;
  background: var(--peach);
}
.message-bubble p {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.message-bubble span {
  display: block;
  margin-top: 5px;
  color: var(--ink-2);
  font-size: 0.7rem;
  text-align: right;
}
.message-bubble button {
  margin-top: 5px;
  border: 0;
  background: transparent;
  color: var(--danger);
  font-weight: 700;
}
.load-older {
  display: block;
  margin: 0 auto 14px;
  border: 0;
  background: transparent;
  color: var(--primary-deep);
}
.composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  padding: 15px 18px;
  border-top: 1px solid var(--line);
  background: white;
}
.composer textarea {
  min-height: 58px;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 11px 13px;
  color: var(--ink);
  font: inherit;
}
.composer textarea:focus {
  outline: 3px solid rgb(31 102 72 / 18%);
  border-color: var(--focus);
}
.composer p {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--ink-2);
  font-size: 0.72rem;
}
.thread-empty,
.chat-auth-card {
  display: grid;
  place-content: center;
  justify-items: center;
  padding: 44px;
  text-align: center;
}
.thread-empty span {
  color: var(--primary);
  font-size: 2rem;
}
.thread-empty p,
.chat-auth-card p {
  max-width: 520px;
  color: var(--ink-2);
}
.chat-auth-card {
  min-height: 420px;
  border: 1px solid var(--line);
  border-radius: 24px;
  background: white;
}
.chat-state {
  padding: 24px;
  color: var(--ink-2);
  text-align: center;
}
.chat-error {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: var(--layer-toast);
  max-width: 420px;
  padding: 12px 16px;
  border-radius: 12px;
  background: var(--danger);
  color: white;
  box-shadow: var(--shadow);
}
.sr-only {
  position: absolute;
  overflow: hidden;
  width: 1px;
  height: 1px;
  clip: rect(0, 0, 0, 0);
}
@media (max-width: 720px) {
  .chat-page {
    padding: 20px 0 0;
  }
  .chat-heading {
    align-items: flex-start;
    padding-inline: 16px;
  }
  .connection-state {
    max-width: 150px;
    text-align: right;
  }
  .chat-shell {
    grid-template-columns: 1fr;
    min-height: calc(100dvh - 150px);
    border-inline: 0;
    border-radius: 0;
  }
  .chat-shell.has-thread .conversation-pane {
    display: none;
  }
  .thread-empty {
    display: none;
  }
  .thread-pane {
    min-height: calc(100dvh - 150px);
  }
  .mobile-back {
    display: block;
  }
  .message-bubble {
    max-width: 86%;
  }
  .order-entry {
    display: none;
  }
}
</style>
