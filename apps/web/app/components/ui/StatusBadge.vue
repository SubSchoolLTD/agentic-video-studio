<script setup lang="ts">
const props = defineProps<{ status: string }>()
const normalized = computed(() => props.status.toLowerCase().replaceAll(' ', '_'))
const label = computed(() => props.status.replaceAll('_', ' '))
</script>

<template>
  <span class="status-badge" :class="`status-badge--${normalized}`">
    <span class="status-badge__dot" />
    {{ label }}
  </span>
</template>

