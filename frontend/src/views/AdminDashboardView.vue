<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { dashboardMetrics } from '../api/admin'
import type { DashboardMetrics } from '../api/admin'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const metrics = ref<DashboardMetrics | null>(null)
const error = ref('')
async function load() {
  if (!auth.accessToken) return
  try {
    metrics.value = await dashboardMetrics(auth.accessToken)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '指标加载失败'
  }
}
onMounted(load)
</script>

<template>
  <section class="admin-ops">
    <header>
      <div>
        <p class="eyebrow">Operations / Last 7 Days</p>
        <h1>运营概览</h1>
        <p>事实统计采用 UTC 半开时间区间；“当前”指标是实时状态快照。</p>
      </div>
      <button class="secondary" @click="load">刷新指标</button>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template v-if="metrics">
      <div class="admin-ops-card">
        <p>
          统计区间：{{ new Date(metrics.starts_at).toLocaleString() }} —
          {{ new Date(metrics.ends_at).toLocaleString() }}
        </p>
      </div>
      <div class="metric-grid">
        <div class="metric">
          <span>新增注册</span><strong>{{ metrics.registered_users }}</strong
          ><small>users.created_at</small>
        </div>
        <div class="metric">
          <span>校园认证成功</span><strong>{{ metrics.verified_campus }}</strong
          ><small>campus_verifications.verified_at</small>
        </div>
        <div class="metric">
          <span>首次上架</span><strong>{{ metrics.published_products }}</strong
          ><small>products.published_at</small>
        </div>
        <div class="metric">
          <span>完成交易</span><strong>{{ metrics.completed_orders }}</strong
          ><small>orders.completed_at</small>
        </div>
        <div class="metric">
          <span>提交举报</span><strong>{{ metrics.submitted_reports }}</strong
          ><small>reports.created_at</small>
        </div>
        <div class="metric">
          <span>当前待审商品</span><strong>{{ metrics.pending_products_now }}</strong
          ><small>pending_review 快照</small>
        </div>
        <div class="metric">
          <span>当前活跃会话</span><strong>{{ metrics.active_sessions_now }}</strong
          ><small>未撤销且未过期</small>
        </div>
      </div>
    </template>
    <div v-else-if="!error" class="admin-ops-card">正在读取可复核指标…</div>
  </section>
</template>
