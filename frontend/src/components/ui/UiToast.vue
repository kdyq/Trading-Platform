<script setup lang="ts">
withDefaults(defineProps<{ message: string; tone?: 'success' | 'error' }>(), { tone: 'success' })
</script>

<template>
  <div v-if="message" class="ui-toast" :class="`ui-toast-${tone}`" role="status" aria-live="polite">
    {{ message }}
  </div>
</template>
