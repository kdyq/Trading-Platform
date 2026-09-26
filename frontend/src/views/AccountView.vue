<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import {
  changePassword,
  getProfile,
  getSessions,
  revokeSession,
  updateProfile,
  type AccountSession,
  type Profile,
} from '../api/account'
import { ApiError } from '../api/client'
import {
  getMyCredit,
  getMyCreditLedgers,
  type CreditLedger,
  type CreditSummary,
} from '../api/credit'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const profile = ref<Profile | null>(null)
const credit = ref<CreditSummary | null>(null)
const ledgers = ref<CreditLedger[]>([])
const creditCursor = ref<string | null>(null)
const sessions = ref<AccountSession[]>([])
const displayName = ref('')
const currentPassword = ref('')
const newPassword = ref('')
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : '操作失败，请稍后重试'
}

function sessionDescription(session: AccountSession) {
  const network = session.ip_address || '未知网络'
  return `${network} · 有效至 ${new Date(session.expires_at).toLocaleString()}`
}

function campusStatusLabel(status: string) {
  const labels: Record<string, string> = {
    unapplied: '未申请',
    pending: '待验证',
    verified: '已通过',
    rejected: '已拒绝',
    expired: '已失效',
    appealing: '申诉中',
  }
  return labels[status] ?? '状态未知'
}

async function load() {
  if (!auth.accessToken) {
    await router.replace('/login')
    return
  }
  try {
    ;[profile.value, sessions.value] = await Promise.all([
      getProfile(auth.accessToken),
      getSessions(auth.accessToken),
    ])
    const [creditResult, ledgerResult] = await Promise.all([
      getMyCredit(auth.accessToken),
      getMyCreditLedgers(auth.accessToken),
    ])
    credit.value = creditResult
    ledgers.value = ledgerResult.items
    creditCursor.value = ledgerResult.next_cursor
    displayName.value = profile.value.display_name
  } catch (error) {
    errorMessage.value = errorText(error)
  }
}

async function loadMoreCredit() {
  if (!auth.accessToken || !creditCursor.value) return
  try {
    const page = await getMyCreditLedgers(auth.accessToken, creditCursor.value)
    ledgers.value.push(...page.items)
    creditCursor.value = page.next_cursor
  } catch (error) {
    errorMessage.value = errorText(error)
  }
}

async function saveProfile() {
  if (!auth.accessToken) return
  busy.value = true
  message.value = ''
  errorMessage.value = ''
  try {
    profile.value = await updateProfile(auth.accessToken, displayName.value)
    if (auth.user) auth.user.display_name = profile.value.display_name
    message.value = '个人资料已保存'
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    busy.value = false
  }
}

async function savePassword() {
  if (!auth.accessToken) return
  busy.value = true
  message.value = ''
  errorMessage.value = ''
  try {
    const result = await changePassword(auth.accessToken, currentPassword.value, newPassword.value)
    currentPassword.value = ''
    newPassword.value = ''
    message.value = result.message
    sessions.value = await getSessions(auth.accessToken)
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    busy.value = false
  }
}

async function removeSession(session: AccountSession) {
  if (!auth.accessToken || session.is_current) return
  errorMessage.value = ''
  try {
    await revokeSession(auth.accessToken, session.id)
    sessions.value = sessions.value.filter((item) => item.id !== session.id)
  } catch (error) {
    errorMessage.value = errorText(error)
  }
}

onMounted(load)
</script>

<template>
  <section class="container account-page">
    <header class="account-heading">
      <p class="eyebrow">个人中心</p>
      <h1>账户与安全</h1>
      <p>这里展示真实账户状态和统计数据。校园身份将在认证完成后更新。</p>
    </header>

    <p v-if="errorMessage" class="form-message error-message" role="alert">
      {{ errorMessage }}
    </p>
    <p v-if="message" class="form-message success-message" role="status">{{ message }}</p>

    <template v-if="profile">
      <div class="account-grid">
        <article class="account-panel identity-panel">
          <div class="account-avatar" aria-hidden="true">
            {{ profile.display_name.slice(0, 1) }}
          </div>
          <div>
            <h2>{{ profile.display_name }}</h2>
            <p>{{ profile.login_email }}</p>
            <span class="status-chip">
              校园认证：{{ campusStatusLabel(profile.campus_verification_status) }}
            </span>
            <span v-if="credit" class="status-chip"
              >信用 {{ credit.balance }} 分 · {{ credit.level }}</span
            >
            <RouterLink class="identity-action" to="/campus-verification">管理校园认证</RouterLink>
          </div>
        </article>
        <article class="account-panel stats-panel" aria-label="账户统计">
          <div>
            <strong class="num">{{ profile.active_products }}</strong>
            <span>在售商品</span>
          </div>
          <div>
            <strong class="num">{{ profile.favorites }}</strong>
            <span>收藏</span>
          </div>
          <div>
            <strong class="num">{{ profile.orders }}</strong>
            <span>订单</span>
          </div>
        </article>
      </div>

      <article v-if="credit" class="account-panel sessions-panel">
        <div>
          <p class="eyebrow">可解释信用</p>
          <h2>我的信用流水</h2>
          <p>当前 {{ credit.balance }} 分 · 规则 {{ credit.rule_version }}</p>
        </div>
        <p v-if="!ledgers.length" class="muted-copy">尚无信用变动，初始分为 100 分。</p>
        <ul v-else class="session-list">
          <li v-for="item in ledgers" :key="item.id">
            <div>
              <strong>{{ item.reason }}</strong>
              <span>{{ new Date(item.created_at).toLocaleString('zh-CN') }}</span>
            </div>
            <span class="status-chip"
              >{{ item.delta > 0 ? '+' : '' }}{{ item.delta }} · 余额 {{ item.balance_after }}</span
            >
          </li>
        </ul>
        <button
          v-if="creditCursor"
          class="button button-ghost"
          type="button"
          @click="loadMoreCredit"
        >
          加载更多
        </button>
      </article>

      <nav class="account-shortcuts" aria-label="我的交易入口">
        <RouterLink to="/my-products">
          <strong>我的发布</strong>
          <span>{{ profile.active_products }} 件在售</span>
        </RouterLink>
        <RouterLink to="/favorites">
          <strong>我的收藏</strong>
          <span>{{ profile.favorites }} 件收藏</span>
        </RouterLink>
        <RouterLink to="/orders">
          <strong>我的订单</strong>
          <span>{{ profile.orders }} 笔订单</span>
        </RouterLink>
      </nav>

      <div class="account-grid">
        <form class="account-panel auth-form" @submit.prevent="saveProfile">
          <div>
            <p class="eyebrow">公开资料</p>
            <h2>修改昵称</h2>
          </div>
          <label class="field">
            <span>公开昵称</span>
            <input v-model.trim="displayName" minlength="2" maxlength="30" required />
          </label>
          <button class="button button-primary" :disabled="busy" type="submit">保存资料</button>
        </form>

        <form class="account-panel auth-form" @submit.prevent="savePassword">
          <div>
            <p class="eyebrow">近期登录保护</p>
            <h2>修改密码</h2>
          </div>
          <label class="field">
            <span>当前密码</span>
            <input
              v-model="currentPassword"
              autocomplete="current-password"
              required
              type="password"
            />
          </label>
          <label class="field">
            <span>新密码</span>
            <input
              v-model="newPassword"
              autocomplete="new-password"
              minlength="8"
              maxlength="128"
              required
              type="password"
            />
            <small>至少 8 位，包含英文字母和数字，不能有空格。</small>
          </label>
          <button class="button button-primary" :disabled="busy" type="submit">更新密码</button>
        </form>
      </div>

      <article class="account-panel sessions-panel">
        <div>
          <p class="eyebrow">登录设备</p>
          <h2>有效会话</h2>
        </div>
        <p v-if="sessions.length === 0" class="muted-copy">当前没有可显示的会话。</p>
        <ul v-else class="session-list">
          <li v-for="session in sessions" :key="session.id">
            <div>
              <strong>{{ session.user_agent || '未知设备' }}</strong>
              <span>{{ sessionDescription(session) }}</span>
            </div>
            <span v-if="session.is_current" class="status-chip">当前设备</span>
            <button
              v-else
              class="button button-ghost"
              type="button"
              @click="removeSession(session)"
            >
              退出此设备
            </button>
          </li>
        </ul>
      </article>
    </template>
  </section>
</template>
