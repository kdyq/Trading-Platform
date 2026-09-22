<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { listReports, withdrawReport } from '../api/reports'
import type { ReportItem } from '../api/reports'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const reports = ref<ReportItem[]>([])
const loading = ref(true)
const error = ref('')
const statusLabels: Record<ReportItem['status'], string> = {
  open: '已提交',
  reviewing: '处理中',
  resolved: '已处理',
  dismissed: '未认定违规',
  withdrawn: '已撤回',
  appealed: '申诉复核中',
}
const targetLabels = { product: '商品', user: '用户', message: '聊天', order: '订单' }

async function load() {
  if (!auth.accessToken) return
  try {
    reports.value = (await listReports(auth.accessToken)).items
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '举报记录加载失败'
  } finally {
    loading.value = false
  }
}

async function withdraw(item: ReportItem) {
  if (!auth.accessToken) return
  try {
    Object.assign(item, await withdrawReport(auth.accessToken, item.id))
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '举报撤回失败'
  }
}

onMounted(load)
</script>

<template>
  <section class="container reports-page">
    <header>
      <p class="eyebrow">安全与治理</p>
      <h1>我的举报</h1>
      <p>这里仅展示你提交的材料和公开处理结论，内部调查记录与他人信息不会公开。</p>
    </header>
    <p v-if="loading">正在加载举报记录…</p>
    <p v-else-if="!reports.length">暂时没有举报记录。</p>
    <div v-else class="reports-list">
      <article v-for="item in reports" :key="item.id" class="report-item">
        <div>
          <span>{{ targetLabels[item.target_type] }}</span>
          <strong>{{ statusLabels[item.status] }}</strong>
        </div>
        <p>{{ item.details }}</p>
        <p v-if="item.public_result" class="report-result">处理结果：{{ item.public_result }}</p>
        <small>
          {{ new Date(item.created_at).toLocaleString('zh-CN') }} ·
          {{ item.evidence.length }} 个附件
        </small>
        <button v-if="item.status === 'open'" type="button" @click="withdraw(item)">
          撤回举报
        </button>
      </article>
    </div>
    <p v-if="error" class="reports-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.reports-page {
  padding-block: 2.5rem 5rem;
}
.reports-page h1 {
  margin: 0.3rem 0;
  font-size: clamp(2rem, 5vw, 3.5rem);
}
.reports-page header > p:last-child {
  color: var(--color-text-muted, #6f675f);
}
.reports-list {
  display: grid;
  gap: 1rem;
  margin-top: 2rem;
}
.report-item {
  border: 1px solid var(--color-border, #ded8d0);
  border-radius: 18px;
  padding: 1.25rem;
  background: white;
}
.report-item > div {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}
.report-item strong {
  color: var(--color-primary, #ff6b35);
}
.report-item small {
  color: var(--color-text-muted, #6f675f);
}
.report-item button {
  margin-top: 1rem;
  border: 1px solid var(--color-border, #ded8d0);
  border-radius: 999px;
  padding: 0.5rem 0.9rem;
  background: white;
  cursor: pointer;
}
.report-result {
  padding: 0.75rem;
  border-radius: 12px;
  background: #f4f8f4;
  color: #2e6c50;
}
.reports-error {
  color: #a13b2b;
}
</style>
