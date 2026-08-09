<script setup lang="ts">
defineProps<{ value: number }>()
</script>

<template>
  <div class="progress-bar" role="progressbar" :aria-valuenow="Math.round(value * 100)" aria-valuemin="0" aria-valuemax="100">
    <span :style="{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }" />
  </div>
</template>

