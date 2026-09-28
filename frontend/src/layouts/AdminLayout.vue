<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { useRouter } from 'vue-router'

import { adminCapabilities } from '../api/admin'
import type { AdminCapabilities } from '../api/admin'
import { useAuthStore } from '../stores/auth'
import '../styles/admin-ops.css'

const auth = useAuthStore()
const router = useRouter()
const capabilities = ref<AdminCapabilities | null>(null)
const error = ref('')
const loading = ref(true)
const permissions = computed(() => new Set(capabilities.value?.permissions ?? []))
onMounted(async () => {
  await auth.restore()
  if (!auth.user || !auth.accessToken) {
    await router.replace('/login')
    return
  }
  if (auth.user.must_change_password) {
    await router.replace('/account')
    return
  }
  try {
    capabilities.value = await adminCapabilities(auth.accessToken)
    if (!capabilities.value.permissions.length) error.value = '当前账户没有后台权限。'
    if (
      router.currentRoute.value.path === '/admin' &&
      !permissions.value.has('moderation:review')
    ) {
      await router.replace('/admin/users')
    }
  } catch {
    error.value = '后台权限加载失败，请重新登录。'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="admin-shell">
    <aside class="admin-sidebar">
      <RouterLink class="wordmark" to="/"> 拾光集市 </RouterLink>
      <p>管理后台 · {{ capabilities?.roles.join(' / ') || '载入中' }}</p>
      <nav v-if="capabilities" class="admin-navigation" aria-label="后台导航">
        <RouterLink
          v-if="permissions.has('dashboard:read')"
          class="admin-link"
          to="/admin/dashboard"
          >运营概览</RouterLink
        >
        <RouterLink v-if="permissions.has('moderation:review')" class="admin-link" to="/admin"
          >审核工作台</RouterLink
        >
        <RouterLink v-if="permissions.has('users:read')" class="admin-link" to="/admin/users"
          >用户管理</RouterLink
        >
        <RouterLink v-if="permissions.has('products:read')" class="admin-link" to="/admin/products"
          >商品管理</RouterLink
        >
        <RouterLink
          v-if="permissions.has('campus_appeal:read')"
          class="admin-link"
          to="/admin/campus-appeals"
          >校园复核</RouterLink
        >
        <RouterLink v-if="permissions.has('catalog:read')" class="admin-link" to="/admin/catalog"
          >分类与校区</RouterLink
        >
        <RouterLink v-if="permissions.has('staff:manage')" class="admin-link" to="/admin/staff"
          >后台人员</RouterLink
        >
        <RouterLink v-if="permissions.has('audit:read')" class="admin-link" to="/admin/audit"
          >审计日志</RouterLink
        >
      </nav>
      <RouterLink class="admin-home" to="/">返回集市</RouterLink>
    </aside>
    <main class="admin-main">
      <p v-if="loading">正在核对后台权限…</p>
      <div v-else-if="error" class="admin-panel" role="alert">{{ error }}</div>
      <RouterView v-else />
    </main>
  </div>
</template>

<style scoped>
.admin-navigation {
  display: grid;
  gap: 0.45rem;
}
.admin-link {
  background: transparent;
  color: var(--ink-2);
}
.admin-link.router-link-exact-active {
  background: var(--peach);
  color: var(--primary-deep);
}
.admin-home {
  margin-top: auto;
  color: var(--leaf);
  font-weight: 700;
}
</style>
