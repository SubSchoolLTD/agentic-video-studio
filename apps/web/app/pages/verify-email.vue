<script setup lang="ts">
import { CheckCircle2, Clapperboard, LoaderCircle, XCircle } from 'lucide-vue-next'

const route = useRoute()
const config = useRuntimeConfig()
const auth = useAuth()
const state = ref<'loading' | 'success' | 'error'>('loading')
const message = ref('Confirming your email and preparing the workspace…')

useHead({ title: 'Verify email — Framewise', meta: [{ name: 'robots', content: 'noindex, nofollow' }] })

onMounted(async () => {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  if (!token) { state.value = 'error'; message.value = 'The verification token is missing.'; return }
  try {
    const payload = await $fetch<any>('/v1/auth/verify-email', { baseURL: config.public.apiBase, method: 'POST', body: { token } })
    auth.setSession(payload)
    state.value = 'success'
    message.value = 'Email confirmed. Your private workspace is ready.'
    setTimeout(() => void navigateTo(payload.user?.onboarding_complete === false ? '/onboarding' : '/app'), 900)
  }
  catch (reason: any) {
    state.value = 'error'
    message.value = reason?.data?.error?.message || 'This verification link is invalid or expired.'
  }
})
</script>

<template><main class="auth-centered"><div class="auth-brand"><span><Clapperboard :size="22" /></span><strong>Framewise</strong></div><section class="auth-card auth-card--status"><LoaderCircle v-if="state === 'loading'" class="spin" :size="32" /><CheckCircle2 v-else-if="state === 'success'" class="status-success" :size="32" /><XCircle v-else class="status-error" :size="32" /><h2>{{ state === 'loading' ? 'Verifying email' : state === 'success' ? 'Account activated' : 'Verification failed' }}</h2><p>{{ message }}</p><NuxtLink v-if="state === 'error'" class="button button--primary" to="/login">Return to sign in</NuxtLink></section></main></template>
