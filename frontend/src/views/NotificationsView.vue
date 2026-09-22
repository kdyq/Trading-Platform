<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import {
  getNotificationPreferences,
  listNotifications,
  readAllNotifications,
  readNotification,
  setNotificationPreference,
} from '../api/chat'
import type { NotificationItem, NotificationPreferences } from '../api/chat'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const notifications = ref<NotificationItem[]>([])
const preferences = ref<NotificationPreferences>({
  chat: true,
  order: true,
  moderation: true,
  report: true,
})
const error = ref('')
const loading = ref(true)
const labels: Record<keyof NotificationPreferences, string> = {
  chat: '私信提醒',
  order: '订单进度',
  moderation: '审核结果',
  report: '举报结果',
}

async function load() {
  if (!auth.accessToken) return
  try {
    const [feed, settings] = await Promise.all([
      listNotifications(auth.accessToken),
      getNotificationPreferences(auth.accessToken),
    ])
    notifications.value = feed.items
    preferences.value = settings
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '通知暂时无法加载'
  } finally {
    loading.value = false
  }
}

async function markRead(item: NotificationItem) {
  if (!auth.accessToken || item.read_at) return
  const updated = await readNotification(auth.accessToken, item.id)
  Object.assign(item, updated)
}

async function markAllRead() {
  if (!auth.accessToken || !notifications.value.some((item) => !item.read_at)) return
  try {
    await readAllNotifications(auth.accessToken)
    const readAt = new Date().toISOString()
    notifications.value.forEach((item) => {
      if (!item.read_at) item.read_at = readAt
    })
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '全部标为已读失败'
  }
}

async function toggle(category: keyof NotificationPreferences) {
  if (!auth.accessToken) return
  const previous = preferences.value[category]
  preferences.value[category] = !previous
  try {
    preferences.value = await setNotificationPreference(auth.accessToken, category, !previous)
  } catch (caught) {
    preferences.value[category] = previous
    error.value = caught instanceof Error ? caught.message : '偏好保存失败'
  }
}

onMounted(load)
</script>

<template>
  <section class="container notification-page">
    <header>
      <p class="eyebrow">站内动态</p>
      <h1>通知</h1>
      <p>通知摘要不会包含私聊正文、审核材料或其他敏感内容。</p>
    </header>
    <div class="notification-layout">
      <aside class="preference-card">
        <h2>提醒偏好</h2>
        <label v-for="(label, category) in labels" :key="category">
          <span>{{ label }}</span>
          <input type="checkbox" :checked="preferences[category]" @change="toggle(category)" />
        </label>
      </aside>
      <div class="notification-feed" :aria-busy="loading">
        <button
          v-if="notifications.some((item) => !item.read_at)"
          class="read-all"
          type="button"
          @click="markAllRead"
        >
          全部标为已读
        </button>
        <p v-if="loading">正在加载通知…</p>
        <p v-else-if="!notifications.length">暂无通知。</p>
        <article
          v-for="item in notifications"
          :key="item.id"
          :class="{ unread: !item.read_at }"
          @click="markRead(item)"
        >
          <span class="notification-dot" aria-hidden="true" />
          <div>
            <strong>{{ item.title }}</strong>
            <p>{{ item.summary }}</p>
            <time :datetime="item.created_at">
              {{ new Date(item.created_at).toLocaleString('zh-CN') }}
            </time>
          </div>
          <RouterLink
            v-if="item.target_type === 'conversation' && item.target_id"
            :to="`/messages/${item.target_id}`"
          >
            查看会话
          </RouterLink>
          <RouterLink v-else-if="item.target_type === 'report'" to="/reports">
            查看举报
          </RouterLink>
          <RouterLink
            v-else-if="item.target_type === 'report_appeal' && item.target_id"
            :to="`/appeals/${item.target_id}`"
          >
            提交申诉
          </RouterLink>
        </article>
      </div>
    </div>
    <p v-if="error" class="notification-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.notification-page {
  padding-block: 42px 64px;
}
.notification-page header h1 {
  margin: 4px 0;
  font-size: clamp(2rem, 5vw, 3.5rem);
}
.notification-page header > p:last-child {
  color: var(--ink-2);
}
.notification-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 20px;
  margin-top: 28px;
}
.preference-card,
.notification-feed {
  border: 1px solid var(--line);
  border-radius: 20px;
  background: white;
  box-shadow: var(--shadow);
}
.read-all {
  justify-self: end;
  border: 0;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
}
.preference-card {
  align-self: start;
  padding: 20px;
}
.preference-card h2 {
  margin-top: 0;
}
.preference-card label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 46px;
  border-top: 1px solid var(--line);
}
.preference-card input {
  width: 20px;
  height: 20px;
  accent-color: var(--primary);
}
.notification-feed {
  overflow: hidden;
}
.notification-feed > p {
  padding: 28px;
  color: var(--ink-2);
  text-align: center;
}
.notification-feed article {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  gap: 13px;
  align-items: start;
  padding: 19px 20px;
  border-bottom: 1px solid var(--line);
}
.notification-feed article:last-child {
  border-bottom: 0;
}
.notification-feed article.unread {
  background: #fffaf1;
}
.notification-dot {
  width: 8px;
  height: 8px;
  margin-top: 7px;
  border-radius: 50%;
  background: transparent;
}
.unread .notification-dot {
  background: var(--primary);
}
.notification-feed p {
  margin: 4px 0;
  color: var(--ink-2);
}
.notification-feed time {
  color: var(--ink-2);
  font-size: 0.75rem;
}
.notification-feed a {
  color: var(--primary-deep);
  font-weight: 700;
}
.notification-error {
  color: var(--danger);
}
@media (max-width: 720px) {
  .notification-layout {
    grid-template-columns: 1fr;
  }
  .notification-feed article {
    grid-template-columns: 10px minmax(0, 1fr);
  }
  .notification-feed a {
    grid-column: 2;
  }
}
</style>
