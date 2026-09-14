<script setup lang="ts">
withDefaults(
  defineProps<{
    selected?: boolean
    tone?: 'neutral' | 'trust' | 'warning'
    interactive?: boolean
  }>(),
  { selected: false, tone: 'neutral', interactive: false },
)

defineEmits<{ click: [] }>()
</script>

<template>
  <button
    v-if="interactive"
    class="ui-chip ui-chip-button"
    :class="[`ui-chip-${tone}`, { 'is-selected': selected }]"
    type="button"
    :aria-pressed="selected"
    @click="$emit('click')"
  >
    <slot />
  </button>
  <span v-else class="ui-chip" :class="[`ui-chip-${tone}`, { 'is-selected': selected }]">
    <slot />
  </span>
</template>
