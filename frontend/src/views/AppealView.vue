<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'

import { createReportAppeal } from '../api/moderation'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const auth = useAuthStore()
const details = ref('')
const busy = ref(false)
const message = ref('')
const error = ref('')

async function submit() {
  if (!auth.accessToken || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await createReportAppeal(auth.accessToken, String(route.params.reportId), details.value.trim())
    message.value = '申诉已提交，将由不同审核员复核。'
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '申诉提交失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="container appeal-page">
    <p class="eyebrow">治理申诉</p>
    <h1>申请复核处理决定</h1>
    <p>请说明原处理决定中可能存在的事实或判断错误。复核人员默认不得是原决定人。</p>
    <form @submit.prevent="submit">
      <label>
        <span>申诉说明</span>
        <textarea v-model="details" minlength="10" maxlength="1000" rows="8" required />
      </label>
      <button type="submit" :disabled="busy || details.trim().length < 10">
        {{ busy ? '正在提交…' : '提交申诉' }}
      </button>
    </form>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="error" class="appeal-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.appeal-page {
  max-width: 760px;
  padding-block: 3rem 6rem;
}
.appeal-page h1 {
  font-size: clamp(2rem, 5vw, 3.5rem);
}
.appeal-page form,
.appeal-page label {
  display: grid;
  gap: 0.75rem;
}
.appeal-page textarea {
  border: 1px solid #ded8d0;
  border-radius: 14px;
  padding: 1rem;
  font: inherit;
}
.appeal-page button {
  justify-self: start;
  border: 0;
  border-radius: 999px;
  padding: 0.75rem 1.1rem;
  background: #ff6b35;
  color: white;
  font: inherit;
  font-weight: 700;
}
.appeal-error {
  color: #a13b2b;
}
</style>
