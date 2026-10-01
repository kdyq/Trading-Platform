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
        <p>查看区间内的新增与完成数据；“当前”指标反映实时状态。</p>
      </div>
      <button class="secondary" @click="load">刷新指标</button>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template v-if="metrics">
      <div class="admin-ops-card">
        <p>
          统计区间（本地时间）：{{ new Date(metrics.starts_at).toLocaleString() }} —
          {{ new Date(metrics.ends_at).toLocaleString() }}
        </p>
      </div>
      <div class="metric-grid">
        <div class="metric">
          <span>新增注册</span><strong>{{ metrics.registered_users }}</strong
          ><small>按账户注册时间</small>
        </div>
        <div class="metric">
          <span>校园认证成功</span><strong>{{ metrics.verified_campus }}</strong
          ><small>按认证通过时间</small>
        </div>
        <div class="metric">
          <span>首次上架</span><strong>{{ metrics.published_products }}</strong
          ><small>按首次发布时间</small>
        </div>
        <div class="metric">
          <span>完成交易</span><strong>{{ metrics.completed_orders }}</strong
          ><small>按交易完成时间</small>
        </div>
        <div class="metric">
          <span>提交举报</span><strong>{{ metrics.submitted_reports }}</strong
          ><small>按举报提交时间</small>
        </div>
        <div class="metric">
          <span>当前待审商品</span><strong>{{ metrics.pending_products_now }}</strong
          ><small>等待工作人员审核</small>
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
