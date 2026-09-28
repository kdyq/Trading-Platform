<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { adminCapabilities, listProducts, manageProduct } from '../api/admin'
import type { ManagedProduct } from '../api/admin'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const items = ref<ManagedProduct[]>([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const status = ref('')
const notes = ref<Record<string, string>>({})
const canManage = ref(false)
const busy = ref(false)
const error = ref('')
const message = ref('')

async function load() {
  if (!auth.accessToken) return
  error.value = ''
  try {
    const [result, caps] = await Promise.all([
      listProducts(auth.accessToken, page.value, search.value, status.value),
      adminCapabilities(auth.accessToken),
    ])
    items.value = result.items
    total.value = result.total
    canManage.value = caps.permissions.includes('moderation:review')
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '商品列表加载失败'
  }
}

async function decide(item: ManagedProduct, action: 'hide' | 'restore') {
  if (!auth.accessToken || busy.value) return
  const reason = notes.value[item.id]?.trim() || ''
  if (reason.length < 5) {
    error.value = '请填写至少 5 字的处理说明。'
    return
  }
  if (!window.confirm(`确认${action === 'hide' ? '隐藏' : '恢复'}商品「${item.title}」？`)) return
  busy.value = true
  try {
    await manageProduct(auth.accessToken, item, action, reason)
    message.value = '商品状态已更新并记录审计。'
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '商品处理失败'
  } finally {
    busy.value = false
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
onMounted(load)
</script>

<template>
  <section class="admin-ops">
    <header>
      <div>
        <p class="eyebrow">Marketplace</p>
        <h1>商品管理</h1>
        <p>稳定分页检索；隐藏和恢复沿用商品审核状态机与卖家通知。</p>
      </div>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" class="success" role="status">{{ message }}</p>
    <div class="admin-ops-card">
      <form class="admin-ops-toolbar" @submit.prevent="searchNow">
        <input
          v-model.trim="search"
          aria-label="搜索商品"
          maxlength="100"
          placeholder="商品标题"
        /><select v-model="status" aria-label="商品状态">
          <option value="">全部状态</option>
          <option value="on_sale">在售</option>
          <option value="pending_review">待审</option>
          <option value="hidden">已隐藏</option>
          <option value="sold">已成交</option></select
        ><button type="submit">筛选</button>
      </form>
      <div class="admin-ops-table-wrap">
        <table>
          <thead>
            <tr>
              <th>商品</th>
              <th>卖家</th>
              <th>价格</th>
              <th>状态</th>
              <th v-if="canManage">处理</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>
                <strong>{{ item.title }}</strong
                ><small>{{ item.id }}</small>
              </td>
              <td>{{ item.seller_name }}</td>
              <td>¥{{ item.price }}</td>
              <td>
                <span class="status" :data-status="item.status">{{ item.status }}</span>
              </td>
              <td v-if="canManage">
                <div class="admin-ops-actions">
                  <input
                    v-model="notes[item.id]"
                    :aria-label="`处理 ${item.title} 说明`"
                    maxlength="500"
                    placeholder="公开处理说明"
                  /><button
                    v-if="item.status === 'on_sale'"
                    :disabled="busy"
                    @click="decide(item, 'hide')"
                  >
                    隐藏</button
                  ><button
                    v-if="item.status === 'hidden' && !item.report_penalty_active"
                    class="safe"
                    :disabled="busy"
                    @click="decide(item, 'restore')"
                  >
                    恢复</button
                  ><span v-else-if="item.report_penalty_active">需经举报申诉复核</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!items.length">没有匹配的商品。</p>
      <nav class="admin-ops-pager">
        <span>第 {{ page }} 页 · 共 {{ total }} 件</span
        ><button class="secondary" :disabled="page === 1" @click="turn(-1)">上一页</button
        ><button class="secondary" :disabled="page * 20 >= total" @click="turn(1)">下一页</button>
      </nav>
    </div>
  </section>
</template>
