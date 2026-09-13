<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { requestPasswordReset, resetPassword } from '../api/account'
import { ApiError } from '../api/client'

const route = useRoute()
const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''))
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')

async function submitRequest() {
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await requestPasswordReset(email.value)
    message.value = result.message
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '暂时无法发送重置邮件'
  } finally {
    busy.value = false
  }
}

async function submitReset() {
  errorMessage.value = ''
  if (password.value !== confirmPassword.value) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }
  busy.value = true
  try {
    const result = await resetPassword(token.value, password.value)
    message.value = result.message
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '暂时无法重置密码'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="container narrow-page">
    <div class="form-card">
      <p class="eyebrow">账户安全</p>
      <h1>{{ token ? '设置新密码' : '找回密码' }}</h1>
      <p v-if="!token">填写登录邮箱。无论账户是否存在，页面都会显示相同提示。</p>
      <p v-else>新密码至少 8 位，必须同时包含英文字母和数字，且不能有空格。</p>

      <form v-if="!message && !token" class="auth-form" @submit.prevent="submitRequest">
        <label class="field">
          <span>登录邮箱</span>
          <input v-model.trim="email" autocomplete="email" required type="email" />
        </label>
        <p v-if="errorMessage" class="form-message error-message" role="alert">
          {{ errorMessage }}
        </p>
        <button class="button button-primary form-submit" :disabled="busy" type="submit">
          {{ busy ? '正在发送' : '发送重置邮件' }}
        </button>
      </form>

      <form v-else-if="!message" class="auth-form" @submit.prevent="submitReset">
        <label class="field">
          <span>新密码</span>
          <input
            v-model="password"
            autocomplete="new-password"
            minlength="8"
            maxlength="128"
            required
            type="password"
          />
        </label>
        <label class="field">
          <span>再次输入新密码</span>
          <input
            v-model="confirmPassword"
            autocomplete="new-password"
            minlength="8"
            maxlength="128"
            required
            type="password"
          />
        </label>
        <p v-if="errorMessage" class="form-message error-message" role="alert">
          {{ errorMessage }}
        </p>
        <button class="button button-primary form-submit" :disabled="busy" type="submit">
          {{ busy ? '正在保存' : '重置密码' }}
        </button>
      </form>

      <div v-else class="auth-form">
        <p class="form-message success-message" role="status">{{ message }}</p>
        <RouterLink class="button button-primary" to="/login">返回登录</RouterLink>
      </div>
    </div>
  </section>
</template>
