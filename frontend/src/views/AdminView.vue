<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError } from '../api/client'
import { decideModerationProduct, listModerationProducts } from '../api/moderation'
import type { ModerationProduct } from '../api/moderation'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const products = ref<ModerationProduct[]>([])
const status = ref('pending_review')
const loading = ref(true)
const error = ref('')
const noteById = ref<Record<string, string>>({})
const reasonById = ref<Record<string, string>>({})
const busyId = ref('')

async function load() {
  if (!auth.accessToken) {
    loading.value = false
    error.value = '请先登录审核账号。'
    return
  }
  loading.value = true
  error.value = ''
  try {
    products.value = (await listModerationProducts(auth.accessToken, status.value)).items
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '审核队列加载失败'
  } finally {
    loading.value = false
  }
}

async function decide(
  product: ModerationProduct,
  action: 'approve' | 'reject' | 'hide' | 'restore',
) {
  if (!auth.accessToken || busyId.value) return
  const note = noteById.value[product.id]?.trim() || ''
  if (note.length < 5) {
    error.value = '请填写至少 5 个字的公开处理说明。'
    return
  }
  busyId.value = product.id
  error.value = ''
  try {
    await decideModerationProduct(
      auth.accessToken,
      product,
      action,
      reasonById.value[product.id] || 'content_review',
      note,
    )
    products.value = products.value.filter((item) => item.id !== product.id)
  } catch (caught) {
    if (caught instanceof ApiError && caught.code === 'product_version_conflict') await load()
    error.value = caught instanceof Error ? caught.message : '审核操作失败'
  } finally {
    busyId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="moderation-page">
    <header class="moderation-heading">
      <div>
        <p class="eyebrow">内容治理</p>
        <h1>商品审核工作台</h1>
        <p>逐项核对商品信息与图片。所有决定都会记录操作者、理由和商品版本。</p>
      </div>
      <label>
        <span>队列</span>
        <select v-model="status" @change="load">
          <option value="pending_review">待审核</option>
          <option value="on_sale">在售</option>
          <option value="hidden">已隐藏</option>
          <option value="rejected">已驳回</option>
        </select>
      </label>
    </header>
    <p v-if="loading">正在加载审核队列…</p>
    <p v-else-if="!products.length && !error">当前队列为空。</p>
    <div class="moderation-grid">
      <article v-for="product in products" :key="product.id" class="moderation-card">
        <img v-if="product.image_urls[0]" :src="product.image_urls[0]" :alt="product.title" />
        <div class="moderation-card-body">
          <div class="moderation-card-title">
            <h2>{{ product.title }}</h2>
            <strong>¥{{ product.price }}</strong>
          </div>
          <p>{{ product.description }}</p>
          <small>卖家：{{ product.seller_name }} · 版本 {{ product.version }}</small>
          <label>
            <span>原因</span>
            <select v-model="reasonById[product.id]">
              <option value="content_review">内容审核</option>
              <option value="insufficient_detail">信息不完整</option>
              <option value="prohibited">违禁内容</option>
              <option value="unsafe">安全风险</option>
            </select>
          </label>
          <label>
            <span>给卖家的公开说明</span>
            <textarea v-model="noteById[product.id]" rows="3" maxlength="500" />
          </label>
          <div class="moderation-actions">
            <button
              v-if="product.status === 'pending_review'"
              type="button"
              :disabled="busyId === product.id"
              @click="decide(product, 'approve')"
            >
              通过
            </button>
            <button
              v-if="product.status === 'pending_review'"
              class="secondary"
              type="button"
              :disabled="busyId === product.id"
              @click="decide(product, 'reject')"
            >
              驳回
            </button>
            <button
              v-if="['on_sale', 'reserved', 'sold'].includes(product.status)"
              class="secondary"
              type="button"
              :disabled="busyId === product.id"
              @click="decide(product, 'hide')"
            >
              隐藏
            </button>
            <button
              v-if="product.status === 'hidden'"
              type="button"
              :disabled="busyId === product.id"
              @click="decide(product, 'restore')"
            >
              恢复
            </button>
          </div>
        </div>
      </article>
    </div>
    <p v-if="error" class="moderation-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.moderation-page {
  max-width: 1240px;
  margin: 0 auto;
  padding: 2rem;
}
.moderation-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 2rem;
  margin-bottom: 2rem;
}
.moderation-heading h1 {
  margin: 0.3rem 0;
  font-size: clamp(2rem, 4vw, 3.25rem);
}
.moderation-heading p {
  color: #6f675f;
}
.moderation-heading label,
.moderation-card label {
  display: grid;
  gap: 0.4rem;
  font-weight: 700;
}
.moderation-grid {
  display: grid;
  gap: 1rem;
}
.moderation-card {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #ded8d0;
  border-radius: 18px;
  background: white;
}
.moderation-card > img {
  width: 100%;
  height: 100%;
  min-height: 260px;
  object-fit: cover;
}
.moderation-card-body {
  display: grid;
  gap: 0.85rem;
  padding: 1.25rem;
}
.moderation-card-title {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}
.moderation-card-title h2 {
  margin: 0;
}
.moderation-card select,
.moderation-card textarea,
.moderation-heading select {
  border: 1px solid #ded8d0;
  border-radius: 10px;
  padding: 0.7rem;
  background: white;
  font: inherit;
}
.moderation-actions {
  display: flex;
  gap: 0.65rem;
}
.moderation-actions button {
  border: 0;
  border-radius: 999px;
  padding: 0.65rem 1rem;
  background: #ff6b35;
  color: white;
  cursor: pointer;
}
.moderation-actions .secondary {
  border: 1px solid #ded8d0;
  background: white;
  color: #29241f;
}
.moderation-error {
  color: #a13b2b;
}
@media (max-width: 760px) {
  .moderation-heading,
  .moderation-card {
    display: grid;
    grid-template-columns: 1fr;
  }
  .moderation-card > img {
    max-height: 260px;
  }
}
</style>
