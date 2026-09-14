<script setup lang="ts">
import UiChip from '../ui/UiChip.vue'

export type ProductCardState = 'available' | 'sold' | 'pending' | 'loading'

withDefaults(
  defineProps<{
    id?: string
    title?: string
    price?: string
    campus?: string
    department?: string
    condition?: string
    publishedAt?: string
    imageUrl?: string | null
    imageAlt?: string
    state?: ProductCardState
    favorite?: boolean
  }>(),
  {
    id: '',
    title: '',
    price: '',
    campus: '',
    department: '',
    condition: '',
    publishedAt: '',
    imageUrl: null,
    imageAlt: '',
    state: 'available',
    favorite: false,
  },
)
</script>

<template>
  <article v-if="state === 'loading'" class="product-card" aria-hidden="true">
    <div class="ui-skeleton product-card-media" />
    <div class="product-card-body">
      <div class="ui-skeleton skeleton-line skeleton-line-short" />
      <div class="ui-skeleton skeleton-line" />
      <div class="ui-skeleton skeleton-line skeleton-line-medium" />
    </div>
  </article>
  <article v-else class="product-card" :data-state="state">
    <RouterLink class="product-card-link" :to="id ? `/products/${id}` : '/market'">
      <div class="product-card-media">
        <img
          v-if="imageUrl"
          :src="imageUrl"
          :alt="imageAlt || title"
          width="640"
          height="480"
          loading="lazy"
        />
        <span v-else class="product-image-fallback">暂无商品图片</span>
        <span v-if="state === 'sold'" class="product-state-label">已售出</span>
        <span v-else-if="state === 'pending'" class="product-state-label">待审核</span>
        <span v-if="favorite" class="product-favorite-label">已收藏</span>
      </div>
      <div class="product-card-body">
        <div class="product-card-heading">
          <h3>{{ title }}</h3>
          <strong class="num product-price">¥{{ price }}</strong>
        </div>
        <div class="product-card-chips">
          <UiChip v-if="condition">{{ condition }}</UiChip>
          <UiChip v-if="campus" tone="trust">{{ campus }}</UiChip>
        </div>
        <p class="product-card-meta">
          <span>{{ department || '学院信息待补充' }}</span>
          <time>{{ publishedAt }}</time>
        </p>
      </div>
    </RouterLink>
  </article>
</template>
