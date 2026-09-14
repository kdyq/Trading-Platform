<script setup lang="ts">
import { nextTick, onBeforeUnmount, watch } from 'vue'
import { ref } from 'vue'

const props = defineProps<{ open: boolean; title: string }>()
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null

function focusableElements() {
  return Array.from(
    panel.value?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? [],
  )
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    emit('close')
    return
  }
  if (event.key !== 'Tab') return
  const items = focusableElements()
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      previousFocus = document.activeElement as HTMLElement | null
      await nextTick()
      focusableElements()[0]?.focus()
      document.body.classList.add('dialog-open')
    } else {
      document.body.classList.remove('dialog-open')
      previousFocus?.focus()
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => document.body.classList.remove('dialog-open'))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop" @mousedown.self="$emit('close')">
      <section
        ref="panel"
        class="dialog-panel"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`${title}-dialog-title`"
        @keydown="onKeydown"
      >
        <header class="dialog-heading">
          <h2 :id="`${title}-dialog-title`">{{ title }}</h2>
          <button
            class="dialog-close"
            type="button"
            aria-label="关闭对话框"
            @click="$emit('close')"
          >
            关闭
          </button>
        </header>
        <slot />
      </section>
    </div>
  </Teleport>
</template>
