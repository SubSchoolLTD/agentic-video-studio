<script setup lang="ts">
withDefaults(defineProps<{
  interactive?: boolean
  padded?: boolean
}>(), {
  interactive: false,
  padded: true,
})
</script>

<template>
  <section class="app-card" :class="{ 'app-card--interactive': interactive, 'app-card--plain': !padded }">
    <slot />
  </section>
</template>

