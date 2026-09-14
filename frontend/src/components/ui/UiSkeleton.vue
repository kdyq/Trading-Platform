<script setup lang="ts">
withDefaults(defineProps<{ width?: string; height?: string; rounded?: boolean }>(), {
  width: '100%',
  height: '1rem',
  rounded: false,
})
</script>

<template>
  <span
    class="ui-skeleton"
    :class="{ 'ui-skeleton-rounded': rounded }"
    :style="{ width, height }"
    aria-hidden="true"
  />
</template>
