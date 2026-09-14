<script setup lang="ts">
defineProps<{
  id: string
  label: string
  help?: string
  error?: string
}>()
</script>

<template>
  <div class="ui-field" :data-invalid="Boolean(error)">
    <label :for="id">{{ label }}</label>
    <slot :describedby="error ? `${id}-error` : help ? `${id}-help` : undefined" />
    <small v-if="help && !error" :id="`${id}-help`">{{ help }}</small>
    <small v-if="error" :id="`${id}-error`" class="ui-field-error" role="alert">
      {{ error }}
    </small>
  </div>
</template>
