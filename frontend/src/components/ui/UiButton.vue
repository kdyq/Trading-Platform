<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'danger'
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    busy?: boolean
  }>(),
  { variant: 'primary', type: 'button', disabled: false, busy: false },
)

defineEmits<{ click: [event: MouseEvent] }>()
</script>

<template>
  <button
    class="ui-button"
    :class="`ui-button-${variant}`"
    :type="type"
    :disabled="disabled || busy"
    :aria-busy="busy"
    @click="$emit('click', $event)"
  >
    <slot>{{ busy ? '处理中' : '确认' }}</slot>
  </button>
</template>
