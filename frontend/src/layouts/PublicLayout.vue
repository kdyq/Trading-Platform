<script setup lang="ts">
import { RouterLink, RouterView, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

async function logout() {
  await auth.logout()
  await router.push('/')
}
</script>

<template>
  <div class="site-shell">
    <header class="site-header">
      <nav class="container navigation" aria-label="主导航">
        <RouterLink class="wordmark" to="/"> 拾光集市 </RouterLink>
        <div class="navigation-actions">
          <RouterLink class="navigation-link" to="/market"> 逛好物 </RouterLink>
          <template v-if="auth.user">
            <RouterLink class="navigation-link" to="/account">
              {{ auth.user.display_name }}
            </RouterLink>
            <button class="button button-ghost" type="button" @click="logout">退出</button>
          </template>
          <RouterLink v-else class="button button-primary" to="/login"> 登录 </RouterLink>
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
