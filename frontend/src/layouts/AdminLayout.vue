<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="admin-shell">
    <aside class="admin-sidebar">
      <RouterLink class="wordmark" to="/"> 拾光集市 </RouterLink>
      <p>管理后台</p>
      <RouterLink class="admin-link" to="/admin"> 工作台 </RouterLink>
    </aside>
    <main class="admin-main">
      <RouterView />
    </main>
  </div>
</template>
