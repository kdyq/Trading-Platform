<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { listOrders } from '../api/orders'
import type { OrderStatus, OrderSummary } from '../api/orders'
import UiButton from '../components/ui/UiButton.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const role = ref<'buying' | 'selling'>('buying')
const status = ref<OrderStatus | ''>('')
const orders = ref<OrderSummary[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(true)
const loadingMore = ref(false)
const error = ref('')

const statusOptions: Array<{ value: OrderStatus | ''; label: string }> = [
  { value: '', label: '全部' },
  { value: 'pending_seller_confirmation', label: '待卖家确认' },
  { value: 'accepted', label: '待预约' },
  { value: 'scheduled', label: '待面交' },
  { value: 'seller_delivered', label: '待收货' },
  { value: 'completed', label: '已完成' },
  { value: 'disputed', label: '争议中' },
  { value: 'cancelled', label: '已取消' },
  { value: 'expired', label: '已过期' },
]

const statusLabels: Record<OrderStatus, string> = Object.fromEntries(
  statusOptions.filter((item) => item.value).map((item) => [item.value, item.label]),
) as Record<OrderStatus, string>

const emptyCopy = computed(() =>
  role.value === 'buying' ? '还没有符合条件的买入订单' : '还没有符合条件的卖出订单',
)

function formatDate(value: string | null) {
  if (!value) return '待协商'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

async function load(reset = true) {
  if (!auth.accessToken) {
    await router.replace({ path: '/login', query: { next: '/orders' } })
    return
  }
  if (reset) loading.value = true
  else loadingMore.value = true
  error.value = ''
  try {
    const result = await listOrders(
      auth.accessToken,
      role.value,
      status.value || undefined,
      reset ? undefined : nextCursor.value || undefined,
    )
    orders.value = reset ? result.items : [...orders.value, ...result.items]
    nextCursor.value = result.next_cursor
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '订单暂时无法加载'
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

watch([role, status], () => load())
onMounted(() => load())
</script>

<template>
  <section class="container orders-page" aria-live="polite">
    <header class="orders-heading">
      <div>
        <p class="eyebrow">交易进度</p>
        <h1>我的订单</h1>
        <p>预约、面交和评价都在这里完成。平台不经手交易资金。</p>
      </div>
      <RouterLink class="button button-ghost" to="/market">继续逛好物</RouterLink>
    </header>

    <div class="order-toolbar">
      <div class="order-role-switch" aria-label="订单角色">
        <button :class="{ active: role === 'buying' }" type="button" @click="role = 'buying'">
          我买到的
        </button>
        <button :class="{ active: role === 'selling' }" type="button" @click="role = 'selling'">
          我卖出的
        </button>
      </div>
      <label class="order-filter">
        <span>状态</span>
        <select v-model="status">
          <option v-for="option in statusOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>
    </div>

    <div v-if="loading" class="order-grid" aria-label="正在加载订单">
      <article v-for="index in 3" :key="index" class="order-card order-card-loading">
        <div class="ui-skeleton order-image" />
        <div class="order-copy">
          <div class="ui-skeleton order-line-wide" />
          <div class="ui-skeleton order-line-short" />
        </div>
      </article>
    </div>

    <div v-else-if="error" class="order-state" role="alert">
      <h2>订单暂时无法加载</h2>
      <p>{{ error }}</p>
      <UiButton variant="secondary" @click="load()">重新加载</UiButton>
    </div>

    <div v-else-if="orders.length === 0" class="order-state">
      <h2>{{ emptyCopy }}</h2>
      <p>发起交易或调整筛选后，相关订单会显示在这里。</p>
      <RouterLink class="button button-primary" to="/market">浏览商品</RouterLink>
    </div>

    <div v-else class="order-grid">
      <RouterLink
        v-for="order in orders"
        :key="order.id"
        class="order-card"
        :to="`/orders/${order.id}`"
      >
        <img
          v-if="order.image_url"
          class="order-image"
          :src="order.image_url"
          :alt="order.product_title"
        />
        <div v-else class="order-image order-image-fallback" aria-hidden="true">
          {{ order.product_title.slice(0, 1) }}
        </div>
        <div class="order-copy">
          <div class="order-card-topline">
            <span class="order-status" :data-status="order.status">
              {{ statusLabels[order.status] }}
            </span>
            <strong class="num">¥{{ order.amount }}</strong>
          </div>
          <h2>{{ order.product_title }}</h2>
          <p>{{ order.counterparty_name }} · {{ order.campus_name }}</p>
          <dl>
            <div>
              <dt>面交时间</dt>
              <dd>{{ formatDate(order.scheduled_for) }}</dd>
            </div>
            <div>
              <dt>付款方式</dt>
              <dd>线下当面支付</dd>
            </div>
            <div>
              <dt>最近更新</dt>
              <dd>{{ formatDate(order.updated_at) }}</dd>
            </div>
          </dl>
          <span class="order-detail-link">查看订单详情</span>
        </div>
      </RouterLink>
    </div>

    <div v-if="nextCursor" class="order-load-more">
      <UiButton variant="secondary" :disabled="loadingMore" @click="load(false)">
        {{ loadingMore ? '正在加载…' : '加载更多' }}
      </UiButton>
    </div>
  </section>
</template>

<style scoped>
.orders-page {
  padding-block: 3.5rem 6rem;
}
.orders-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 2rem;
  margin-bottom: 2rem;
}
.orders-heading h1 {
  margin: 0.35rem 0 0.65rem;
  font-size: clamp(2rem, 5vw, 3.4rem);
}
.orders-heading p:last-child {
  margin: 0;
  color: var(--color-text-muted);
}
.order-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.order-role-switch {
  display: inline-flex;
  padding: 0.3rem;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
}
.order-role-switch button {
  border: 0;
  border-radius: 999px;
  padding: 0.65rem 1.1rem;
  color: var(--color-text-muted);
  background: transparent;
  cursor: pointer;
}
.order-role-switch button.active {
  color: white;
  background: var(--color-primary);
}
.order-filter {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  color: var(--color-text-muted);
}
.order-filter select {
  min-width: 9rem;
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  padding: 0.68rem 0.8rem;
  color: var(--color-text);
  background: var(--color-surface);
}
.order-grid {
  display: grid;
  gap: 1rem;
}
.order-card {
  display: grid;
  grid-template-columns: 9rem 1fr;
  gap: 1.25rem;
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: 1rem;
  color: inherit;
  background: var(--color-surface);
  box-shadow: 0 12px 30px rgba(126, 78, 38, 0.06);
  text-decoration: none;
  transition:
    transform 0.16s ease,
    border-color 0.16s ease;
}
.order-card:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--color-primary) 48%, var(--color-border));
}
.order-card:active {
  transform: translateY(0);
}
.order-image {
  width: 9rem;
  height: 9rem;
  border-radius: 0.8rem;
  object-fit: cover;
  background: var(--color-background-soft);
}
.order-image-fallback {
  display: grid;
  place-items: center;
  color: var(--color-primary);
  font-size: 2rem;
  font-weight: 800;
}
.order-copy {
  min-width: 0;
}
.order-card-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.order-status {
  border-radius: 999px;
  padding: 0.35rem 0.65rem;
  color: #7b461f;
  background: #fff0df;
  font-size: 0.82rem;
  font-weight: 700;
}
.order-status[data-status='completed'] {
  color: #2e6553;
  background: #e6f4ed;
}
.order-status[data-status='disputed'] {
  color: #8b352f;
  background: #fae9e7;
}
.order-status[data-status='cancelled'],
.order-status[data-status='expired'] {
  color: var(--color-text-muted);
  background: var(--color-background-soft);
}
.order-copy h2 {
  margin: 0.75rem 0 0.35rem;
  font-size: 1.25rem;
}
.order-copy > p {
  margin: 0;
  color: var(--color-text-muted);
}
.order-copy dl {
  display: flex;
  gap: 2rem;
  margin: 1rem 0;
}
.order-copy dl div {
  display: grid;
  gap: 0.2rem;
}
.order-copy dt {
  color: var(--color-text-muted);
  font-size: 0.78rem;
}
.order-copy dd {
  margin: 0;
  font-size: 0.92rem;
}
.order-detail-link {
  color: var(--color-primary);
  font-weight: 700;
}
.order-state {
  padding: 4.5rem 1.5rem;
  border: 1px dashed var(--color-border);
  border-radius: 1rem;
  text-align: center;
  background: var(--color-surface);
}
.order-state h2 {
  margin-top: 0;
}
.order-state p {
  color: var(--color-text-muted);
}
.order-load-more {
  display: flex;
  justify-content: center;
  margin-top: 1.5rem;
}
.order-card-loading {
  pointer-events: none;
}
.order-line-wide {
  width: 65%;
  height: 1.3rem;
  margin: 0.5rem 0 1rem;
}
.order-line-short {
  width: 38%;
  height: 1rem;
}
@media (max-width: 700px) {
  .orders-page {
    padding-block: 2rem 4rem;
  }
  .orders-heading,
  .order-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .order-role-switch {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .order-card {
    grid-template-columns: 5.5rem 1fr;
    gap: 0.9rem;
  }
  .order-image {
    width: 5.5rem;
    height: 5.5rem;
  }
  .order-copy dl {
    flex-direction: column;
    gap: 0.55rem;
  }
}
@media (prefers-reduced-motion: reduce) {
  .order-card {
    transition: none;
  }
}
</style>
