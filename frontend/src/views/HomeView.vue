<script setup lang="ts">
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { getLatestProducts, getMarketCategories, getMarketSummary } from '../api/market'
import type { PublicCategory, PublicMarketSummary, PublicProduct } from '../api/market'
import ProductCard from '../components/market/ProductCard.vue'
import HealthStatus from '../components/HealthStatus.vue'
import { useAuthStore } from '../stores/auth'

gsap.registerPlugin(ScrollTrigger)

const auth = useAuthStore()
const root = ref<HTMLElement | null>(null)
const corridor = ref<HTMLElement | null>(null)
const corridorTrack = ref<HTMLElement | null>(null)
const categories = ref<PublicCategory[]>([])
const products = ref<PublicProduct[]>([])
const summary = ref<PublicMarketSummary>({
  available_products: 0,
  active_campuses: 0,
  verified_sellers: 0,
})
const loading = ref(true)
const error = ref('')
let motionContext: gsap.Context | undefined
let media: gsap.MatchMedia | undefined

const stats = computed(() => [
  { value: summary.value.available_products, label: '在售好物' },
  { value: summary.value.active_campuses, label: '活跃校区' },
  { value: summary.value.verified_sellers, label: '认证卖家' },
  { value: categories.value.length, label: '市集分类' },
])

function relativeTime(value: string | null) {
  if (!value) return '待上架'
  const elapsed = Date.now() - new Date(value).getTime()
  if (elapsed < 60 * 60 * 1000) return '刚刚'
  if (elapsed < 24 * 60 * 60 * 1000) return `${Math.floor(elapsed / 3_600_000)} 小时前`
  return `${Math.floor(elapsed / 86_400_000)} 天前`
}

async function loadMarket() {
  loading.value = true
  error.value = ''
  try {
    const [categoryResult, productResult, summaryResult] = await Promise.all([
      getMarketCategories(),
      getLatestProducts(8),
      getMarketSummary(),
    ])
    categories.value = categoryResult
    products.value = productResult.items
    summary.value = summaryResult
    await nextTick()
    ScrollTrigger.refresh()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '市集暂时无法加载'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadMarket()
  if (!root.value) return
  motionContext = gsap.context(() => {
    media = gsap.matchMedia()
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const timeline = gsap.timeline({ defaults: { ease: 'power2.out' } })
      timeline
        .from('.market-hero-copy > *', { autoAlpha: 0, y: 24, duration: 0.55, stagger: 0.07 })
        .from('.hero-market-ticket', { autoAlpha: 0, y: 24, rotation: 2, duration: 0.7 }, '<0.12')
        .from('.market-stat', { autoAlpha: 0, y: 16, duration: 0.35, stagger: 0.06 }, '<0.2')
      gsap.to('.hero-market-ticket', {
        y: -8,
        rotation: -0.8,
        duration: 2.6,
        repeat: -1,
        yoyo: true,
        ease: 'sine.inOut',
      })
      gsap.to('.hero-trust-seal', { rotation: 360, duration: 26, repeat: -1, ease: 'none' })
      gsap.from('.market-stat-value', {
        textContent: 0,
        duration: 1.6,
        snap: { textContent: 1 },
        stagger: 0.05,
        ease: 'power1.out',
      })
      gsap.from('.market-reveal', {
        autoAlpha: 0,
        y: 24,
        duration: 0.5,
        stagger: 0.06,
        scrollTrigger: { trigger: '.latest-market', start: 'top 78%', once: true },
      })
    })
    media.add('(min-width: 1024px) and (prefers-reduced-motion: no-preference)', () => {
      if (!corridor.value || !corridorTrack.value) return
      const distance = () => Math.max(0, corridorTrack.value!.scrollWidth - window.innerWidth)
      gsap.to(corridorTrack.value, {
        x: () => -distance(),
        ease: 'none',
        scrollTrigger: {
          trigger: corridor.value,
          start: 'top top',
          end: () => `+=${distance()}`,
          pin: true,
          scrub: 1,
          invalidateOnRefresh: true,
        },
      })
    })
  }, root.value)
})

onUnmounted(() => {
  media?.revert()
  motionContext?.revert()
})
</script>

<template>
  <div ref="root" class="market-home">
    <section class="container market-hero">
      <div class="market-hero-copy">
        <p class="eyebrow">校园里的周末市集</p>
        <h1>闲置好物，换个主人继续发光</h1>
        <p class="hero-description">从同学手里发现好物，也让自己的闲置重新派上用场。</p>
        <div class="hero-actions">
          <RouterLink class="button button-primary" to="/market">开始逛逛</RouterLink>
          <RouterLink class="button button-ghost" :to="auth.user ? '/my-products' : '/login'">
            {{ auth.user ? '我的发布' : '登录后发布' }}
          </RouterLink>
        </div>
        <HealthStatus />
      </div>
      <article class="hero-market-ticket">
        <span class="ticket-tape" aria-hidden="true" />
        <span class="hero-trust-seal" aria-label="校园身份认证">校园<br />认证</span>
        <template v-if="products[0]">
          <p>今日新到</p>
          <h2>{{ products[0].title }}</h2>
          <strong class="num">¥{{ products[0].price }}</strong>
          <span>{{ products[0].campus_name }}</span>
        </template>
        <template v-else>
          <p>摊位等你来</p>
          <h2>等待第一件校园好物</h2>
          <span>当前没有公开商品，发布功能将在下一阶段开放。</span>
        </template>
      </article>
    </section>

    <section class="market-stats" aria-label="真实市集数据">
      <div class="container market-stat-grid">
        <div v-for="item in stats" :key="item.label" class="market-stat">
          <strong class="num market-stat-value">{{ item.value }}</strong>
          <span>{{ item.label }}</span>
        </div>
      </div>
    </section>

    <div class="market-marquee" aria-label="平台特点">
      <div class="market-marquee-track">
        <span>校园认证</span><span>当面验货</span><span>闲置循环</span><span>公开透明</span>
        <span aria-hidden="true">校园认证</span><span aria-hidden="true">当面验货</span>
        <span aria-hidden="true">闲置循环</span><span aria-hidden="true">公开透明</span>
      </div>
    </div>

    <section class="container market-section category-market" aria-labelledby="category-title">
      <div class="section-heading">
        <h2 id="category-title">从熟悉的校园分类开始</h2>
        <p>分类来自真实基础数据。进入列表后还可以继续按校区和价格筛选。</p>
      </div>
      <div v-if="loading" class="category-grid" aria-label="分类加载中">
        <span v-for="index in 8" :key="index" class="ui-skeleton category-skeleton" />
      </div>
      <div v-else-if="categories.length" class="category-grid">
        <RouterLink
          v-for="(category, index) in categories"
          :key="category.id"
          class="category-link"
          :to="{ path: '/market', query: { category: category.code } }"
        >
          <span class="num">{{ String(index + 1).padStart(2, '0') }}</span>
          <strong>{{ category.name }}</strong>
          <small>查看好物</small>
        </RouterLink>
      </div>
      <p v-else class="market-inline-empty">分类数据尚未准备好。</p>
    </section>

    <section class="container market-section latest-market" aria-labelledby="latest-title">
      <div class="section-heading market-reveal">
        <h2 id="latest-title">刚摆上摊的好物</h2>
        <p>只展示真实公开商品；没有商品时保留诚实空态。</p>
      </div>
      <div v-if="loading" class="product-grid">
        <ProductCard v-for="index in 4" :key="index" state="loading" />
      </div>
      <div v-else-if="error" class="market-empty market-reveal" role="alert">
        <h3>市集暂时没有连上</h3>
        <p>{{ error }}</p>
        <button class="button button-ghost" type="button" @click="loadMarket">重新加载</button>
      </div>
      <div v-else-if="products.length" class="product-grid">
        <ProductCard
          v-for="product in products"
          :id="product.id"
          :key="product.id"
          class="market-reveal"
          :title="product.title"
          :price="product.price"
          :campus="product.campus_name"
          :department="product.seller_name"
          :published-at="relativeTime(product.published_at)"
          :image-url="product.image_url"
          :image-alt="product.image_alt ?? product.title"
        />
      </div>
      <div v-else class="market-empty market-reveal">
        <h3>第一件好物还没摆上来</h3>
        <p>公共市场目前没有在售商品。你可以先看看分类，商品发布将在下一阶段开放。</p>
        <RouterLink class="button button-ghost" to="/market">查看市场空态</RouterLink>
      </div>
    </section>

    <section ref="corridor" class="market-corridor" aria-labelledby="corridor-title">
      <div ref="corridorTrack" class="market-corridor-track">
        <article class="corridor-intro">
          <h2 id="corridor-title">一条路逛完核心页面</h2>
          <p>桌面端随页面固定横移，移动端使用原生横向滚动。</p>
        </article>
        <RouterLink class="corridor-panel corridor-panel-orange" to="/market">
          <span>公共市场</span><strong>搜索、分类和筛选</strong>
        </RouterLink>
        <RouterLink class="corridor-panel corridor-panel-green" to="/campus-verification">
          <span>身份信任</span><strong>校园邮箱与人工申诉</strong>
        </RouterLink>
        <RouterLink class="corridor-panel corridor-panel-paper" to="/account">
          <span>个人中心</span><strong>资料、会话和安全状态</strong>
        </RouterLink>
      </div>
    </section>

    <section class="container market-section trust-market" aria-labelledby="trust-title">
      <div class="section-heading"><h2 id="trust-title">把可信交易写进每一步</h2></div>
      <div class="trust-market-grid">
        <article>
          <strong>校园认证</strong>
          <p>登录邮箱与校园身份分离，公开页面不泄露邮箱。</p>
        </article>
        <article>
          <strong>当面验货</strong>
          <p>交易在校内完成，见面前先确认商品状态和约定。</p>
        </article>
        <article>
          <strong>状态透明</strong>
          <p>已售、预留和不可公开商品使用明确状态，不制造库存。</p>
        </article>
        <article>
          <strong>信息克制</strong>
          <p>只展示完成判断所需的校区、卖家和商品信息。</p>
        </article>
      </div>
    </section>
  </div>
</template>
