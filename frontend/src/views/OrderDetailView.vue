<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  acceptOrder,
  cancelOrder,
  completeOrder,
  confirmMeeting,
  createReview,
  deliverOrder,
  disputeOrder,
  getOrder,
  proposeMeeting,
} from '../api/orders'
import type { MeetingProposal, OrderDetail, OrderStatus } from '../api/orders'
import UiButton from '../components/ui/UiButton.vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const order = ref<OrderDetail | null>(null)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const actionError = ref('')
const meetingTime = ref('')
const meetingLocation = ref('')
const cancelReason = ref('schedule_failed')
const cancelNote = ref('')
const disputeReason = ref('item_not_as_described')
const disputeDetails = ref('')
const rating = ref(5)
const reviewContent = ref('')
const reviewTags = ref<string[]>([])

const statusLabels: Record<OrderStatus, string> = {
  pending_seller_confirmation: '待卖家确认',
  accepted: '待预约',
  scheduled: '待面交',
  seller_delivered: '待买家确认',
  completed: '已完成',
  cancelled: '已取消',
  expired: '已过期',
  disputed: '争议处理中',
}
const reviewTagOptions = [
  ['good_communication', '沟通顺畅'],
  ['on_time', '准时赴约'],
  ['item_as_described', '描述一致'],
  ['friendly', '友善礼貌'],
  ['smooth_transaction', '交易顺利'],
]

const isBuyer = computed(() => auth.user?.id === order.value?.buyer_id)
const isSeller = computed(() => auth.user?.id === order.value?.seller_id)
const counterparty = computed(() =>
  isBuyer.value ? order.value?.seller_display_name : order.value?.buyer_display_name,
)
const canArrange = computed(() => ['accepted', 'scheduled'].includes(order.value?.status || ''))
const canCancel = computed(() =>
  ['pending_seller_confirmation', 'accepted', 'scheduled'].includes(order.value?.status || ''),
)
const canDispute = computed(() =>
  ['accepted', 'scheduled', 'seller_delivered'].includes(order.value?.status || ''),
)
const hasSide = computed(
  () =>
    canCancel.value ||
    canDispute.value ||
    ['cancelled', 'disputed'].includes(order.value?.status || ''),
)

function formatDate(value: string | null) {
  if (!value) return '尚未确定'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function proposalNeedsMyConfirmation(proposal: MeetingProposal) {
  if (proposal.status !== 'pending') return false
  return isBuyer.value ? !proposal.buyer_confirmed_at : !proposal.seller_confirmed_at
}

async function load() {
  if (!auth.accessToken) {
    await router.replace({ path: '/login', query: { next: route.fullPath } })
    return
  }
  loading.value = true
  error.value = ''
  try {
    order.value = await getOrder(auth.accessToken, String(route.params.id))
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '订单详情暂时无法加载'
  } finally {
    loading.value = false
  }
}

async function run(action: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true
  actionError.value = ''
  try {
    await action()
    await load()
  } catch (caught) {
    actionError.value = caught instanceof Error ? caught.message : '操作失败，请稍后重试'
  } finally {
    busy.value = false
  }
}

function submitMeeting() {
  if (!auth.accessToken || !order.value || !meetingTime.value || !meetingLocation.value.trim())
    return
  return run(async () => {
    await proposeMeeting(
      auth.accessToken!,
      order.value!.id,
      new Date(meetingTime.value).toISOString(),
      meetingLocation.value.trim(),
    )
    meetingTime.value = ''
    meetingLocation.value = ''
  })
}

function toggleReviewTag(tag: string) {
  reviewTags.value = reviewTags.value.includes(tag)
    ? reviewTags.value.filter((item) => item !== tag)
    : [...reviewTags.value, tag]
}

onMounted(load)
</script>

<template>
  <section class="container order-detail-page" aria-live="polite">
    <RouterLink class="order-back" to="/orders">返回我的订单</RouterLink>

    <div v-if="loading" class="order-detail-loading">
      <div class="ui-skeleton detail-skeleton-title" />
      <div class="ui-skeleton detail-skeleton-panel" />
    </div>
    <div v-else-if="error" class="detail-state" role="alert">
      <h1>订单详情暂时无法加载</h1>
      <p>{{ error }}</p>
      <UiButton variant="secondary" @click="load">重新加载</UiButton>
    </div>

    <template v-else-if="order">
      <header class="order-detail-heading">
        <div>
          <span class="order-detail-status" :data-status="order.status">
            {{ statusLabels[order.status] }}
          </span>
          <h1>{{ order.product_title }}</h1>
          <p>{{ order.campus_name }} · 与 {{ counterparty }} 的线下面交</p>
        </div>
        <strong class="num detail-price">¥{{ order.amount }}</strong>
      </header>

      <p v-if="actionError" class="detail-action-error" role="alert">{{ actionError }}</p>

      <div class="order-detail-layout" :class="{ 'without-side': !hasSide }">
        <main class="detail-main">
          <section class="detail-panel order-summary-panel">
            <h2>交易概况</h2>
            <dl class="detail-facts">
              <div>
                <dt>付款方式</dt>
                <dd>线下当面支付</dd>
              </div>
              <div>
                <dt>预约时间</dt>
                <dd>{{ formatDate(order.scheduled_for) }}</dd>
              </div>
              <div>
                <dt>买家</dt>
                <dd>{{ order.buyer_display_name }}</dd>
              </div>
              <div>
                <dt>卖家</dt>
                <dd>{{ order.seller_display_name }}</dd>
              </div>
            </dl>
            <div class="detail-primary-actions">
              <UiButton
                v-if="isSeller && order.status === 'pending_seller_confirmation'"
                :disabled="busy"
                @click="run(() => acceptOrder(auth.accessToken!, order!.id))"
              >
                接受交易
              </UiButton>
              <UiButton
                v-if="isSeller && canArrange"
                :disabled="busy"
                @click="run(() => deliverOrder(auth.accessToken!, order!.id))"
              >
                确认已交付
              </UiButton>
              <UiButton
                v-if="isBuyer && order.status === 'seller_delivered'"
                :disabled="busy"
                @click="run(() => completeOrder(auth.accessToken!, order!.id))"
              >
                确认收货
              </UiButton>
            </div>
          </section>

          <section v-if="canArrange || order.meeting_proposals.length" class="detail-panel">
            <h2>面交安排</h2>
            <form v-if="canArrange" class="meeting-form" @submit.prevent="submitMeeting">
              <label
                ><span>候选时间</span><input v-model="meetingTime" type="datetime-local" required
              /></label>
              <label
                ><span>校园内地点</span
                ><input
                  v-model="meetingLocation"
                  maxlength="200"
                  required
                  placeholder="例如：图书馆东门"
              /></label>
              <UiButton type="submit" :disabled="busy || !meetingTime || !meetingLocation.trim()">
                提出安排
              </UiButton>
            </form>
            <div v-if="order.meeting_proposals.length" class="meeting-list">
              <article
                v-for="proposal in order.meeting_proposals"
                :key="proposal.id"
                class="meeting-item"
              >
                <div>
                  <strong>{{ formatDate(proposal.proposed_for) }}</strong>
                  <p>{{ proposal.location_text }}</p>
                  <small>{{
                    proposal.status === 'accepted'
                      ? '双方已确认'
                      : proposal.status === 'pending'
                        ? '等待确认'
                        : '已失效'
                  }}</small>
                </div>
                <UiButton
                  v-if="proposalNeedsMyConfirmation(proposal)"
                  variant="secondary"
                  :disabled="busy"
                  @click="run(() => confirmMeeting(auth.accessToken!, order!.id, proposal.id))"
                >
                  确认安排
                </UiButton>
              </article>
            </div>
          </section>

          <section class="detail-panel">
            <h2>订单记录</h2>
            <ol class="order-timeline">
              <li v-for="event in order.events" :key="event.id">
                <time>{{ formatDate(event.created_at) }}</time>
                <div>
                  <strong>{{ statusLabels[event.to_status] }}</strong>
                  <p>{{ event.note || '订单状态已更新' }}</p>
                </div>
              </li>
            </ol>
          </section>

          <section v-if="order.reviews.length || order.can_review" class="detail-panel">
            <h2>交易评价</h2>
            <form
              v-if="order.can_review"
              class="review-form"
              @submit.prevent="
                run(() =>
                  createReview(auth.accessToken!, order!.id, rating, reviewTags, reviewContent),
                )
              "
            >
              <label
                ><span>评分</span
                ><select v-model="rating">
                  <option v-for="score in [5, 4, 3, 2, 1]" :key="score" :value="score">
                    {{ score }} 分
                  </option>
                </select></label
              >
              <fieldset>
                <legend>标签</legend>
                <button
                  v-for="item in reviewTagOptions"
                  :key="item[0]"
                  type="button"
                  :class="{ selected: reviewTags.includes(item[0]) }"
                  @click="toggleReviewTag(item[0])"
                >
                  {{ item[1] }}
                </button>
              </fieldset>
              <label
                ><span>评价内容</span
                ><textarea
                  v-model="reviewContent"
                  maxlength="1000"
                  rows="4"
                  placeholder="可选，写下真实交易体验"
                />
              </label>
              <UiButton type="submit" :disabled="busy">提交评价</UiButton>
            </form>
            <div class="review-list">
              <article v-for="review in order.reviews" :key="review.id">
                <div>
                  <strong>{{ review.reviewer_name }}</strong
                  ><span class="num">{{ review.rating }} / 5</span>
                </div>
                <p v-if="review.content">{{ review.content }}</p>
                <small>{{ formatDate(review.created_at) }}</small>
              </article>
            </div>
          </section>
        </main>

        <aside v-if="hasSide" class="detail-side">
          <section v-if="canCancel" class="detail-panel compact-panel">
            <h2>取消订单</h2>
            <label
              ><span>原因</span
              ><select v-model="cancelReason">
                <option value="changed_mind">改变计划</option>
                <option value="schedule_failed">无法协调时间</option>
                <option value="item_issue">商品情况有变</option>
                <option value="other">其他</option>
              </select></label
            >
            <label
              ><span>补充说明</span><textarea v-model="cancelNote" maxlength="500" rows="3" />
            </label>
            <UiButton
              variant="secondary"
              :disabled="busy"
              @click="
                run(() => cancelOrder(auth.accessToken!, order!.id, cancelReason, cancelNote))
              "
            >
              取消订单
            </UiButton>
          </section>

          <section v-if="canDispute" class="detail-panel compact-panel">
            <h2>交易异常</h2>
            <p>争议会冻结订单，等待授权人员处理。</p>
            <label
              ><span>争议原因</span
              ><select v-model="disputeReason">
                <option value="item_not_as_described">商品与描述不符</option>
                <option value="no_show">未按约出现</option>
                <option value="safety_concern">安全问题</option>
                <option value="other">其他</option>
              </select></label
            >
            <label
              ><span>事实说明</span
              ><textarea
                v-model="disputeDetails"
                minlength="5"
                maxlength="1000"
                rows="4"
                required
              />
            </label>
            <UiButton
              variant="secondary"
              :disabled="busy || disputeDetails.trim().length < 5"
              @click="
                run(() =>
                  disputeOrder(auth.accessToken!, order!.id, disputeReason, disputeDetails.trim()),
                )
              "
            >
              发起争议
            </UiButton>
          </section>

          <section
            v-if="order.status === 'cancelled' || order.status === 'disputed'"
            class="detail-panel compact-panel"
          >
            <h2>{{ order.status === 'disputed' ? '争议说明' : '取消说明' }}</h2>
            <p>{{ order.dispute_details || order.cancellation_note || '未提供补充说明' }}</p>
          </section>
        </aside>
      </div>
    </template>
  </section>
</template>

<style scoped>
.order-detail-page {
  padding-block: 2rem 6rem;
}
.order-back {
  display: inline-block;
  margin-bottom: 1.5rem;
  color: var(--color-primary);
  font-weight: 700;
}
.order-detail-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 2rem;
  margin-bottom: 2rem;
}
.order-detail-heading h1 {
  margin: 0.65rem 0 0.45rem;
  font-size: clamp(2rem, 4vw, 3rem);
}
.order-detail-heading p {
  margin: 0;
  color: var(--color-text-muted);
}
.order-detail-status {
  display: inline-flex;
  border-radius: 999px;
  padding: 0.4rem 0.75rem;
  color: #7b461f;
  background: #fff0df;
  font-weight: 750;
}
.order-detail-status[data-status='completed'] {
  color: #2e6553;
  background: #e6f4ed;
}
.order-detail-status[data-status='disputed'] {
  color: #8b352f;
  background: #fae9e7;
}
.detail-price {
  font-size: 2rem;
  color: var(--color-primary);
}
.order-detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 20rem;
  gap: 1.25rem;
  align-items: start;
}
.order-detail-layout.without-side {
  grid-template-columns: minmax(0, 1fr);
}
.detail-main,
.detail-side {
  display: grid;
  gap: 1.25rem;
}
.detail-panel {
  padding: 1.5rem;
  border: 1px solid var(--color-border);
  border-radius: 1rem;
  background: var(--color-surface);
  box-shadow: 0 12px 30px rgba(126, 78, 38, 0.05);
}
.detail-panel h2 {
  margin: 0 0 1.25rem;
  font-size: 1.2rem;
}
.detail-facts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
  margin: 0;
}
.detail-facts div {
  padding: 0.9rem;
  border-radius: 0.8rem;
  background: var(--color-background-soft);
}
.detail-facts dt {
  color: var(--color-text-muted);
  font-size: 0.8rem;
}
.detail-facts dd {
  margin: 0.25rem 0 0;
}
.detail-primary-actions {
  display: flex;
  gap: 0.75rem;
  margin-top: 1.25rem;
}
.meeting-form {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 0.8rem;
  align-items: end;
}
label {
  display: grid;
  gap: 0.4rem;
  color: var(--color-text-muted);
  font-size: 0.85rem;
}
input,
select,
textarea {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  padding: 0.72rem 0.8rem;
  color: var(--color-text);
  background: var(--color-surface);
  font: inherit;
}
input:focus,
select:focus,
textarea:focus {
  outline: 3px solid color-mix(in srgb, var(--color-primary) 24%, transparent);
  border-color: var(--color-primary);
}
.meeting-list {
  display: grid;
  gap: 0.7rem;
  margin-top: 1rem;
}
.meeting-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
  border-radius: 0.8rem;
  background: var(--color-background-soft);
}
.meeting-item p {
  margin: 0.25rem 0;
}
.meeting-item small {
  color: var(--color-text-muted);
}
.order-timeline {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.order-timeline li {
  display: grid;
  grid-template-columns: 8rem 1fr;
  gap: 1rem;
  padding: 0 0 1.35rem;
}
.order-timeline li:not(:last-child) div {
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 1.35rem;
}
.order-timeline time,
.order-timeline p {
  color: var(--color-text-muted);
}
.order-timeline p {
  margin: 0.25rem 0 0;
}
.compact-panel {
  display: grid;
  gap: 0.85rem;
}
.compact-panel h2,
.compact-panel p {
  margin: 0;
}
.compact-panel p {
  color: var(--color-text-muted);
}
.review-form {
  display: grid;
  gap: 1rem;
  padding-bottom: 1.25rem;
}
.review-form fieldset {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  border: 0;
  padding: 0;
  margin: 0;
}
.review-form legend {
  margin-bottom: 0.5rem;
  color: var(--color-text-muted);
  font-size: 0.85rem;
}
.review-form fieldset button {
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0.48rem 0.75rem;
  color: var(--color-text);
  background: var(--color-surface);
  cursor: pointer;
}
.review-form fieldset button.selected {
  border-color: var(--color-primary);
  color: #7b461f;
  background: #fff0df;
}
.review-list {
  display: grid;
  gap: 0.75rem;
}
.review-list article {
  padding: 1rem;
  border-radius: 0.8rem;
  background: var(--color-background-soft);
}
.review-list article > div {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}
.review-list p {
  margin: 0.6rem 0;
}
.review-list small {
  color: var(--color-text-muted);
}
.detail-action-error {
  border-radius: 0.8rem;
  padding: 0.8rem 1rem;
  color: #8b352f;
  background: #fae9e7;
}
.detail-state {
  padding: 4rem 1rem;
  text-align: center;
}
.detail-skeleton-title {
  width: 40%;
  height: 2.5rem;
  margin-bottom: 2rem;
}
.detail-skeleton-panel {
  width: 100%;
  height: 24rem;
}
@media (max-width: 900px) {
  .order-detail-layout {
    grid-template-columns: 1fr;
  }
  .detail-side {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 680px) {
  .order-detail-heading {
    align-items: start;
    flex-direction: column;
  }
  .detail-facts,
  .detail-side,
  .meeting-form {
    grid-template-columns: 1fr;
  }
  .meeting-item {
    align-items: stretch;
    flex-direction: column;
  }
  .order-timeline li {
    grid-template-columns: 1fr;
    gap: 0.35rem;
  }
}
</style>
