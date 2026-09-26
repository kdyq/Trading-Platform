<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

import { ApiError, requestBlob } from '../api/client'
import {
  downloadAppealEvidence,
  decideModerationProduct,
  decideModerationReport,
  listModerationProducts,
  listModerationReports,
  listReportAppeals,
  reviewReportAppeal,
} from '../api/moderation'
import type { ModerationProduct, ModerationReport, ReportAppeal } from '../api/moderation'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const products = ref<ModerationProduct[]>([])
const reports = ref<ModerationReport[]>([])
const appeals = ref<ReportAppeal[]>([])
const productPage = ref(1)
const reportPage = ref(1)
const appealPage = ref(1)
const productTotal = ref(0)
const reportTotal = ref(0)
const appealTotal = ref(0)
const status = ref('pending_review')
const loading = ref(true)
const error = ref('')
const noteById = ref<Record<string, string>>({})
const reasonById = ref<Record<string, string>>({})
const busyId = ref('')
const reportPublicNotes = ref<Record<string, string>>({})
const reportInternalNotes = ref<Record<string, string>>({})
const reportPenalties = ref<Record<string, 'none' | 'warn' | 'hide' | 'suspend'>>({})
const appealNotes = ref<Record<string, string>>({})
const productImageBlobs = ref<Record<string, string>>({})

function clearProductImageBlobs() {
  for (const url of Object.values(productImageBlobs.value)) URL.revokeObjectURL(url)
  productImageBlobs.value = {}
}

async function load() {
  if (!auth.accessToken) {
    loading.value = false
    error.value = '请先登录审核账号。'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [productResult, reportResult, appealResult] = await Promise.all([
      listModerationProducts(auth.accessToken, status.value, productPage.value),
      listModerationReports(auth.accessToken, reportPage.value),
      listReportAppeals(auth.accessToken, appealPage.value),
    ])
    products.value = productResult.items
    productTotal.value = productResult.total
    clearProductImageBlobs()
    await Promise.all(
      productResult.items.map(async (product) => {
        if (!product.image_urls[0] || !auth.accessToken) return
        try {
          const blob = await requestBlob(product.image_urls[0], auth.accessToken)
          productImageBlobs.value[product.id] = URL.createObjectURL(blob)
        } catch {
          // The moderation card remains usable if an image file is unavailable.
        }
      }),
    )
    reports.value = reportResult.items
    reportTotal.value = reportResult.total
    appeals.value = appealResult.items
    appealTotal.value = appealResult.total
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '审核队列加载失败'
  } finally {
    loading.value = false
  }
}

function changePage(queue: 'product' | 'report' | 'appeal', delta: number) {
  if (queue === 'product') productPage.value = Math.max(1, productPage.value + delta)
  else if (queue === 'report') reportPage.value = Math.max(1, reportPage.value + delta)
  else appealPage.value = Math.max(1, appealPage.value + delta)
  void load()
}

function changeProductStatus() {
  productPage.value = 1
  void load()
}

async function saveAppealEvidence(appeal: ReportAppeal, evidenceId: string) {
  if (!auth.accessToken) return
  try {
    const blob = await downloadAppealEvidence(auth.accessToken, appeal.id, evidenceId)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `appeal-evidence-${evidenceId}`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '复核材料下载失败'
  }
}

async function reviewAppeal(appeal: ReportAppeal, action: 'uphold' | 'reverse') {
  if (!auth.accessToken || busyId.value) return
  const reason = appealNotes.value[appeal.id]?.trim() || ''
  if (reason.length < 5) {
    error.value = '请填写申诉复核理由。'
    return
  }
  busyId.value = appeal.id
  try {
    Object.assign(appeal, await reviewReportAppeal(auth.accessToken, appeal.id, action, reason))
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '申诉复核失败'
  } finally {
    busyId.value = ''
  }
}

async function decideReport(report: ModerationReport, action: 'review' | 'dismiss' | 'violate') {
  if (!auth.accessToken || busyId.value) return
  const publicResult = reportPublicNotes.value[report.id]?.trim() || ''
  const internalReason = reportInternalNotes.value[report.id]?.trim() || ''
  if (publicResult.length < 5 || internalReason.length < 5) {
    error.value = '请填写公开结论和内部调查理由。'
    return
  }
  busyId.value = report.id
  try {
    const updated = await decideModerationReport(auth.accessToken, report, {
      action,
      penalty_code: action === 'violate' ? reportPenalties.value[report.id] || 'warn' : 'none',
      penalty_points: action === 'violate' ? 5 : 0,
      public_result: publicResult,
      internal_reason: internalReason,
    })
    Object.assign(report, updated)
  } catch (caught) {
    if (caught instanceof ApiError && caught.code === 'report_version_conflict') await load()
    error.value = caught instanceof Error ? caught.message : '举报处理失败'
  } finally {
    busyId.value = ''
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
onUnmounted(clearProductImageBlobs)
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
        <select v-model="status" @change="changeProductStatus">
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
        <img
          v-if="productImageBlobs[product.id]"
          :src="productImageBlobs[product.id]"
          :alt="product.title"
        />
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
              v-if="product.status === 'on_sale'"
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
    <nav class="moderation-actions" aria-label="商品审核分页">
      <button type="button" :disabled="productPage <= 1" @click="changePage('product', -1)">
        上一页
      </button>
      <span>第 {{ productPage }} 页 · 共 {{ productTotal }} 件</span>
      <button
        type="button"
        :disabled="productPage * 20 >= productTotal"
        @click="changePage('product', 1)"
      >
        下一页
      </button>
    </nav>
    <p v-if="error" class="moderation-error" role="alert">{{ error }}</p>
    <section class="report-queue">
      <header>
        <p class="eyebrow">举报调查</p>
        <h2>举报处置队列</h2>
      </header>
      <article v-for="report in reports" :key="report.id" class="report-review-card">
        <div>
          <strong>{{ report.target_type }} · {{ report.reason_code }}</strong>
          <span>{{ report.status }} · 版本 {{ report.version }}</span>
        </div>
        <p>{{ report.details }}</p>
        <small>已引用材料：{{ report.evidence_ids.length }} 项</small>
        <label>
          <span>公开处理结论</span>
          <textarea v-model="reportPublicNotes[report.id]" rows="2" maxlength="500" />
        </label>
        <label>
          <span>内部调查理由</span>
          <textarea v-model="reportInternalNotes[report.id]" rows="2" maxlength="1000" />
        </label>
        <label>
          <span>处罚</span>
          <select v-model="reportPenalties[report.id]">
            <option value="warn">警告与信用扣减</option>
            <option value="hide">隐藏关联商品</option>
            <option value="suspend">暂停用户（高风险）</option>
          </select>
        </label>
        <div class="moderation-actions">
          <button type="button" @click="decideReport(report, 'review')">开始调查</button>
          <button class="secondary" type="button" @click="decideReport(report, 'dismiss')">
            驳回举报
          </button>
          <button type="button" @click="decideReport(report, 'violate')">确认违规</button>
        </div>
      </article>
      <nav class="moderation-actions" aria-label="举报分页">
        <button type="button" :disabled="reportPage <= 1" @click="changePage('report', -1)">
          上一页
        </button>
        <span>第 {{ reportPage }} 页 · 共 {{ reportTotal }} 件</span>
        <button
          type="button"
          :disabled="reportPage * 20 >= reportTotal"
          @click="changePage('report', 1)"
        >
          下一页
        </button>
      </nav>
    </section>
    <section class="report-queue">
      <header>
        <p class="eyebrow">独立复核</p>
        <h2>待处理申诉</h2>
      </header>
      <article v-for="appeal in appeals" :key="appeal.id" class="report-review-card">
        <strong>举报 {{ appeal.report_id }}</strong>
        <small>{{ appeal.status }}</small>
        <p>{{ appeal.details }}</p>
        <div v-if="appeal.evidence_ids.length" class="moderation-actions">
          <button
            v-for="evidenceId in appeal.evidence_ids"
            :key="evidenceId"
            type="button"
            @click="saveAppealEvidence(appeal, evidenceId)"
          >
            下载复核材料
          </button>
        </div>
        <label>
          <span>复核理由</span>
          <textarea v-model="appealNotes[appeal.id]" rows="3" maxlength="1000" />
        </label>
        <div class="moderation-actions">
          <button class="secondary" type="button" @click="reviewAppeal(appeal, 'uphold')">
            维持决定
          </button>
          <button type="button" @click="reviewAppeal(appeal, 'reverse')">撤销处罚</button>
        </div>
      </article>
      <nav class="moderation-actions" aria-label="申诉分页">
        <button type="button" :disabled="appealPage <= 1" @click="changePage('appeal', -1)">
          上一页
        </button>
        <span>第 {{ appealPage }} 页 · 共 {{ appealTotal }} 件</span>
        <button
          type="button"
          :disabled="appealPage * 20 >= appealTotal"
          @click="changePage('appeal', 1)"
        >
          下一页
        </button>
      </nav>
    </section>
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
.report-queue {
  margin-top: 3rem;
}
.report-review-card {
  display: grid;
  gap: 0.75rem;
  margin-top: 1rem;
  border: 1px solid #ded8d0;
  border-radius: 18px;
  padding: 1.25rem;
  background: white;
}
.report-review-card > div:first-child {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}
.report-review-card label {
  display: grid;
  gap: 0.4rem;
  font-weight: 700;
}
.report-review-card textarea,
.report-review-card select {
  border: 1px solid #ded8d0;
  border-radius: 10px;
  padding: 0.7rem;
  font: inherit;
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
