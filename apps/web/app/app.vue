<script setup lang="ts">
const route = useRoute()
const publicRoutes = ['/', '/login', '/register', '/verify-email', '/forgot-password', '/reset-password']
const isPublic = computed(() => publicRoutes.includes(route.path))
const isAdmin = computed(() => route.path.startsWith('/admin'))

useHead({
  htmlAttrs: { lang: 'en' },
  bodyAttrs: { class: 'app-body' },
})
</script>

<template>
  <NuxtPage v-if="isPublic" />
  <AdminShell v-else-if="isAdmin">
    <NuxtPage />
  </AdminShell>
  <AppShell v-else>
    <NuxtPage />
  </AppShell>
  <ToastHost />
</template>
