<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listUsers, updateUserStatus } from '../api/admin'
import type { ManagedUser } from '../api/admin'
import { adminCapabilities } from '../api/admin'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const items = ref<ManagedUser[]>([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const status = ref('')
const reasons = ref<Record<string, string>>({})
const canManage = ref(false)
const error = ref('')
const message = ref('')
const busy = ref(false)

async function load() {
  if (!auth.accessToken) return
  error.value = ''
  try {
    const [result, caps] = await Promise.all([
      listUsers(auth.accessToken, page.value, search.value, status.value),
      adminCapabilities(auth.accessToken),
    ])
    items.value = result.items
    total.value = result.total
    canManage.value = caps.permissions.includes('users:status')
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '用户列表加载失败'
  }
}

function searchNow() {
  page.value = 1
  void load()
}
function turn(delta: number) {
  page.value = Math.max(1, page.value + delta)
  void load()
}
async function changeStatus(item: ManagedUser) {
  if (!auth.accessToken || busy.value) return
  const reason = reasons.value[item.id]?.trim() || ''
  if (reason.length < 5) {
    error.value = '请填写至少 5 字的状态变更理由。'
    return
  }
  const next = item.status === 'active' ? 'disabled' : 'active'
  if (
    !window.confirm(
      `确认${next === 'active' ? '启用' : '停用'} ${item.display_name}？其现有会话将全部撤销。`,
    )
  )
    return
  busy.value = true
  error.value = ''
  try {
    await updateUserStatus(auth.accessToken, item.id, next, reason)
    message.value = '状态变更已记录审计。'
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '状态变更失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="admin-ops">
    <header>
      <div>
        <p class="eyebrow">People</p>
        <h1>用户管理</h1>
        <p>按昵称或登录邮箱检索；普通后台角色默认只看脱敏邮箱。</p>
      </div>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" class="success" role="status">{{ message }}</p>
    <div class="admin-ops-card">
      <form class="admin-ops-toolbar" @submit.prevent="searchNow">
        <input
          v-model.trim="search"
          aria-label="搜索用户"
          maxlength="100"
          placeholder="昵称或邮箱"
        />
        <select v-model="status" aria-label="用户状态">
          <option value="">全部状态</option>
          <option value="active">正常</option>
          <option value="suspended">暂停</option>
          <option value="disabled">停用</option>
        </select>
        <button type="submit">筛选</button>
      </form>
      <div class="admin-ops-table-wrap">
        <table>
          <thead>
            <tr>
              <th>用户</th>
              <th>登录邮箱</th>
              <th>校园认证</th>
              <th>状态</th>
              <th v-if="canManage">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>
                <strong>{{ item.display_name }}</strong
                ><small>{{ item.id }}</small>
              </td>
              <td>{{ item.email }}</td>
              <td>{{ item.campus_status }}</td>
              <td>
                <span class="status" :data-status="item.status">{{ item.status }}</span>
              </td>
              <td v-if="canManage">
                <div class="admin-ops-actions">
                  <input
                    v-model="reasons[item.id]"
                    :aria-label="`更改 ${item.display_name} 状态理由`"
                    maxlength="500"
                    placeholder="状态变更理由"
                  /><button
                    v-if="item.status !== 'suspended'"
                    :disabled="busy || item.id === auth.user?.id"
                    @click="changeStatus(item)"
                  >
                    {{ item.status === 'active' ? '停用' : '启用' }}</button
                  ><span v-else>需经举报申诉复核</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!items.length">没有匹配的用户。</p>
      <nav class="admin-ops-pager">
        <span>第 {{ page }} 页 · 共 {{ total }} 人</span
        ><button class="secondary" :disabled="page === 1" @click="turn(-1)">上一页</button
        ><button class="secondary" :disabled="page * 20 >= total" @click="turn(1)">下一页</button>
      </nav>
    </div>
  </section>
</template>
