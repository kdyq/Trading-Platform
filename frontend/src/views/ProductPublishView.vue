<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getCampusStatus } from '../api/campus'
import { ApiError } from '../api/client'
import {
  createSellerProduct,
  getCatalogCategories,
  getSellerProductImage,
  getSellerProduct,
  transitionSellerProduct,
  updateSellerProduct,
  uploadProductImage,
  type CatalogCategory,
  type ProductImageReference,
  type SellerProduct,
  type SellerProductInput,
} from '../api/sellerProducts'
import { useAuthStore } from '../stores/auth'

interface DraftImage extends ProductImageReference {
  previewUrl: string
  name: string
}

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const step = ref(1)
const categories = ref<CatalogCategory[]>([])
const productId = ref<string | null>(null)
const version = ref(1)
const images = ref<DraftImage[]>([])
const loading = ref(true)
const saving = ref(false)
const uploading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
let autoSaveTimer: number | undefined

const form = reactive({
  title: '',
  description: '',
  price: '',
  originalPrice: '',
  categoryId: '',
  campusId: '',
  condition: 'good',
  isNegotiable: false,
  deliveryNotes: '',
})
const conditionOptions = [
  ['new', '全新'],
  ['like_new', '几乎全新'],
  ['good', '轻微使用'],
  ['fair', '使用痕迹'],
]

const flatCategories = computed(() =>
  categories.value.flatMap((category) => [category, ...category.children]),
)
const localKey = computed(() => `shiguang-product-draft:${productId.value ?? 'new'}`)
const canSubmit = computed(
  () =>
    form.title.trim().length >= 5 &&
    form.description.trim().length >= 20 &&
    Number(form.price) > 0 &&
    Boolean(form.categoryId && form.campusId && images.value.length),
)

function inputPayload(): SellerProductInput {
  return {
    title: form.title,
    description: form.description,
    price: form.price || '0',
    original_price: form.originalPrice || null,
    category_id: form.categoryId,
    campus_id: form.campusId,
    condition: form.condition,
    is_negotiable: form.isNegotiable,
    delivery_notes: form.deliveryNotes || null,
  }
}

async function applyProduct(product: SellerProduct) {
  productId.value = product.id
  version.value = product.version
  Object.assign(form, {
    title: product.title,
    description: product.description,
    price: product.price,
    originalPrice: product.original_price ?? '',
    categoryId: product.category_id,
    campusId: product.campus_id,
    condition: product.condition,
    isNegotiable: product.is_negotiable,
    deliveryNotes: product.delivery_notes ?? '',
  })
  images.value = await Promise.all(
    product.images.map(async (image) => {
      let previewUrl = ''
      if (auth.accessToken) {
        try {
          previewUrl = URL.createObjectURL(
            await getSellerProductImage(auth.accessToken, image.thumbnail_url),
          )
        } catch {
          previewUrl = ''
        }
      }
      return {
        kind: 'existing' as const,
        id: image.id,
        previewUrl,
        name: image.alt_text ?? '商品图片',
      }
    }),
  )
}

function storeLocal() {
  localStorage.setItem(
    localKey.value,
    JSON.stringify({ step: step.value, form: { ...form }, productId: productId.value }),
  )
}

function restoreLocal() {
  const saved = localStorage.getItem(localKey.value)
  if (!saved) return
  try {
    const parsed = JSON.parse(saved) as { step?: number; form?: Partial<typeof form> }
    Object.assign(form, parsed.form ?? {})
    step.value = Math.min(3, Math.max(1, parsed.step ?? 1))
  } catch {
    localStorage.removeItem(localKey.value)
  }
}

async function saveDraft(showFeedback = true) {
  if (!auth.accessToken || !form.categoryId || !form.campusId || saving.value) return false
  saving.value = true
  errorMessage.value = ''
  try {
    let product: SellerProduct
    if (productId.value) {
      product = await updateSellerProduct(
        auth.accessToken,
        productId.value,
        version.value,
        inputPayload(),
        images.value.map(({ kind, id }) => ({ kind, id })),
      )
    } else {
      product = await createSellerProduct(auth.accessToken, inputPayload())
      if (images.value.length) {
        product = await updateSellerProduct(
          auth.accessToken,
          product.id,
          product.version,
          inputPayload(),
          images.value.map(({ kind, id }) => ({ kind, id })),
        )
      }
    }
    await applyProduct(product)
    if (showFeedback) successMessage.value = '草稿已保存'
    storeLocal()
    return true
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '草稿保存失败'
    return false
  } finally {
    saving.value = false
  }
}

async function chooseImages(event: Event) {
  const target = event.target as HTMLInputElement
  const files = [...(target.files ?? [])]
  if (!auth.accessToken || !files.length) return
  if (images.value.length + files.length > 8) {
    errorMessage.value = '每件商品最多上传 8 张图片'
    return
  }
  uploading.value = true
  errorMessage.value = ''
  try {
    for (const file of files) {
      const uploaded = await uploadProductImage(auth.accessToken, file)
      images.value.push({
        kind: 'upload',
        id: uploaded.id,
        previewUrl: URL.createObjectURL(file),
        name: uploaded.original_filename,
      })
    }
    await saveDraft(false)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '图片上传失败'
  } finally {
    uploading.value = false
    target.value = ''
  }
}

function removeImage(index: number) {
  const [removed] = images.value.splice(index, 1)
  if (removed?.previewUrl.startsWith('blob:')) URL.revokeObjectURL(removed.previewUrl)
}

async function submitProduct() {
  if (!(await saveDraft(false)) || !auth.accessToken || !productId.value) return
  saving.value = true
  try {
    const product = await transitionSellerProduct(
      auth.accessToken,
      productId.value,
      'submit',
      version.value,
    )
    await applyProduct(product)
    localStorage.removeItem(localKey.value)
    await router.push('/my-products')
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '提交审核失败'
  } finally {
    saving.value = false
  }
}

watch(
  [form, step, images],
  () => {
    storeLocal()
    window.clearTimeout(autoSaveTimer)
    if (productId.value) {
      autoSaveTimer = window.setTimeout(() => void saveDraft(false), 1200)
    }
  },
  { deep: true },
)

onMounted(async () => {
  if (!auth.accessToken) {
    await router.replace('/login')
    return
  }
  if (auth.user?.campus_verification_status !== 'verified') {
    await router.replace('/campus-verification')
    return
  }
  try {
    const [catalog, campus] = await Promise.all([
      getCatalogCategories(),
      getCampusStatus(auth.accessToken),
    ])
    categories.value = catalog
    form.categoryId = flatCategories.value[0]?.id ?? ''
    form.campusId = campus.campus_id ?? ''
    const routeId = typeof route.params.id === 'string' ? route.params.id : null
    if (routeId) await applyProduct(await getSellerProduct(auth.accessToken, routeId))
    else restoreLocal()
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '发布页加载失败'
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  window.clearTimeout(autoSaveTimer)
  images.value.forEach((image) => {
    if (image.previewUrl.startsWith('blob:')) URL.revokeObjectURL(image.previewUrl)
  })
})
</script>

<template>
  <section class="publish-page">
    <div class="container publish-shell">
      <header class="publish-heading">
        <div>
          <p class="eyebrow">把闲置交给下一位同学</p>
          <h1>{{ productId ? '继续完善商品' : '发布一件校园好物' }}</h1>
          <p>草稿会自动保存在当前设备；首次保存后同步到你的账户。</p>
        </div>
        <RouterLink class="button button-ghost" to="/my-products">我的发布</RouterLink>
      </header>

      <div v-if="loading" class="publish-card">正在准备发布表单…</div>
      <form v-else class="publish-card" @submit.prevent="submitProduct">
        <ol class="publish-steps" aria-label="发布步骤">
          <li v-for="item in 3" :key="item" :class="{ active: step === item }">
            <button type="button" @click="step = item">{{ item }}</button>
            <span>{{ ['基本信息', '图片与交付', '确认提交'][item - 1] }}</span>
          </li>
        </ol>

        <p v-if="errorMessage" class="form-message form-message-error" role="alert">
          {{ errorMessage }}
        </p>
        <p v-if="successMessage" class="form-message form-message-success" role="status">
          {{ successMessage }}
        </p>

        <div v-show="step === 1" class="publish-section">
          <label>商品标题<input v-model="form.title" maxlength="120" required /></label>
          <label>
            详细描述
            <textarea v-model="form.description" maxlength="3000" rows="7"></textarea>
          </label>
          <div class="publish-grid">
            <label>售价<input v-model="form.price" type="number" min="0" step="0.01" /></label>
            <label>
              原价（可选）
              <input v-model="form.originalPrice" type="number" min="0" step="0.01" />
            </label>
            <label>
              分类
              <select v-model="form.categoryId">
                <option v-for="category in flatCategories" :key="category.id" :value="category.id">
                  {{ category.name }}
                </option>
              </select>
            </label>
          </div>
          <fieldset class="chip-fieldset">
            <legend>成色</legend>
            <label v-for="option in conditionOptions" :key="option[0]">
              <input v-model="form.condition" type="radio" :value="option[0]" />
              <span>{{ option[1] }}</span>
            </label>
          </fieldset>
        </div>

        <div v-show="step === 2" class="publish-section">
          <div class="upload-dropzone">
            <strong>上传真实商品图片</strong>
            <p>JPEG、PNG 或 WebP，系统会移除 EXIF；最多 8 张。</p>
            <label class="button button-secondary">
              {{ uploading ? '正在处理…' : '选择图片' }}
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                hidden
                :disabled="uploading"
                @change="chooseImages"
              />
            </label>
          </div>
          <div v-if="images.length" class="publish-image-grid">
            <figure v-for="(image, index) in images" :key="`${image.kind}-${image.id}`">
              <img v-if="image.previewUrl" :src="image.previewUrl" :alt="image.name" />
              <div v-else class="seller-product-placeholder">图片已安全保存</div>
              <figcaption>
                <span>图片 {{ index + 1 }}</span>
                <button type="button" @click="removeImage(index)">移除</button>
              </figcaption>
            </figure>
          </div>
          <label>
            交付说明
            <textarea
              v-model="form.deliveryNotes"
              maxlength="500"
              rows="4"
              placeholder="例如：工作日傍晚东门自提"
            ></textarea>
          </label>
          <label class="check-row">
            <input v-model="form.isNegotiable" type="checkbox" />
            <span>接受合理议价</span>
          </label>
        </div>

        <div v-show="step === 3" class="publish-section review-section">
          <p class="eyebrow">提交前确认</p>
          <h2>{{ form.title || '尚未填写标题' }}</h2>
          <strong class="review-price">¥{{ form.price || '0.00' }}</strong>
          <dl>
            <div>
              <dt>图片</dt>
              <dd>{{ images.length }} 张</dd>
            </div>
            <div>
              <dt>成色</dt>
              <dd>{{ form.condition }}</dd>
            </div>
            <div>
              <dt>交付</dt>
              <dd>{{ form.deliveryNotes || '暂未填写' }}</dd>
            </div>
          </dl>
          <p>提交后进入待审核状态。审核期间如需修改，请先撤回到草稿。</p>
        </div>

        <footer class="publish-actions">
          <button v-if="step > 1" class="button button-ghost" type="button" @click="step -= 1">
            上一步
          </button>
          <button
            class="button button-secondary"
            type="button"
            :disabled="saving"
            @click="saveDraft()"
          >
            保存草稿
          </button>
          <button v-if="step < 3" class="button button-primary" type="button" @click="step += 1">
            下一步
          </button>
          <button
            v-else
            class="button button-primary publish-submit"
            type="submit"
            :disabled="saving || !canSubmit"
          >
            {{ saving ? '正在提交…' : '提交审核' }}
          </button>
        </footer>
      </form>
    </div>
  </section>
</template>
