<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '../api/client'
import { getFavorites, type PublicProduct } from '../api/market'
import ProductCard from '../components/market/ProductCard.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const products = ref<PublicProduct[]>([])
const loading = ref(true)
const errorMessage = ref('')
const conditionLabels = {
  new: '全新',
  like_new: '近新',
  good: '使用良好',
  fair: '明显使用',
}

onMounted(async () => {
  if (!auth.accessToken) {
    await router.replace('/login')
    return
  }
  try {
    products.value = (await getFavorites(auth.accessToken)).items
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '收藏列表加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="container seller-products-page">
    <header class="seller-products-heading">
      <div>
        <p class="eyebrow">个人中心</p>
        <h1>我的收藏</h1>
      </div>
      <RouterLink class="button button-secondary" to="/market">继续逛好物</RouterLink>
    </header>
    <p v-if="errorMessage" class="form-message form-message-error">{{ errorMessage }}</p>
    <p v-if="loading">正在加载收藏…</p>
    <div v-else-if="!products.length" class="empty-state">
      <h2>还没有收藏</h2>
      <p>看到心仪的校园好物时，可以先收藏起来。</p>
      <RouterLink class="button button-primary" to="/market">去公开市场</RouterLink>
    </div>
    <div v-else class="product-grid">
      <ProductCard
        v-for="item in products"
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
        :status="item.status"
        :image-url="item.image_url ?? undefined"
        :image-alt="item.image_alt ?? undefined"
      />
    </div>
  </section>
</template>
