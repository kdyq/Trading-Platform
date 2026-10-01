<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  confirmCampusCode,
  downloadCampusAppeal,
  getCampusPolicy,
  getCampusStatus,
  getSchools,
  requestCampusCode,
  submitCampusAppeal,
  type CampusStatus,
  type CampusPolicy,
  type SchoolSummary,
} from '../api/campus'
import { ApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const schools = ref<SchoolSummary[]>([])
const policy = ref<CampusPolicy | null>(null)
const status = ref<CampusStatus | null>(null)
const selectedSchoolId = ref('')
const selectedCampusId = ref('')
const campusEmail = ref('')
const verificationId = ref('')
const code = ref('')
const appealReason = ref('')
const appealFile = ref<File | null>(null)
const busy = ref(false)
const loading = ref(true)
const loadFailed = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const selectedSchool = computed(() =>
  schools.value.find((school) => school.id === selectedSchoolId.value),
)
const campuses = computed(() => selectedSchool.value?.campuses ?? [])
const canUseEmailFlow = computed(
  () => status.value?.status !== 'verified' && status.value?.status !== 'appealing',
)
const appealMaxMegabytes = computed(() =>
  policy.value ? Math.round(policy.value.appeal_max_bytes / 1024 / 1024) : null,
)

function statusLabel(value: string | undefined) {
  const labels: Record<string, string> = {
    unapplied: '未申请',
    pending: '待验证',
    verified: '已通过',
    rejected: '已拒绝',
    expired: '已失效',
    appealing: '申诉中',
  }
  return labels[value ?? ''] ?? '状态未知'
}

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : '操作失败，请稍后重试'
}

function chooseSchool() {
  selectedCampusId.value = campuses.value[0]?.id ?? ''
}

async function load() {
  if (!auth.accessToken) {
    await router.replace('/login')
    return
  }
  loading.value = true
  loadFailed.value = false
  errorMessage.value = ''
  schools.value = []
  status.value = null
  policy.value = null
  try {
    ;[schools.value, status.value, policy.value] = await Promise.all([
      getSchools(),
      getCampusStatus(auth.accessToken),
      getCampusPolicy(),
    ])
    selectedSchoolId.value = schools.value[0]?.id ?? ''
    chooseSchool()
  } catch (error) {
    loadFailed.value = true
    errorMessage.value = errorText(error)
  } finally {
    loading.value = false
  }
}

async function sendCode() {
  if (!auth.accessToken) return
  busy.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const result = await requestCampusCode(auth.accessToken, {
      school_id: selectedSchoolId.value,
      campus_id: selectedCampusId.value,
      campus_email: campusEmail.value,
    })
    verificationId.value = result.verification_id
    successMessage.value = result.message
    status.value = await getCampusStatus(auth.accessToken)
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    busy.value = false
  }
}

async function confirmCode() {
  if (!auth.accessToken) return
  busy.value = true
  errorMessage.value = ''
  try {
    status.value = await confirmCampusCode(auth.accessToken, verificationId.value, code.value)
    if (auth.user) auth.user.campus_verification_status = status.value.status
    successMessage.value = '校园身份认证成功'
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    busy.value = false
  }
}

function chooseFile(event: Event) {
  const input = event.target as HTMLInputElement
  appealFile.value = input.files?.[0] ?? null
}

async function submitAppeal() {
  if (!auth.accessToken || !appealFile.value) return
  busy.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    await submitCampusAppeal(auth.accessToken, {
      campusId: selectedCampusId.value,
      reason: appealReason.value,
      material: appealFile.value,
    })
    status.value = await getCampusStatus(auth.accessToken)
    successMessage.value = '申诉材料已私密提交'
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    busy.value = false
  }
}

async function downloadMaterial() {
  if (!auth.accessToken || !status.value?.appeal) return
  try {
    const blob = await downloadCampusAppeal(auth.accessToken, status.value.appeal.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = status.value.appeal.original_filename
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    errorMessage.value = errorText(error)
  }
}

onMounted(load)
</script>

<template>
  <section class="container campus-page">
    <header class="account-heading">
      <p class="eyebrow">可信校园交易</p>
      <h1>校园身份认证</h1>
      <p>登录邮箱只用于账户登录；这里填写的校园邮箱只用于确认在校身份。</p>
    </header>

    <p v-if="errorMessage" class="form-message error-message" role="alert">
      {{ errorMessage }}
    </p>
    <p v-if="successMessage" class="form-message success-message" role="status">
      {{ successMessage }}
    </p>

    <article v-if="status" class="trust-panel">
      <div class="trust-seal" aria-hidden="true">校</div>
      <div>
        <p class="eyebrow">当前状态</p>
        <h2>{{ statusLabel(status.status) }}</h2>
        <p v-if="status.campus_email">认证邮箱：{{ status.campus_email }}</p>
        <p v-if="status.expires_at">
          有效期至 {{ new Date(status.expires_at).toLocaleDateString() }}
        </p>
        <button v-if="status.appeal" class="text-button" type="button" @click="downloadMaterial">
          下载我提交的材料
        </button>
      </div>
    </article>

    <div v-if="loading" class="empty-state campus-empty" aria-live="polite">
      <h2>正在加载认证信息</h2>
      <p>正在读取学校和认证状态，请稍候。</p>
    </div>

    <div v-else-if="loadFailed" class="empty-state campus-empty">
      <h2>认证信息加载失败</h2>
      <p>请检查网络连接后重试。</p>
      <button class="button button-ghost" type="button" @click="load">重新加载</button>
    </div>

    <div v-else-if="schools.length === 0" class="empty-state campus-empty">
      <h2>尚未配置学校</h2>
      <p>管理员配置学校、校区和校园邮箱域名后即可开始认证。</p>
    </div>

    <div v-else-if="canUseEmailFlow" class="campus-grid">
      <form class="account-panel auth-form" @submit.prevent="sendCode">
        <div>
          <p class="eyebrow">推荐方式</p>
          <h2>校园邮箱验证</h2>
        </div>
        <label class="field">
          <span>学校</span>
          <select v-model="selectedSchoolId" required @change="chooseSchool">
            <option v-for="school in schools" :key="school.id" :value="school.id">
              {{ school.name }}
            </option>
          </select>
        </label>
        <label class="field">
          <span>校区</span>
          <select v-model="selectedCampusId" required>
            <option v-for="campus in campuses" :key="campus.id" :value="campus.id">
              {{ campus.name }}
            </option>
          </select>
        </label>
        <label class="field">
          <span>校园邮箱</span>
          <input v-model.trim="campusEmail" autocomplete="email" required type="email" />
          <small v-if="selectedSchool?.email_domains.length">
            支持域名：{{ selectedSchool.email_domains.join('、') }}
          </small>
        </label>
        <button class="button button-primary" :disabled="busy" type="submit">
          {{ busy ? '正在发送' : '发送校园验证码' }}
        </button>
      </form>

      <form v-if="verificationId" class="account-panel auth-form" @submit.prevent="confirmCode">
        <div>
          <p class="eyebrow">第二步</p>
          <h2>确认验证码</h2>
        </div>
        <label class="field">
          <span>6 位验证码</span>
          <input
            v-model.trim="code"
            autocomplete="one-time-code"
            inputmode="numeric"
            maxlength="6"
            pattern="[0-9]{6}"
            required
          />
        </label>
        <button class="button button-primary" :disabled="busy" type="submit">
          {{ busy ? '正在确认' : '完成认证' }}
        </button>
      </form>

      <form class="account-panel auth-form" @submit.prevent="submitAppeal">
        <div>
          <p class="eyebrow">备用方式</p>
          <h2>人工申诉</h2>
          <p class="muted-copy">校园邮箱暂时不可用时，可提交一份证明材料等待审核。</p>
        </div>
        <label class="field">
          <span>情况说明</span>
          <textarea v-model.trim="appealReason" minlength="20" maxlength="1000" required />
        </label>
        <label class="field">
          <span>私密材料</span>
          <input
            accept="application/pdf,image/png,image/jpeg"
            required
            type="file"
            @change="chooseFile"
          />
          <small v-if="policy">
            仅支持 PDF、PNG 或 JPEG，最大 {{ appealMaxMegabytes }} MB，保存
            {{ policy.appeal_retention_days }} 天。
          </small>
        </label>
        <button class="button button-ghost" :disabled="busy || !appealFile" type="submit">
          {{ busy ? '正在提交' : '私密提交申诉' }}
        </button>
      </form>
    </div>
  </section>
</template>
