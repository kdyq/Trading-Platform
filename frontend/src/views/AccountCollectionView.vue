<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => String(route.meta.title ?? '账户记录'))
const description = computed(() => String(route.meta.description ?? '当前还没有可展示的内容。'))
</script>

<template>
  <section class="container narrow-page">
    <div class="empty-state">
      <p class="eyebrow">个人中心</p>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
      <RouterLink class="button button-primary" to="/account">返回账户与安全</RouterLink>
    </div>
  </section>
</template>
