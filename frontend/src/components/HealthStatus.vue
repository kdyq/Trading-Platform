<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { getReadiness, type ReadinessResponse } from '../api/health'

type ViewState = 'loading' | 'ready' | 'not-ready' | 'error'

const state = ref<ViewState>('loading')
const readiness = ref<ReadinessResponse | null>(null)

const label = computed(() => {
  if (state.value === 'ready') return '服务已连接'
  if (state.value === 'not-ready') return '服务正在准备'
  if (state.value === 'error') return '暂时无法连接服务'
  return '正在检查服务'
})

onMounted(async () => {
  try {
    readiness.value = await getReadiness()
    state.value = readiness.value.status === 'ready' ? 'ready' : 'not-ready'
  } catch {
    state.value = 'error'
  }
})
</script>

<template>
  <div class="health-status" :data-state="state" role="status" aria-live="polite">
    <span class="health-dot" aria-hidden="true" />
    <span>{{ label }}</span>
  </div>
</template>
