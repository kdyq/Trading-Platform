<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'

const hasError = ref(false)

onErrorCaptured(() => {
  hasError.value = true
  return false
})

function reload(): void {
  window.location.reload()
}
</script>

<template>
  <section v-if="hasError" class="error-boundary" role="alert">
    <p class="eyebrow">页面暂时不可用</p>
    <h1>这里没有正常加载</h1>
    <p>请刷新后再试。若问题持续出现，请稍后返回。</p>
    <button class="button button-primary" type="button" @click="reload">刷新页面</button>
  </section>
  <slot v-else />
</template>
