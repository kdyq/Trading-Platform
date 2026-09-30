<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getMarketCampuses, getMarketCategories, searchProducts } from '../api/market'
import type { PublicCampus, PublicCategory, PublicProduct } from '../api/market'
import MarketFilters from '../components/market/MarketFilters.vue'
import ProductCard from '../components/market/ProductCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiDialog from '../components/ui/UiDialog.vue'
import UiField from '../components/ui/UiField.vue'

const route = useRoute()
const router = useRouter()
const categories = ref<PublicCategory[]>([])
const campuses = ref<PublicCampus[]>([])
const products = ref<PublicProduct[]>([])
const total = ref(0)
const nextCursor = ref<string | null>(null)
const cursorHistory = new Map<string, string>()
const loading = ref(false)
const error = ref('')
const filterOpen = ref(false)
const filters = reactive({
  keyword: '',
  category: '',
  campus: '',
  min_price: '',
  max_price: '',
  condition: '',
  negotiable: '',
  status: '',
  sort: 'newest',
})
let debounceTimer: number | undefined
let requestController: AbortController | undefined

const page = computed(() => Math.max(1, Number(route.query.page) || 1))
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / 12)))
const previousDisabled = computed(
  () => page.value <= 1 || (page.value > 2 && !cursorHistory.has(historyKey(page.value - 1))),
)
const conditionLabels: Record<PublicProduct['condition'], string> = {
  new: '全新',
  like_new: '近新',
  good: '使用良好',
  fair: '明显使用',
}

function firstQueryValue(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function syncFilters() {
  for (const key of Object.keys(filters) as (keyof typeof filters)[]) {
    filters[key] = firstQueryValue(route.query[key]) || (key === 'sort' ? 'newest' : '')
  }
}

function cleanQuery() {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries(filters)) {
    if (value && !(key === 'sort' && value === 'newest')) query[key] = value
  }
  return query
}

function historyKey(targetPage: number) {
  return `${JSON.stringify(cleanQuery())}:${targetPage}`
}

async function applyFilters() {
  filterOpen.value = false
  await router.push({ path: '/market', query: cleanQuery() })
}

async function clearFilters() {
  Object.assign(filters, {
    keyword: '',
    category: '',
    campus: '',
    min_price: '',
    max_price: '',
    condition: '',
    negotiable: '',
    status: '',
    sort: 'newest',
  })
  await router.push({ path: '/market' })
}

async function changePage(nextPage: number) {
  if (loading.value) return
  if (nextPage < page.value) {
    if (previousDisabled.value) return
    const query: Record<string, string> = { ...cleanQuery() }
    const previous = cursorHistory.get(historyKey(nextPage))
    if (nextPage > 1 && previous) query.cursor = previous
    query.page = String(nextPage)
    await router.push({ path: '/market', query })
    window.scrollTo({ top: 0, behavior: 'smooth' })
    return
  }
  if (!nextCursor.value) return
  cursorHistory.set(historyKey(nextPage), nextCursor.value)
  await router.push({
    path: '/market',
    query: { ...cleanQuery(), page: String(nextPage), cursor: nextCursor.value },
  })
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function loadOptions() {
  try {
    ;[categories.value, campuses.value] = await Promise.all([
      getMarketCategories(),
      getMarketCampuses(),
    ])
  } catch {
    categories.value = []
    campuses.value = []
  }
}

async function loadProducts() {
  requestController?.abort()
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  error.value = ''
  try {
    const result = await searchProducts(
      {
        ...cleanQuery(),
        page: String(page.value),
        cursor: firstQueryValue(route.query.cursor) || undefined,
      },
      controller.signal,
    )
    products.value = result.items
    total.value = result.total
    nextCursor.value = result.next_cursor
  } catch (caught) {
    if (controller.signal.aborted) return
    error.value = caught instanceof Error ? caught.message : '商品列表暂时无法加载'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

watch(
  () => route.fullPath,
  () => {
    syncFilters()
    void loadProducts()
  },
  { immediate: true },
)

watch(
  () => filters.keyword,
  (value) => {
    if (value === firstQueryValue(route.query.keyword)) return
    window.clearTimeout(debounceTimer)
    debounceTimer = window.setTimeout(() => {
      void router.replace({ path: '/market', query: cleanQuery() })
    }, 320)
  },
)

void loadOptions()

onUnmounted(() => {
  window.clearTimeout(debounceTimer)
  requestController?.abort()
})
</script>

<template>
  <section class="container market-page">
    <header class="market-page-heading">
      <div>
        <p class="eyebrow">公开市场</p>
        <h1>找到今天想带走的好物</h1>
        <p>筛选状态会保存在网址中，刷新或分享后仍能恢复。</p>
      </div>
      <UiButton class="mobile-filter-button" variant="secondary" @click="filterOpen = true">
        筛选商品
      </UiButton>
    </header>

    <div class="market-search-bar">
      <UiField id="market-keyword" label="搜索商品">
        <template #default="{ describedby }">
          <input
            id="market-keyword"
            v-model="filters.keyword"
            type="search"
            :aria-describedby="describedby"
            placeholder="输入商品关键词"
          />
        </template>
      </UiField>
      <UiField id="market-sort" label="排序">
        <template #default="{ describedby }">
          <select
            id="market-sort"
            v-model="filters.sort"
            :aria-describedby="describedby"
            @change="applyFilters"
          >
            <option value="newest">最新发布</option>
            <option value="price_asc">价格从低到高</option>
            <option value="price_desc">价格从高到低</option>
          </select>
        </template>
      </UiField>
    </div>

    <div class="market-results-layout">
      <aside class="desktop-filters" aria-label="商品筛选">
        <MarketFilters
          v-model:category="filters.category"
          v-model:campus="filters.campus"
          v-model:min-price="filters.min_price"
          v-model:max-price="filters.max_price"
          v-model:condition="filters.condition"
          v-model:negotiable="filters.negotiable"
          v-model:status="filters.status"
          :categories="categories"
          :campuses="campuses"
          id-prefix="desktop-filter"
          @apply="applyFilters"
          @clear="clearFilters"
        />
      </aside>

      <main class="market-result-list" aria-live="polite" :aria-busy="loading">
        <p class="result-count">
          共找到 <strong class="num">{{ total }}</strong> 件商品
        </p>
        <div v-if="loading" class="market-product-grid">
          <ProductCard v-for="index in 6" :key="index" state="loading" />
        </div>
        <div v-else-if="error" class="market-empty" role="alert">
          <h2>商品列表暂时不可用</h2>
          <p>{{ error }}</p>
          <UiButton variant="secondary" @click="loadProducts">重新加载</UiButton>
        </div>
        <div v-else-if="products.length" class="market-product-grid">
          <ProductCard
            v-for="item in products"
            :id="item.id"
            :key="item.id"
            :title="item.title"
            :image-url="item.image_url"
            :image-alt="item.image_alt ?? undefined"
            :price="item.price"
            :campus="item.campus_name"
            :department="item.seller_name"
            :condition="conditionLabels[item.condition]"
            :published-at="
              item.published_at ? new Date(item.published_at).toLocaleDateString('zh-CN') : '待上架'
            "
            :state="
              item.status === 'sold'
                ? 'sold'
                : item.status === 'reserved'
                  ? 'reserved'
                  : 'available'
            "
          />
        </div>
        <div v-else class="market-empty">
          <h2>没有找到符合条件的商品</h2>
          <p>试试放宽价格或清空部分筛选条件。</p>
          <UiButton variant="secondary" @click="clearFilters">清空条件</UiButton>
        </div>
        <nav v-if="pageCount > 1" class="pagination" aria-label="商品分页">
          <UiButton
            variant="secondary"
            :disabled="loading || previousDisabled"
            @click="changePage(page - 1)"
          >
            上一页
          </UiButton>
          <span>第 {{ page }} / {{ pageCount }} 页</span>
          <UiButton
            variant="secondary"
            :disabled="loading || !nextCursor"
            @click="changePage(page + 1)"
          >
            下一页
          </UiButton>
        </nav>
      </main>
    </div>

    <UiDialog :open="filterOpen" title="筛选商品" @close="filterOpen = false">
      <MarketFilters
        v-model:category="filters.category"
        v-model:campus="filters.campus"
        v-model:min-price="filters.min_price"
        v-model:max-price="filters.max_price"
        v-model:condition="filters.condition"
        v-model:negotiable="filters.negotiable"
        v-model:status="filters.status"
        :categories="categories"
        :campuses="campuses"
        id-prefix="mobile-filter"
        @apply="applyFilters"
        @clear="clearFilters"
      />
    </UiDialog>
  </section>
</template>
