<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listCampuses, listCategories, updateCatalogItem } from '../api/admin'
import type { ManagedCampus, ManagedCategory } from '../api/admin'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const categories = ref<ManagedCategory[]>([])
const campuses = ref<ManagedCampus[]>([])
const categoryPage = ref(1)
const campusPage = ref(1)
const categoryTotal = ref(0)
const campusTotal = ref(0)
const reasons = ref<Record<string, string>>({})
const busy = ref(false)
const error = ref('')
const message = ref('')

async function load() {
  if (!auth.accessToken) return
  error.value = ''
  try {
    const [c, a] = await Promise.all([
      listCategories(auth.accessToken, categoryPage.value),
      listCampuses(auth.accessToken, campusPage.value),
    ])
    categories.value = c.items
    categoryTotal.value = c.total
    campuses.value = a.items
    campusTotal.value = a.total
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '基础数据加载失败'
  }
}

async function save(kind: 'categories' | 'campuses', item: ManagedCategory | ManagedCampus) {
  if (!auth.accessToken || busy.value) return
  const reason = reasons.value[item.id]?.trim() || ''
  if (reason.length < 5) {
    error.value = '请填写至少 5 字的维护理由。'
    return
  }
  if (!window.confirm(`确认更新「${item.name}」的排序与启用状态？`)) return
  busy.value = true
  try {
    await updateCatalogItem(auth.accessToken, kind, item, reason)
    message.value = '基础数据已更新并留下审计记录。'
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '基础数据更新失败'
  } finally {
    busy.value = false
  }
}

function turn(kind: 'categories' | 'campuses', delta: number) {
  if (kind === 'categories') categoryPage.value = Math.max(1, categoryPage.value + delta)
  else campusPage.value = Math.max(1, campusPage.value + delta)
  void load()
}
onMounted(load)
</script>

<template>
  <section class="admin-ops">
    <header>
      <div>
        <p class="eyebrow">Taxonomy</p>
        <h1>分类与校区</h1>
        <p>仅维护排序和启用状态；不硬删除已经被商品与认证引用的记录。</p>
      </div>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" class="success" role="status">{{ message }}</p>
    <div class="admin-ops-card">
      <h2>商品分类</h2>
      <div class="admin-ops-table-wrap">
        <table>
          <thead>
            <tr>
              <th>分类</th>
              <th>层级</th>
              <th>排序</th>
              <th>启用</th>
              <th>维护理由</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in categories" :key="item.id">
              <td>
                <strong>{{ item.name }}</strong
                ><small>{{ item.code }}</small>
              </td>
              <td>{{ item.level }}</td>
              <td>
                <input
                  v-model.number="item.display_order"
                  :aria-label="`排序 ${item.name}`"
                  type="number"
                  min="0"
                />
              </td>
              <td>
                <input v-model="item.is_active" :aria-label="`启用 ${item.name}`" type="checkbox" />
              </td>
              <td>
                <div class="admin-ops-actions">
                  <input
                    v-model="reasons[item.id]"
                    :aria-label="`维护 ${item.name} 理由`"
                    maxlength="500"
                    placeholder="维护理由"
                  /><button :disabled="busy" @click="save('categories', item)">保存</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <nav class="admin-ops-pager">
        <span>第 {{ categoryPage }} 页 · 共 {{ categoryTotal }} 项</span
        ><button class="secondary" :disabled="categoryPage === 1" @click="turn('categories', -1)">
          上一页</button
        ><button
          class="secondary"
          :disabled="categoryPage * 20 >= categoryTotal"
          @click="turn('categories', 1)"
        >
          下一页
        </button>
      </nav>
    </div>
    <div class="admin-ops-card">
      <h2>校区</h2>
      <div class="admin-ops-table-wrap">
        <table>
          <thead>
            <tr>
              <th>校区</th>
              <th>学校</th>
              <th>排序</th>
              <th>启用</th>
              <th>维护理由</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in campuses" :key="item.id">
              <td>
                <strong>{{ item.name }}</strong
                ><small>{{ item.code }}</small>
              </td>
              <td>{{ item.school_name }}</td>
              <td>
                <input
                  v-model.number="item.display_order"
                  :aria-label="`排序 ${item.name}`"
                  type="number"
                  min="0"
                />
              </td>
              <td>
                <input v-model="item.is_active" :aria-label="`启用 ${item.name}`" type="checkbox" />
              </td>
              <td>
                <div class="admin-ops-actions">
                  <input
                    v-model="reasons[item.id]"
                    :aria-label="`维护 ${item.name} 理由`"
                    maxlength="500"
                    placeholder="维护理由"
                  /><button :disabled="busy" @click="save('campuses', item)">保存</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <nav class="admin-ops-pager">
        <span>第 {{ campusPage }} 页 · 共 {{ campusTotal }} 项</span
        ><button class="secondary" :disabled="campusPage === 1" @click="turn('campuses', -1)">
          上一页</button
        ><button
          class="secondary"
          :disabled="campusPage * 20 >= campusTotal"
          @click="turn('campuses', 1)"
        >
          下一页
        </button>
      </nav>
    </div>
  </section>
</template>
