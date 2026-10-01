<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const menuOpen = ref(false)
const canTrade = computed(() => auth.user?.status === 'active' && !auth.user.must_change_password)
watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)

async function logout() {
  await auth.logout()
  await router.push('/')
}
</script>

<template>
  <div class="site-shell">
    <header class="site-header">
      <nav class="container navigation" aria-label="主导航" @keydown.esc="menuOpen = false">
        <RouterLink class="wordmark" to="/"> 拾光集市 </RouterLink>
        <button
          class="button button-ghost navigation-toggle"
          type="button"
          aria-controls="site-navigation"
          :aria-expanded="menuOpen"
          @click="menuOpen = !menuOpen"
        >
          {{ menuOpen ? '关闭菜单' : '菜单' }}
        </button>
        <div id="site-navigation" class="navigation-actions" :class="{ 'is-open': menuOpen }">
          <RouterLink class="navigation-link" to="/market"> 逛好物 </RouterLink>
          <template v-if="auth.user">
            <template v-if="canTrade">
              <RouterLink class="navigation-link" to="/sell">发布闲置</RouterLink>
              <RouterLink class="navigation-link" to="/my-products">我的发布</RouterLink>
              <RouterLink class="navigation-link" to="/favorites">收藏</RouterLink>
              <RouterLink class="navigation-link" to="/messages">消息</RouterLink>
              <RouterLink class="navigation-link" to="/orders">订单</RouterLink>
              <RouterLink class="navigation-link" to="/reports">举报</RouterLink>
            </template>
            <RouterLink
              v-if="!auth.user.must_change_password"
              class="navigation-link"
              to="/notifications"
              >通知</RouterLink
            >
            <RouterLink class="navigation-link" to="/account">
              {{ auth.user.display_name }}
            </RouterLink>
            <button class="button button-ghost" type="button" @click="logout">退出</button>
          </template>
          <RouterLink v-else class="button button-primary" to="/login"> 登录 </RouterLink>
        </div>
      </nav>
    </header>
    <p v-if="auth.user?.status === 'suspended'" class="container form-message" role="status">
      账户已暂停。可查看通知、提交处罚申诉和管理账户安全。
    </p>
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
