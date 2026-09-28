<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  adminCapabilities,
  createAuditExport,
  downloadAuditExport,
  listAudit,
  listAuditExports,
  revokeAuditExport,
} from '../api/admin'
import type { AuditEntry, AuditExport } from '../api/admin'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const items = ref<AuditEntry[]>([])
const total = ref(0)
const page = ref(1)
const action = ref('')
const exportReason = ref('')
const exportJobs = ref<AuditExport[]>([])
const exportPage = ref(1)
const exportTotal = ref(0)
const error = ref('')
const message = ref('')
const busy = ref(false)
const canExport = ref(false)

async function load() {
  if (!auth.accessToken) return
  error.value = ''
  try {
    const [result, caps] = await Promise.all([
      listAudit(auth.accessToken, page.value, action.value),
      adminCapabilities(auth.accessToken),
    ])
    items.value = result.items
    total.value = result.total
    canExport.value = caps.permissions.includes('audit:export')
    if (canExport.value) await refreshExports()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '审计日志加载失败'
  }
}

async function refreshExports() {
  if (!auth.accessToken || !canExport.value) return
  const result = await listAuditExports(auth.accessToken, exportPage.value)
  exportJobs.value = result.items
  exportTotal.value = result.total
}

function turnExports(delta: number) {
  exportPage.value = Math.max(1, exportPage.value + delta)
  void refreshExports()
}

function filter() {
  page.value = 1
  void load()
}
function turn(delta: number) {
  page.value = Math.max(1, page.value + delta)
  void load()
}
async function createExport() {
  if (!auth.accessToken || busy.value) return
  if (exportReason.value.trim().length < 5) {
    error.value = '请填写至少 5 字的导出理由。'
    return
  }
  if (!window.confirm('确认导出过去 7 天的审计日志？文件将包含操作者水印，并于 1 小时后过期。'))
    return
  busy.value = true
  try {
    await createAuditExport(auth.accessToken, exportReason.value.trim(), action.value)
    exportPage.value = 1
    await refreshExports()
    message.value = '导出已排队，等待独立任务处理。'
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '导出创建失败'
  } finally {
    busy.value = false
  }
}

async function refreshExport() {
  try {
    await refreshExports()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '任务状态读取失败'
  }
}

async function downloadExport(job: AuditExport) {
  if (!auth.accessToken) return
  try {
    const blob = await downloadAuditExport(auth.accessToken, job.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `audit-${job.id}.csv`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '文件下载失败'
  }
}

async function revoke(job: AuditExport) {
  if (!auth.accessToken) return
  if (!window.confirm('确认撤销此导出文件的访问权限？')) return
  try {
    await revokeAuditExport(auth.accessToken, job.id)
    await refreshExports()
    message.value = '文件访问已撤销。'
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '撤销失败'
  }
}
onMounted(load)
</script>

<template>
  <section class="admin-ops">
    <header>
      <div>
        <p class="eyebrow">Accountability</p>
        <h1>审计日志</h1>
        <p>只读检索；敏感字段脱敏，导出需要独立权限并带操作者水印。</p>
      </div>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" class="success" role="status">{{ message }}</p>
    <div class="admin-ops-card">
      <form class="admin-ops-toolbar" @submit.prevent="filter">
        <input
          v-model.trim="action"
          aria-label="审计动作"
          maxlength="96"
          placeholder="按动作代码筛选"
        /><button type="submit">搜索</button>
      </form>
      <div class="admin-ops-table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>操作者</th>
              <th>动作</th>
              <th>对象</th>
              <th>脱敏详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>{{ new Date(item.created_at).toLocaleString() }}</td>
              <td>{{ item.actor_id || '系统' }}</td>
              <td>
                <strong>{{ item.action }}</strong>
              </td>
              <td>
                {{ item.target_type }}<small>{{ item.target_id }}</small>
              </td>
              <td>
                <pre>{{ JSON.stringify(item.audit_data, null, 2) }}</pre>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!items.length">所选区间暂无审计记录。</p>
      <nav class="admin-ops-pager">
        <span>第 {{ page }} 页 · 共 {{ total }} 条</span
        ><button class="secondary" :disabled="page === 1" @click="turn(-1)">上一页</button
        ><button class="secondary" :disabled="page * 20 >= total" @click="turn(1)">下一页</button>
      </nav>
    </div>
    <div v-if="canExport" class="admin-ops-card">
      <h2>异步导出</h2>
      <p>创建后由独立 worker 处理；下载仍会重新验证当前权限、所有者与有效期。</p>
      <div class="admin-ops-toolbar">
        <input
          v-model.trim="exportReason"
          aria-label="导出理由"
          minlength="5"
          maxlength="500"
          placeholder="导出理由"
        /><button :disabled="busy" @click="createExport">创建导出</button>
      </div>
      <div v-for="job in exportJobs" :key="job.id" class="admin-ops-actions">
        <span
          >任务 {{ job.id }} · {{ job.status }} · 到期
          {{ new Date(job.expires_at).toLocaleString() }}</span
        ><button class="secondary" @click="refreshExport">刷新状态</button
        ><button v-if="job.status === 'ready' && !job.revoked" @click="downloadExport(job)">
          下载 CSV</button
        ><button v-if="!job.revoked" class="secondary" @click="revoke(job)">撤销访问</button>
      </div>
      <p v-if="!exportJobs.length">暂无导出任务。</p>
      <nav class="admin-ops-pager">
        <span>第 {{ exportPage }} 页 · 共 {{ exportTotal }} 项</span
        ><button class="secondary" :disabled="exportPage === 1" @click="turnExports(-1)">
          上一页</button
        ><button
          class="secondary"
          :disabled="exportPage * 20 >= exportTotal"
          @click="turnExports(1)"
        >
          下一页
        </button>
      </nav>
    </div>
  </section>
</template>

<style scoped>
pre {
  max-width: 330px;
  margin: 0;
  overflow-x: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font:
    0.78rem/1.4 Consolas,
    monospace;
}
</style>
