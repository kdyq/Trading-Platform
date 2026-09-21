<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { createConversation } from '../api/chat'
import { ApiError } from '../api/client'
import { addFavorite, getFavoriteStatus, getProductDetail, removeFavorite } from '../api/market'
import type { PublicProductDetail } from '../api/market'
import ProductCard from '../components/market/ProductCard.vue'
import ProductGallery from '../components/market/ProductGallery.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiChip from '../components/ui/UiChip.vue'
import UiDialog from '../components/ui/UiDialog.vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const product = ref<PublicProductDetail | null>(null)
const loading = ref(true)
const notFound = ref(false)
const error = ref('')
const favorited = ref(false)
const favoriteCount = ref(0)
const favoriteBusy = ref(false)
const contactBusy = ref(false)
const gate = ref<'login' | 'verification' | 'later' | null>(null)
const gateIntent = ref<'action' | 'report'>('action')
let controller: AbortController | undefined
const originalTitle = document.title
const originalDescription = document.querySelector<HTMLMetaElement>(
  'meta[name="description"]',
)?.content
let createdDescriptionMeta = false

const conditionLabels: Record<PublicProductDetail['condition'], string> = {
  new: '全新',
  like_new: '近新',
  good: '使用良好',
  fair: '明显使用',
}
const statusLabels: Record<PublicProductDetail['status'], string> = {
  on_sale: '在售',
  reserved: '已预订',
  sold: '已售出',
}
const galleryImages = computed(() => {
  const current = product.value
  if (!current) return []
  return current.images.map((image) => ({
    url: image.url,
    alt: image.alt_text || current.title,
  }))
})

const isOwner = computed(() => auth.user?.id === product.value?.seller.id)
const actionDisabled = computed(
  () => !product.value || isOwner.value || product.value.status === 'sold',
)
const favoriteDisabled = computed(
  () => !product.value || isOwner.value || product.value.status === 'sold',
)
const disabledReason = computed(() => {
  if (isOwner.value) return '这是你发布的商品'
  if (product.value?.status === 'sold') return '商品已售出'
  return ''
})
const gateTitle = computed(() => {
  if (gate.value === 'login') return '登录后继续'
  if (gate.value === 'verification') return '完成校园认证'
  return '功能开放准备中'
})

function setMeta(title: string, description: string) {
  document.title = title
  let meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
  if (!meta) {
    meta = document.createElement('meta')
    meta.name = 'description'
    document.head.append(meta)
    createdDescriptionMeta = true
  }
  meta.content = description
}

function openGate(intent: 'action' | 'report' = 'action') {
  if (intent === 'action' && actionDisabled.value) return
  gateIntent.value = intent
  if (!auth.user) gate.value = 'login'
  else if (intent === 'action' && auth.user.campus_verification_status !== 'verified')
    gate.value = 'verification'
  else gate.value = 'later'
}

async function contactSeller() {
  if (actionDisabled.value || !product.value) return
  if (!auth.user) {
    gate.value = 'login'
    return
  }
  if (auth.user.campus_verification_status !== 'verified') {
    gate.value = 'verification'
    return
  }
  if (!auth.accessToken || contactBusy.value) return
  contactBusy.value = true
  try {
    const conversation = await createConversation(auth.accessToken, product.value.id)
    await router.push(`/messages/${conversation.id}`)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '暂时无法联系卖家'
  } finally {
    contactBusy.value = false
  }
}

async function toggleFavorite() {
  if (favoriteDisabled.value || !product.value) return
  if (!auth.user) {
    gate.value = 'login'
    return
  }
  if (auth.user.campus_verification_status !== 'verified') {
    gate.value = 'verification'
    return
  }
  if (!auth.accessToken || favoriteBusy.value) return
  favoriteBusy.value = true
  try {
    if (favorited.value) {
      await removeFavorite(auth.accessToken, product.value.id)
      favorited.value = false
      favoriteCount.value = Math.max(0, favoriteCount.value - 1)
    } else {
      const status = await addFavorite(auth.accessToken, product.value.id)
      favorited.value = status.favorited
      favoriteCount.value = status.favorite_count
    }
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '收藏操作失败'
  } finally {
    favoriteBusy.value = false
  }
}

async function loadProduct() {
  controller?.abort()
  const requestController = new AbortController()
  controller = requestController
  loading.value = true
  notFound.value = false
  error.value = ''
  product.value = null
  setMeta('商品详情｜拾光集市', '浏览拾光集市公开、可信的校园二手商品信息。')
  try {
    const loadedProduct = await getProductDetail(String(route.params.id), requestController.signal)
    if (controller !== requestController) return
    product.value = loadedProduct
    favoriteCount.value = loadedProduct.favorite_count
    favorited.value = false
    if (auth.accessToken && auth.user?.id !== loadedProduct.seller.id) {
      try {
        const status = await getFavoriteStatus(auth.accessToken, loadedProduct.id)
        if (controller !== requestController) return
        favorited.value = status.favorited
        favoriteCount.value = status.favorite_count
      } catch {
        // Detail remains usable when the optional personal favorite status is unavailable.
      }
    }
    setMeta(
      `${product.value.title}｜拾光集市`,
      `${product.value.school_name}${product.value.campus_name}的${product.value.category_name}二手商品，¥${product.value.price}。`,
    )
  } catch (caught) {
    if (requestController.signal.aborted || controller !== requestController) return
    if (caught instanceof ApiError && caught.status === 404) {
      notFound.value = true
      setMeta('商品不可见｜拾光集市', '该商品不存在或当前不可公开浏览。')
    } else {
      error.value = caught instanceof Error ? caught.message : '商品详情暂时无法加载'
    }
  } finally {
    if (controller === requestController && !requestController.signal.aborted) loading.value = false
  }
}

watch(() => route.params.id, loadProduct, { immediate: true })

onUnmounted(() => {
  controller?.abort()
  document.title = originalTitle
  const meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
  if (meta && originalDescription !== undefined) meta.content = originalDescription
  else if (meta && createdDescriptionMeta) meta.remove()
})
</script>

<template>
  <section class="container product-detail-page" aria-live="polite" :aria-busy="loading">
    <div v-if="loading" class="product-detail-loading">
      <div class="ui-skeleton product-detail-image-skeleton" />
      <div class="ui-skeleton product-detail-copy-skeleton" />
    </div>

    <div v-else-if="notFound" class="market-empty product-detail-state">
      <p class="eyebrow">商品不可见</p>
      <h1>这件商品暂时不在摊位上</h1>
      <p>它可能不存在、已隐藏，或尚未对公共市场开放。</p>
      <RouterLink class="button button-ghost" to="/market">返回公开市场</RouterLink>
    </div>

    <div v-else-if="error" class="market-empty product-detail-state" role="alert">
      <h1>商品详情暂时无法加载</h1>
      <p>{{ error }}</p>
      <UiButton variant="secondary" @click="loadProduct">重新加载</UiButton>
    </div>

    <template v-else-if="product">
      <nav class="product-breadcrumb" aria-label="面包屑">
        <RouterLink to="/market">公开市场</RouterLink>
        <span aria-hidden="true">/</span>
        <RouterLink :to="`/market?category=${product.category_code}`">
          {{ product.category_name }}
        </RouterLink>
      </nav>

      <div class="product-detail-hero">
        <ProductGallery :title="product.title" :images="galleryImages" />

        <article class="product-purchase-card">
          <div class="product-detail-chips">
            <UiChip :tone="product.status === 'on_sale' ? 'trust' : 'warning'">
              {{ statusLabels[product.status] }}
            </UiChip>
            <UiChip>{{ conditionLabels[product.condition] }}</UiChip>
            <UiChip v-if="product.is_negotiable">可议价</UiChip>
          </div>
          <h1>{{ product.title }}</h1>
          <strong class="num product-detail-price">¥{{ product.price }}</strong>
          <p class="product-location">{{ product.school_name }} · {{ product.campus_name }}</p>

          <div class="product-main-actions">
            <UiButton
              variant="secondary"
              :disabled="favoriteDisabled || favoriteBusy"
              @click="toggleFavorite"
            >
              {{ favorited ? '取消收藏' : '收藏' }} · {{ favoriteCount }}
            </UiButton>
            <UiButton :disabled="actionDisabled || contactBusy" @click="contactSeller">
              {{ contactBusy ? '正在建立会话…' : '联系卖家 / 发起交易' }}
            </UiButton>
          </div>
          <p v-if="disabledReason" class="action-disabled-reason">{{ disabledReason }}</p>

          <dl class="product-facts">
            <div>
              <dt>发布时间</dt>
              <dd>
                {{
                  product.published_at
                    ? new Date(product.published_at).toLocaleString('zh-CN')
                    : '待上架'
                }}
              </dd>
            </div>
            <div>
              <dt>浏览</dt>
              <dd class="num">{{ product.view_count }} 次</dd>
            </div>
            <div>
              <dt>分类</dt>
              <dd>{{ product.category_name }}</dd>
            </div>
          </dl>
        </article>
      </div>

      <div class="product-detail-content">
        <article class="product-description-card">
          <p class="eyebrow">物品说明</p>
          <h2>关于这件好物</h2>
          <p class="product-description">{{ product.description }}</p>
          <button class="text-button report-entry" type="button" @click="openGate('report')">
            举报商品
          </button>
        </article>

        <aside class="seller-trust-card">
          <p class="eyebrow">卖家与信用</p>
          <h2>{{ product.seller.display_name }}</h2>
          <p>{{ product.school_name }} · {{ product.campus_name }}</p>
          <UiChip v-if="product.seller.campus_verified" tone="trust">校园身份已认证</UiChip>
          <UiChip v-else tone="warning">校园身份待核验</UiChip>
          <div class="seller-credit-grid">
            <div>
              <strong class="num">
                {{ product.seller.completed_orders }}
              </strong>
              <span>完成交易</span>
            </div>
            <div>
              <strong class="num">
                {{ product.seller.review_count }}
              </strong>
              <span>收到评价</span>
            </div>
            <div>
              <strong class="num">
                {{ product.seller.average_rating ?? '—' }}
              </strong>
              <span>平均评分</span>
            </div>
          </div>
        </aside>
      </div>

      <section class="similar-products" aria-labelledby="similar-products-title">
        <header>
          <p class="eyebrow">同类摊位</p>
          <h2 id="similar-products-title">你可能还会喜欢</h2>
        </header>
        <div v-if="product.similar_products.length" class="product-grid">
          <ProductCard
            v-for="item in product.similar_products"
            :id="item.id"
            :key="item.id"
            :title="item.title"
            :price="item.price"
            :campus="item.campus_name"
            :department="item.seller_name"
            :condition="conditionLabels[item.condition]"
            :published-at="
              item.published_at ? new Date(item.published_at).toLocaleDateString('zh-CN') : '待上架'
            "
            :state="item.status === 'reserved' ? 'reserved' : 'available'"
          />
        </div>
        <p v-else class="market-inline-empty">这个分类暂时没有其他公开商品。</p>
      </section>
    </template>

    <UiDialog :open="gate !== null" :title="gateTitle" @close="gate = null">
      <div class="gate-dialog-content">
        <template v-if="gate === 'login'">
          <p>登录后才能收藏、联系卖家或发起校内交易。</p>
          <RouterLink class="button button-primary" :to="`/login?redirect=${route.fullPath}`">
            去登录
          </RouterLink>
        </template>
        <template v-else-if="gate === 'verification'">
          <p>完成校园身份认证后，才能联系校内卖家并发起交易。</p>
          <RouterLink class="button button-primary" to="/campus-verification">去认证</RouterLink>
        </template>
        <template v-else>
          <p v-if="gateIntent === 'report'">
            举报入口已保留，提交与治理处理将在后续阶段开放，本阶段不会伪造举报结果。
          </p>
          <p v-else>身份门禁已通过。联系与交易写入将在后续交易阶段开放，本阶段不会伪造提交结果。</p>
          <UiButton variant="secondary" @click="gate = null">知道了</UiButton>
        </template>
      </div>
    </UiDialog>
  </section>
</template>
