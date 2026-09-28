<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { campusAppealMaterial, decideCampusAppeal, listCampusAppeals } from '../api/admin'
import type { CampusAppeal } from '../api/admin'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const items = ref<CampusAppeal[]>([])
const page = ref(1)
const total = ref(0)
const status = ref('pending')
const reasons = ref<Record<string, string>>({})
const error = ref('')
const message = ref('')
const busy = ref(false)

async function load() {
  if (!auth.accessToken) return
  error.value = ''
  try {
    const result = await listCampusAppeals(auth.accessToken, page.value, status.value)
    items.value = result.items
    total.value = result.total
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '校园申诉加载失败'
  }
}

async function download(item: CampusAppeal) {
  if (!auth.accessToken) return
  try {
    const blob = await campusAppealMaterial(auth.accessToken, item.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = item.original_filename
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '材料下载失败'
  }
}

async function decide(item: CampusAppeal, action: 'approve' | 'reject') {
  if (!auth.accessToken || busy.value) return
  const reason = reasons.value[item.id]?.trim() || ''
  if (reason.length < 5) {
    error.value = '请填写至少 5 字的复核理由。'
    return
  }
  if (!window.confirm(`确认${action === 'approve' ? '通过' : '驳回'}此校园认证申诉？`)) return
  busy.value = true
  try {
    await decideCampusAppeal(auth.accessToken, item.id, action, reason)
    message.value = '复核决定已记录。'
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '复核失败'
  } finally {
    busy.value = false
  }
}

function filter() {
  page.value = 1
  void load()
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
        <p class="eyebrow">Campus Trust</p>
        <h1>校园认证复核</h1>
        <p>材料仅在审核权限下按件下载，不进入通用用户列表。</p>
      </div>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" class="success" role="status">{{ message }}</p>
    <div class="admin-ops-card">
      <div class="admin-ops-toolbar">
        <select v-model="status" aria-label="申诉状态" @change="filter">
          <option value="pending">待复核</option>
          <option value="approved">已通过</option>
          <option value="rejected">已驳回</option>
        </select>
      </div>
      <div class="admin-ops-table-wrap">
        <table>
          <thead>
            <tr>
              <th>申请</th>
              <th>说明</th>
              <th>材料</th>
              <th>状态</th>
              <th>决定</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>
                <strong>{{ item.user_id }}</strong
                ><small>{{ new Date(item.created_at).toLocaleString() }}</small>
              </td>
              <td>{{ item.reason }}</td>
              <td>
                <button class="secondary" @click="download(item)">
                  下载 {{ item.original_filename }}
                </button>
              </td>
              <td>
                <span class="status" :data-status="item.status">{{ item.status }}</span>
              </td>
              <td>
                <div v-if="item.status === 'pending'" class="admin-ops-actions">
                  <input
                    v-model="reasons[item.id]"
                    :aria-label="`复核 ${item.id} 理由`"
                    maxlength="500"
                    placeholder="复核理由"
                  /><button class="safe" :disabled="busy" @click="decide(item, 'approve')">
                    通过</button
                  ><button class="secondary" :disabled="busy" @click="decide(item, 'reject')">
                    驳回
                  </button>
                </div>
                <span v-else>{{ item.review_reason }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!items.length">暂无对应申诉。</p>
      <nav class="admin-ops-pager">
        <span>第 {{ page }} 页 · 共 {{ total }} 件</span
        ><button class="secondary" :disabled="page === 1" @click="turn(-1)">上一页</button
        ><button class="secondary" :disabled="page * 20 >= total" @click="turn(1)">下一页</button>
      </nav>
    </div>
  </section>
</template>
