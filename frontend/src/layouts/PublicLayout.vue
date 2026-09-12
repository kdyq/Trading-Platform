<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="site-shell">
    <header class="site-header">
      <nav class="container navigation" aria-label="主导航">
        <RouterLink class="wordmark" to="/"> 拾光集市 </RouterLink>
        <div class="navigation-actions">
          <RouterLink class="navigation-link" to="/"> 逛好物 </RouterLink>
          <RouterLink class="button button-primary" to="/login"> 登录 </RouterLink>
        </div>
      </nav>
    </header>
    <main>
      <RouterView />
    </main>
    <footer class="site-footer">
      <div class="container footer-content">
        <strong>拾光集市</strong>
        <span>让闲置在校园里继续发光</span>
      </div>
    </footer>
  </div>
</template>
