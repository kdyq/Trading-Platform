<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { ApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'

const email = ref('')
const password = ref('')
const busy = ref(false)
const errorMessage = ref('')
const auth = useAuthStore()
const router = useRouter()

async function submit() {
  busy.value = true
  errorMessage.value = ''
  try {
    await auth.login(email.value, password.value)
    await router.push('/')
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '登录失败，请稍后重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="container narrow-page">
    <div class="form-card">
      <p class="eyebrow">欢迎回来</p>
      <h1>登录拾光集市</h1>
      <p>使用普通登录邮箱进入账户。校园认证邮箱在登录后单独填写。</p>
      <form class="auth-form" @submit.prevent="submit">
        <label class="field">
          <span>登录邮箱</span>
          <input v-model.trim="email" autocomplete="email" name="email" required type="email" />
        </label>
        <label class="field">
          <span>密码</span>
          <input
            v-model="password"
            autocomplete="current-password"
            maxlength="128"
            name="password"
            required
            type="password"
          />
        </label>
        <p v-if="errorMessage" class="form-message error-message" role="alert">
          {{ errorMessage }}
        </p>
        <button class="button button-primary form-submit" :disabled="busy" type="submit">
          {{ busy ? '正在登录' : '登录' }}
        </button>
      </form>
      <p class="form-switch">还没有账户？<RouterLink to="/register">注册普通账户</RouterLink></p>
    </div>
  </section>
</template>
