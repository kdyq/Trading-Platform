<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <section class="container narrow-page">
    <div class="empty-state">
      <p class="error-code num">404</p>
      <h1>这个摊位还没有摆出来</h1>
      <p>地址可能写错了，回到首页继续逛逛。</p>
      <RouterLink class="button button-primary" to="/"> 返回首页 </RouterLink>
    </div>
  </section>
</template>
