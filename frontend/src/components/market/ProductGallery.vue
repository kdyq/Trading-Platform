<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { API_BASE_URL } from '../../api/client'

export interface GalleryImage {
  url: string | null
  alt: string
}

const props = defineProps<{ images: GalleryImage[]; title: string }>()
const selected = ref(0)
const failed = ref(new Set<number>())
const safeImages = computed(() =>
  props.images.length ? props.images : [{ url: null, alt: `${props.title} 暂无图片` }],
)

watch(
  () => props.images,
  () => {
    selected.value = 0
    failed.value = new Set()
  },
)

function selectOffset(offset: number) {
  selected.value = (selected.value + offset + safeImages.value.length) % safeImages.value.length
}

function markFailed(index: number) {
  failed.value = new Set(failed.value).add(index)
}
</script>

<template>
  <section class="product-gallery" aria-label="商品图片">
    <div
      class="product-gallery-stage"
      tabindex="0"
      aria-label="商品图片画廊，使用左右方向键切换"
      @keydown.left.prevent="selectOffset(-1)"
      @keydown.right.prevent="selectOffset(1)"
    >
      <img
        v-if="safeImages[selected]?.url && !failed.has(selected)"
        :src="
          safeImages[selected]?.url?.startsWith('/')
            ? `${API_BASE_URL}${safeImages[selected]?.url}`
            : (safeImages[selected]?.url ?? '')
        "
        :alt="safeImages[selected]?.alt"
        width="960"
        height="720"
        loading="lazy"
        @error="markFailed(selected)"
      />
      <div v-else class="product-gallery-fallback">
        <span>暂无可展示图片</span>
        <small>可联系卖家确认物品状态</small>
      </div>
      <span v-if="safeImages.length > 1" class="gallery-count">
        {{ selected + 1 }} / {{ safeImages.length }}
      </span>
    </div>
    <div v-if="safeImages.length > 1" class="gallery-thumbnails" aria-label="选择商品图片">
      <button
        v-for="(image, index) in safeImages"
        :key="`${image.url}-${index}`"
        type="button"
        :aria-label="`查看第 ${index + 1} 张图片`"
        :aria-current="selected === index ? 'true' : undefined"
        @click="selected = index"
      >
        {{ index + 1 }}
      </button>
    </div>
  </section>
</template>
