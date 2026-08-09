<script setup lang="ts">
useHead({
  htmlAttrs: { lang: 'en' },
  bodyAttrs: { class: 'app-body' },
})
</script>

<template>
  <AppShell>
    <NuxtPage />
  </AppShell>
  <ToastHost />
</template>

