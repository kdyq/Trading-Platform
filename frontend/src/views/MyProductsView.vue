<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '../api/client'
import {
  listSellerProducts,
  getSellerProductImage,
  transitionSellerProduct,
  type SellerProduct,
} from '../api/sellerProducts'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const products = ref<SellerProduct[]>([])
const loading = ref(true)
const errorMessage = ref('')
const imagePreviews = ref<Record<string, string>>({})

const statusLabels: Record<string, string> = {
  draft: '草稿',
  pending_review: '待审核',
  on_sale: '在售',
  reserved: '已预订',
  sold: '已售出',
  rejected: '未通过',
  hidden: '已下架',
}

async function act(product: SellerProduct, action: 'withdraw' | 'hide' | 'sold') {
  if (!auth.accessToken) return
  try {
    const updated = await transitionSellerProduct(
      auth.accessToken,
      product.id,
      action,
      product.version,
    )
    products.value = products.value.map((item) => (item.id === updated.id ? updated : item))
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '操作失败'
  }
}

onMounted(async () => {
  if (!auth.accessToken) {
    await router.replace('/login')
    return
  }
  try {
    products.value = (await listSellerProducts(auth.accessToken)).items
    for (const product of products.value) {
      const image = product.images[0]
      if (!image) continue
      try {
        imagePreviews.value[product.id] = URL.createObjectURL(
          await getSellerProductImage(auth.accessToken, image.thumbnail_url),
        )
      } catch {
        // Keep the safe placeholder when a private preview is temporarily unavailable.
      }
    }
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '发布记录加载失败'
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
        <h1>我的发布</h1>
      </div>
      <RouterLink class="button button-primary" to="/sell">发布闲置</RouterLink>
    </header>
    <p v-if="errorMessage" class="form-message form-message-error">{{ errorMessage }}</p>
    <p v-if="loading">正在加载发布记录…</p>
    <div v-else-if="!products.length" class="empty-state">
      <h2>还没有商品草稿</h2>
      <p>从一件不再使用的好物开始吧。</p>
      <RouterLink class="button button-primary" to="/sell">创建草稿</RouterLink>
    </div>
    <div v-else class="seller-product-list">
      <article v-for="product in products" :key="product.id" class="seller-product-row">
        <img
          v-if="imagePreviews[product.id]"
          :src="imagePreviews[product.id]"
          :alt="product.title"
        />
        <div v-else class="seller-product-placeholder">等待图片</div>
        <div>
          <span class="status-pill">{{ statusLabels[product.status] ?? product.status }}</span>
          <h2>{{ product.title || '未命名草稿' }}</h2>
          <strong>¥{{ product.price }}</strong>
        </div>
        <div class="seller-product-actions">
          <RouterLink
            v-if="['draft', 'rejected', 'hidden'].includes(product.status)"
            class="button button-secondary"
            :to="`/sell/${product.id}`"
          >
            继续编辑
          </RouterLink>
          <button
            v-if="product.status === 'pending_review'"
            class="button button-ghost"
            type="button"
            @click="act(product, 'withdraw')"
          >
            撤回审核
          </button>
          <button
            v-if="['on_sale', 'reserved'].includes(product.status)"
            class="button button-ghost"
            type="button"
            @click="act(product, 'hide')"
          >
            下架
          </button>
          <button
            v-if="['on_sale', 'reserved'].includes(product.status)"
            class="button button-primary"
            type="button"
            @click="act(product, 'sold')"
          >
            标记售出
          </button>
        </div>
      </article>
    </div>
  </section>
</template>
