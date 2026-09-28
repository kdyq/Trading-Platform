<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { inviteStaff, listStaff, updateStaffRoles, updateStaffStatus } from '../api/admin'
import type { Staff } from '../api/admin'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const items = ref<Staff[]>([])
const total = ref(0)
const page = ref(1)
const email = ref('')
const newRole = ref('SUPPORT')
const inviteReason = ref('')
const reasonById = ref<Record<string, string>>({})
const roleById = ref<Record<string, string>>({})
const busy = ref(false)
const error = ref('')
const message = ref('')

async function load() {
  if (!auth.accessToken) return
  error.value = ''
  try {
    const result = await listStaff(auth.accessToken, page.value)
    items.value = result.items
    total.value = result.total
    for (const item of result.items) roleById.value[item.id] = item.roles[0] || 'SUPPORT'
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '后台人员加载失败'
  }
}

async function invite() {
  if (!auth.accessToken || busy.value || inviteReason.value.trim().length < 5) return
  if (!window.confirm(`确认将已注册账户 ${email.value} 授予 ${newRole.value} 角色？`)) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    await inviteStaff(
      auth.accessToken,
      email.value.trim(),
      newRole.value,
      inviteReason.value.trim(),
    )
    email.value = ''
    inviteReason.value = ''
    message.value = '后台角色已授予，相关旧会话已撤销。'
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '邀请失败'
  } finally {
    busy.value = false
  }
}

async function changeRole(item: Staff) {
  if (!auth.accessToken || busy.value) return
  const reason = reasonById.value[item.id]?.trim() || ''
  if (reason.length < 5) {
    error.value = '请填写至少 5 字的变更理由。'
    return
  }
  if (!window.confirm(`确认修改 ${item.display_name} 的后台角色？旧会话将全部失效。`)) return
  busy.value = true
  try {
    await updateStaffRoles(
      auth.accessToken,
      item.id,
      [roleById.value[item.id] || 'SUPPORT'],
      reason,
    )
    message.value = '角色已更新。'
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '角色更新失败'
  } finally {
    busy.value = false
  }
}

async function changeStatus(item: Staff) {
  if (!auth.accessToken || busy.value) return
  const reason = reasonById.value[item.id]?.trim() || ''
  if (reason.length < 5) {
    error.value = '请填写至少 5 字的变更理由。'
    return
  }
  const next = item.status === 'active' ? 'disabled' : 'active'
  if (
    !window.confirm(
      `确认${next === 'active' ? '启用' : '停用'} ${item.display_name}？旧会话将全部失效。`,
    )
  )
    return
  busy.value = true
  try {
    await updateStaffStatus(auth.accessToken, item.id, next, reason)
    message.value = '状态已更新。'
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '状态更新失败'
  } finally {
    busy.value = false
  }
}

function turn(delta: number) {
  page.value = Math.max(1, page.value + delta)
  void load()
}
onMounted(load)
</script>

<template>
  <section class="admin-ops">
    <header>
      <div>
        <p class="eyebrow">Identity & Access</p>
        <h1>后台人员</h1>
        <p>固定角色与最小权限；每次变更都要求理由与再次确认。</p>
      </div>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" class="success" role="status">{{ message }}</p>
    <form class="admin-ops-card" @submit.prevent="invite">
      <h2>邀请已注册账户</h2>
      <p>受邀者需先完成普通邮箱注册，不会自动创建未验证账号。</p>
      <div class="admin-ops-toolbar">
        <input
          v-model.trim="email"
          aria-label="受邀邮箱"
          type="email"
          placeholder="已注册邮箱"
          required
        />
        <select v-model="newRole" aria-label="受邀角色">
          <option>SUPPORT</option>
          <option>REVIEWER</option>
          <option>ADMIN</option>
          <option>SUPER_ADMIN</option>
        </select>
        <input
          v-model.trim="inviteReason"
          aria-label="邀请理由"
          minlength="5"
          maxlength="500"
          placeholder="授权理由"
          required
        />
        <button :disabled="busy" type="submit">授予角色</button>
      </div>
    </form>
    <div class="admin-ops-card">
      <div class="admin-ops-table-wrap">
        <table>
          <thead>
            <tr>
              <th>人员</th>
              <th>状态</th>
              <th>角色</th>
              <th>操作与理由</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>
                <strong>{{ item.display_name }}</strong
                ><small>{{ item.username || item.email }}</small>
              </td>
              <td>
                <span class="status" :data-status="item.status">{{ item.status }}</span>
              </td>
              <td>
                <span v-for="role in item.roles" :key="role">{{ role }} </span>
              </td>
              <td>
                <div class="admin-ops-actions">
                  <select
                    v-model="roleById[item.id]"
                    :aria-label="`变更 ${item.display_name} 角色`"
                  >
                    <option>SUPPORT</option>
                    <option>REVIEWER</option>
                    <option>ADMIN</option>
                    <option>SUPER_ADMIN</option></select
                  ><input
                    v-model="reasonById[item.id]"
                    :aria-label="`变更 ${item.display_name} 理由`"
                    maxlength="500"
                    placeholder="变更理由"
                  /><button
                    class="secondary"
                    :disabled="busy || item.id === auth.user?.id"
                    @click="changeRole(item)"
                  >
                    变更角色</button
                  ><button
                    :class="item.status === 'active' ? 'secondary' : 'safe'"
                    :disabled="busy || item.id === auth.user?.id"
                    @click="changeStatus(item)"
                  >
                    {{ item.status === 'active' ? '停用' : '启用' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!items.length">暂无后台人员。</p>
      <nav class="admin-ops-pager">
        <span>第 {{ page }} 页 · 共 {{ total }} 人</span
        ><button class="secondary" :disabled="page === 1" @click="turn(-1)">上一页</button
        ><button class="secondary" :disabled="page * 20 >= total" @click="turn(1)">下一页</button>
      </nav>
    </div>
  </section>
</template>
