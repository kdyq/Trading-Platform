<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { requestRegistrationCode } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'

const email = ref('')
const code = ref('')
const displayName = ref('')
const password = ref('')
const acceptUserAgreement = ref(false)
const acceptPrivacyPolicy = ref(false)
const busy = ref(false)
const sendingCode = ref(false)
const errorMessage = ref('')
const statusMessage = ref('')
const auth = useAuthStore()
const router = useRouter()

async function sendCode() {
  if (!email.value) {
    errorMessage.value = '请先填写登录邮箱'
    return
  }
  sendingCode.value = true
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    const result = await requestRegistrationCode(email.value)
    statusMessage.value = result.message
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '验证码发送失败'
  } finally {
    sendingCode.value = false
  }
}

async function submit() {
  busy.value = true
  errorMessage.value = ''
  try {
    await auth.register({
      email: email.value,
      code: code.value,
      display_name: displayName.value,
      password: password.value,
      accept_user_agreement: acceptUserAgreement.value,
      accept_privacy_policy: acceptPrivacyPolicy.value,
    })
    await router.push('/')
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '注册失败，请稍后重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="container narrow-page">
    <div class="form-card form-card-wide">
      <p class="eyebrow">普通账户</p>
      <h1>注册拾光集市</h1>
      <p>登录邮箱只用于账户登录。学校、校区和校园邮箱将在认证页面单独填写。</p>
      <form class="auth-form" @submit.prevent="submit">
        <label class="field">
          <span>登录邮箱</span>
          <span class="inline-control">
            <input v-model.trim="email" autocomplete="email" name="email" required type="email" />
            <button
              class="button button-ghost"
              :disabled="sendingCode"
              type="button"
              @click="sendCode"
            >
              {{ sendingCode ? '发送中' : '发送验证码' }}
            </button>
          </span>
        </label>
        <label class="field">
          <span>邮箱验证码</span>
          <input
            v-model.trim="code"
            autocomplete="one-time-code"
            inputmode="numeric"
            maxlength="6"
            name="code"
            pattern="[0-9]{6}"
            required
          />
        </label>
        <label class="field">
          <span>公开昵称</span>
          <input
            v-model.trim="displayName"
            maxlength="30"
            minlength="2"
            name="display-name"
            required
          />
          <small>2-30 个字符，可与其他用户重复。</small>
        </label>
        <label class="field">
          <span>密码</span>
          <input
            v-model="password"
            autocomplete="new-password"
            maxlength="128"
            minlength="8"
            name="password"
            pattern="(?=.*[A-Za-z])(?=.*[0-9])\S{8,128}"
            required
            type="password"
          />
          <small>至少 8 位，同时包含英文字母和数字，不能有空格。</small>
        </label>
        <label class="consent-row">
          <input v-model="acceptUserAgreement" required type="checkbox" />
          <span>我已阅读并同意当前版本的《用户协议》</span>
        </label>
        <label class="consent-row">
          <input v-model="acceptPrivacyPolicy" required type="checkbox" />
          <span>我已阅读并同意当前版本的《隐私政策》</span>
        </label>
        <p v-if="statusMessage" class="form-message success-message" aria-live="polite">
          {{ statusMessage }}
        </p>
        <p v-if="errorMessage" class="form-message error-message" role="alert">
          {{ errorMessage }}
        </p>
        <button class="button button-primary form-submit" :disabled="busy" type="submit">
          {{ busy ? '正在创建账户' : '创建账户' }}
        </button>
      </form>
      <p class="form-switch">已有账户？<RouterLink to="/login">返回登录</RouterLink></p>
    </div>
  </section>
</template>
