<script setup lang="ts">
const route = useRoute()
const publicRoutes = ['/', '/login', '/register', '/verify-email', '/forgot-password', '/reset-password']
const isPublic = computed(() => publicRoutes.includes(route.path))

useHead({
  htmlAttrs: { lang: 'en' },
  bodyAttrs: { class: 'app-body' },
})
</script>

<template>
  <NuxtPage v-if="isPublic" />
  <AppShell v-else>
    <NuxtPage />
  </AppShell>
  <ToastHost />
</template>
