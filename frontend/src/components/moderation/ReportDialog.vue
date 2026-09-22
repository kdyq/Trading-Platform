<script setup lang="ts">
import { ref, watch } from 'vue'

import { createReport, uploadReportEvidence } from '../../api/reports'
import type { ReportItem, ReportTargetType } from '../../api/reports'
import { useAuthStore } from '../../stores/auth'
import UiButton from '../ui/UiButton.vue'
import UiDialog from '../ui/UiDialog.vue'

const props = defineProps<{
  open: boolean
  targetType: ReportTargetType
  targetId: string
  title?: string
}>()
const emit = defineEmits<{ close: []; submitted: [report: ReportItem] }>()
const auth = useAuthStore()
const reason = ref('fraud')
const details = ref('')
const evidence = ref<File | null>(null)
const busy = ref(false)
const error = ref('')

watch(
  () => props.open,
  (open) => {
    if (!open) return
    error.value = ''
  },
)

function chooseEvidence(event: Event) {
  evidence.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function submit() {
  if (!auth.accessToken || details.value.trim().length < 5 || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const report = await createReport(auth.accessToken, {
      target_type: props.targetType,
      target_id: props.targetId,
      reason_code: reason.value,
      details: details.value.trim(),
    })
    if (evidence.value) await uploadReportEvidence(auth.accessToken, report.id, evidence.value)
    details.value = ''
    evidence.value = null
    emit('submitted', report)
    emit('close')
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '举报提交失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <UiDialog :open="open" :title="title || '提交举报'" @close="$emit('close')">
    <form class="report-dialog-form" @submit.prevent="submit">
      <p>请提供客观事实。证据仅供授权审核人员查看，不会出现在通知或公开页面。</p>
      <label>
        <span>举报原因</span>
        <select v-model="reason">
          <option value="fraud">疑似欺诈</option>
          <option value="harassment">骚扰行为</option>
          <option value="spam">垃圾信息</option>
          <option value="prohibited">违禁内容</option>
          <option value="unsafe">安全风险</option>
          <option value="counterfeit">疑似假冒</option>
          <option value="no_show">交易爽约</option>
          <option value="other">其他</option>
        </select>
      </label>
      <label>
        <span>事实说明</span>
        <textarea v-model="details" minlength="5" maxlength="1000" rows="5" required />
      </label>
      <label>
        <span>证据附件（可选）</span>
        <input type="file" accept="application/pdf,image/png,image/jpeg" @change="chooseEvidence" />
        <small>支持 PDF、PNG、JPEG，最大 10 MB。</small>
      </label>
      <p v-if="error" class="report-dialog-error" role="alert">{{ error }}</p>
      <div class="report-dialog-actions">
        <UiButton type="button" variant="secondary" :disabled="busy" @click="$emit('close')">
          取消
        </UiButton>
        <UiButton type="submit" :disabled="busy || details.trim().length < 5">
          {{ busy ? '正在提交…' : '提交举报' }}
        </UiButton>
      </div>
    </form>
  </UiDialog>
</template>

<style scoped>
.report-dialog-form {
  display: grid;
  gap: 1rem;
}
.report-dialog-form > p:first-child,
.report-dialog-form small {
  color: var(--color-text-muted, #6f675f);
}
.report-dialog-form label {
  display: grid;
  gap: 0.45rem;
  font-weight: 700;
}
.report-dialog-form select,
.report-dialog-form textarea,
.report-dialog-form input {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--color-border, #ded8d0);
  border-radius: 12px;
  padding: 0.75rem;
  background: white;
  color: inherit;
  font: inherit;
}
.report-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}
.report-dialog-error {
  color: #a13b2b;
}
</style>
