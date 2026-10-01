<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getCampusStatus } from '../api/campus'
import { ApiError } from '../api/client'
import {
  createSellerProduct,
  getCatalogCategories,
  getSellerProductImage,
  getProductImagePreview,
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
const legacyKey = 'shiguang-product-draft:new'
const legacyAvailable = ref(Boolean(localStorage.getItem(legacyKey)))
const uploadController = new AbortController()
let autoSaveTimer: number | undefined
let applyingProduct = false
let disposed = false

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
type LocalDraft = {
  step?: number
  productId?: string
  form?: Partial<typeof form>
  images?: Array<ProductImageReference & { name?: string }>
}
const productRecovery = ref<{ key: string; draft: LocalDraft } | null>(null)
const conditionOptions = [
  ['new', '全新'],
  ['like_new', '几乎全新'],
  ['good', '轻微使用'],
  ['fair', '使用痕迹'],
]

const flatCategories = computed(() =>
  categories.value.flatMap((category) => [category, ...category.children]),
)
const localKey = computed(
  () => `shiguang-product-draft:${auth.user?.id}:${productId.value ?? 'new'}`,
)
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
  applyingProduct = true
  try {
    images.value.forEach((image) => {
      if (image.previewUrl.startsWith('blob:')) URL.revokeObjectURL(image.previewUrl)
    })
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
    const previews = await Promise.all(
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
    if (disposed) {
      previews.forEach((image) => URL.revokeObjectURL(image.previewUrl))
      return
    }
    images.value = previews
    await nextTick()
  } finally {
    applyingProduct = false
  }
}

function storeLocal() {
  if (disposed) return
  localStorage.setItem(
    localKey.value,
    JSON.stringify({
      step: step.value,
      form: { ...form },
      productId: productId.value,
      images: imageReferences(),
    }),
  )
}

function imageReferences() {
  return images.value.map(({ kind, id, name }) => ({ kind, id, name }))
}

async function restoreDraft(draft: LocalDraft) {
  if (!auth.accessToken || disposed) return false
  window.clearTimeout(autoSaveTimer)
  uploading.value = true
  applyingProduct = true
  let missingImages = false
  try {
    if (Array.isArray(draft.images)) {
      const restored: DraftImage[] = []
      let retryRequired = false
      for (const reference of draft.images.slice(0, 8)) {
        if (disposed) break
        const existing = images.value.find(
          (image) => image.kind === reference.kind && image.id === reference.id,
        )
        if (existing) restored.push(existing)
        else if (reference.kind === 'upload') {
          try {
            const blob = await getProductImagePreview(auth.accessToken, reference.id)
            if (!disposed) {
              restored.push({
                kind: 'upload',
                id: reference.id,
                name: reference.name ?? '缓存图片',
                previewUrl: URL.createObjectURL(blob),
              })
            }
          } catch (error) {
            if (error instanceof ApiError && [404, 410].includes(error.status ?? 0)) {
              missingImages = true
            } else {
              retryRequired = true
              break
            }
          }
        } else missingImages = true
      }
      if (disposed || retryRequired) {
        restored.forEach((image) => {
          if (!images.value.includes(image)) URL.revokeObjectURL(image.previewUrl)
        })
        if (!disposed) errorMessage.value = '缓存图片暂时无法加载，草稿已保留，请稍后重试恢复。'
        return false
      }
      const candidates = missingImages ? [...images.value, ...restored] : restored
      const nextImages = candidates
        .filter(
          (image, index) =>
            candidates.findIndex((item) => item.kind === image.kind && item.id === image.id) ===
            index,
        )
        .slice(0, 8)
      images.value.forEach((image) => {
        if (!nextImages.includes(image)) URL.revokeObjectURL(image.previewUrl)
      })
      restored.forEach((image) => {
        if (!images.value.includes(image) && !nextImages.includes(image)) {
          URL.revokeObjectURL(image.previewUrl)
        }
      })
      images.value = nextImages
    }
    if (disposed) return false
    Object.assign(form, draft.form ?? {})
    step.value = Math.min(3, Math.max(1, draft.step ?? 1))
    await nextTick()
  } finally {
    applyingProduct = false
    uploading.value = false
  }
  if (disposed) return false
  errorMessage.value = missingImages
    ? '部分缓存图片已过期或不可恢复，已保留服务器图片。请检查当前图片，仅补传缺少的图片后保存。'
    : ''
  storeLocal()
  if (productId.value && !missingImages) {
    autoSaveTimer = window.setTimeout(() => void saveDraft(false), 1200)
  }
  return true
}

async function restoreLegacy() {
  if (
    !auth.accessToken ||
    saving.value ||
    uploading.value ||
    productId.value ||
    route.name !== 'product-create'
  )
    return
  try {
    const saved = JSON.parse(localStorage.getItem(legacyKey) ?? '{}') as LocalDraft
    if (saved.productId) {
      const product = await getSellerProduct(auth.accessToken, saved.productId)
      await applyProduct(product)
      if (disposed) return
      await router.replace(`/sell/${product.id}`)
    }
    if (!(await restoreDraft(saved))) {
      if (!disposed) productRecovery.value = { key: legacyKey, draft: saved }
      return
    }
    if (disposed) return
    storeLocal()
    discardLegacy()
  } catch {
    errorMessage.value = '旧草稿无法恢复，或不属于当前账户。请从“我的发布”查找已同步商品。'
  }
}

function discardLegacy() {
  localStorage.removeItem(legacyKey)
  legacyAvailable.value = false
}

async function restoreLocal() {
  const key = localKey.value
  const saved = localStorage.getItem(key)
  if (!saved) return
  try {
    const draft = JSON.parse(saved) as LocalDraft
    if (!(await restoreDraft(draft)) && !disposed) productRecovery.value = { key, draft }
  } catch {
    localStorage.removeItem(key)
  }
}

function offerProductRecovery() {
  if (!productId.value) return
  const legacyProductKey = `shiguang-product-draft:${productId.value}`
  const key = localStorage.getItem(localKey.value) ? localKey.value : legacyProductKey
  const saved = localStorage.getItem(key)
  if (!saved) return
  try {
    const draft = JSON.parse(saved) as LocalDraft
    if (!draft.form || (draft.productId && draft.productId !== productId.value)) return
    const different = Object.entries(draft.form).some(([name, value]) => {
      const current = form[name as keyof typeof form]
      return name === 'price' || name === 'originalPrice'
        ? Number(value || 0) !== Number(current || 0)
        : value !== current
    })
    const imageDiff =
      Array.isArray(draft.images) &&
      JSON.stringify(draft.images.map(({ kind, id }) => ({ kind, id }))) !==
        JSON.stringify(imageReferences().map(({ kind, id }) => ({ kind, id })))
    if (different || imageDiff || key === legacyProductKey) productRecovery.value = { key, draft }
  } catch {
    localStorage.removeItem(key)
  }
}

async function restoreProductRecovery() {
  const recovery = productRecovery.value
  if (!recovery || saving.value || uploading.value) return
  if (!(await restoreDraft(recovery.draft)) || disposed) return
  if (recovery.key === legacyKey) discardLegacy()
  else localStorage.removeItem(recovery.key)
  productRecovery.value = null
  storeLocal()
}

function discardProductRecovery() {
  if (!productRecovery.value) return
  localStorage.removeItem(productRecovery.value.key)
  productRecovery.value = null
}

async function saveDraft(showFeedback = true) {
  if (
    disposed ||
    !auth.accessToken ||
    !form.categoryId ||
    !form.campusId ||
    saving.value ||
    uploading.value
  )
    return false
  window.clearTimeout(autoSaveTimer)
  saving.value = true
  errorMessage.value = ''
  const originalKey = localKey.value
  const snapshot = { step: step.value, form: { ...form }, images: imageReferences() }
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
      const previousKey = localKey.value
      product = await createSellerProduct(auth.accessToken, inputPayload())
      localStorage.setItem(
        previousKey.replace(/:new$/, `:${product.id}`),
        JSON.stringify({ ...snapshot, productId: product.id }),
      )
      localStorage.removeItem(previousKey)
      if (disposed) return false
      productId.value = product.id
      version.value = product.version
      storeLocal()
      await router.replace(`/sell/${product.id}`)
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
    localStorage.setItem(
      originalKey.replace(/:new$/, `:${product.id}`),
      JSON.stringify({
        ...snapshot,
        productId: product.id,
        images: product.images.map((image) => ({
          kind: 'existing',
          id: image.id,
          name: image.alt_text ?? '商品图片',
        })),
      }),
    )
    if (disposed) return false
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
  if (!auth.accessToken || !files.length || uploading.value || saving.value) return
  if (images.value.length + files.length > 8) {
    errorMessage.value = '每件商品最多上传 8 张图片'
    return
  }
  uploading.value = true
  window.clearTimeout(autoSaveTimer)
  errorMessage.value = ''
  try {
    for (const file of files) {
      const uploaded = await uploadProductImage(auth.accessToken, file, uploadController.signal)
      if (disposed) return
      images.value.push({
        kind: 'upload',
        id: uploaded.id,
        previewUrl: URL.createObjectURL(file),
        name: uploaded.original_filename,
      })
    }
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '图片上传失败'
  } finally {
    uploading.value = false
    target.value = ''
  }
  if (!disposed && images.value.length && !errorMessage.value) await saveDraft(false)
}

function removeImage(index: number) {
  const [removed] = images.value.splice(index, 1)
  if (removed?.previewUrl.startsWith('blob:')) URL.revokeObjectURL(removed.previewUrl)
}

async function submitProduct() {
  if (uploading.value || saving.value || !canSubmit.value) return
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
  [form, images],
  () => {
    if (applyingProduct || loading.value) return
    storeLocal()
    window.clearTimeout(autoSaveTimer)
    if (productId.value && !uploading.value && !saving.value) {
      autoSaveTimer = window.setTimeout(() => void saveDraft(false), 1200)
    }
  },
  { deep: true },
)

watch(step, () => {
  if (!loading.value && !applyingProduct) storeLocal()
})

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
    if (routeId) {
      const product = await getSellerProduct(auth.accessToken, routeId)
      if (product.appeal_report_id) {
        await router.replace(`/appeals/${product.appeal_report_id}`)
        return
      }
      await applyProduct(product)
      offerProductRecovery()
    } else await restoreLocal()
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '发布页加载失败'
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  disposed = true
  uploadController.abort()
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

      <aside
        v-if="legacyAvailable && !productId && route.name === 'product-create'"
        class="form-message"
      >
        <p>此设备有旧版草稿，未记录所属账户。确认属于你后可恢复；公用设备请直接删除。</p>
        <button
          class="button button-secondary"
          type="button"
          :disabled="saving || uploading"
          @click="restoreLegacy"
        >
          恢复我的旧草稿
        </button>
        <button class="button button-ghost" type="button" @click="discardLegacy">删除旧草稿</button>
      </aside>

      <aside v-if="productRecovery" class="form-message" role="status">
        <p>本机有未同步的草稿。请确认后恢复，或继续使用当前表单。</p>
        <button
          class="button button-secondary"
          type="button"
          :disabled="saving || uploading"
          @click="restoreProductRecovery"
        >
          {{ productId ? '恢复此商品的本机草稿' : '重试恢复本机草稿' }}
        </button>
        <button
          class="button button-ghost"
          type="button"
          :disabled="saving || uploading"
          @click="discardProductRecovery"
        >
          {{ productId ? '删除此商品的本机草稿' : '删除本机草稿' }}
        </button>
      </aside>

      <div v-if="loading" class="publish-card">正在准备发布表单…</div>
      <form v-else class="publish-card" @submit.prevent="submitProduct">
        <fieldset class="publish-fields" :disabled="saving || uploading">
          <legend class="sr-only">商品发布表单</legend>
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
                  <option
                    v-for="category in flatCategories"
                    :key="category.id"
                    :value="category.id"
                  >
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
              :disabled="saving || uploading || !canSubmit"
            >
              {{ saving ? '正在提交…' : '提交审核' }}
            </button>
          </footer>
        </fieldset>
      </form>
    </div>
  </section>
</template>
