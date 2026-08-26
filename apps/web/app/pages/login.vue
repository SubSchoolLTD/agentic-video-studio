<script setup lang="ts">
import { ArrowRight, Clapperboard, LockKeyhole } from 'lucide-vue-next'

const route = useRoute()
const auth = useAuth()
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const hydrated = ref(false)

onMounted(() => { hydrated.value = true })

useHead({ title: 'Sign in — Framewise', meta: [{ name: 'robots', content: 'noindex, nofollow' }] })

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    const target = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/app'
    await navigateTo(target)
  }
  catch (reason: any) {
    error.value = reason?.data?.error?.message || reason?.data?.detail || 'Email or password is incorrect.'
  }
  finally { loading.value = false }
}

async function googleCredential(credential: string) {
  loading.value = true
  error.value = ''
  try {
    const payload = await auth.loginWithGoogle(credential)
    await navigateTo(payload.user?.onboarding_complete === false ? '/onboarding' : '/app')
  }
  catch (reason: any) { error.value = reason?.data?.error?.message || reason?.data?.detail || 'Google sign-in failed.' }
  finally { loading.value = false }
}
</script>

<template>
  <main class="auth-layout" :data-hydrated="hydrated">
    <section class="auth-story">
      <div class="auth-brand"><span><Clapperboard :size="22" /></span><strong>Framewise</strong></div>
      <div><span class="auth-kicker">Agentic video studio</span><h1>Your projects stay yours.</h1><p>Research, generate, review and publish evidence-backed video in an isolated workspace.</p></div>
      <div class="auth-trust"><LockKeyhole :size="17" /><span>Private organization data · signed media links · audited AI usage</span></div>
    </section>
    <section class="auth-panel">
      <form class="auth-card" @submit.prevent="submit">
        <div><span class="eyebrow">Welcome back</span><h2>Sign in to Framewise</h2><p>Use the account linked to your organization.</p></div>
        <GoogleSignInButton @credential="googleCredential" @error="error = $event" />
        <div class="auth-divider"><span>or use email</span></div>
        <label>Email<input v-model="email" name="email" type="email" autocomplete="email" required placeholder="you@company.com"></label>
        <label>Password<input v-model="password" name="password" type="password" autocomplete="current-password" required minlength="10" placeholder="Your password"></label>
        <div v-if="error" class="auth-error" role="alert">{{ error }}</div>
        <div class="auth-inline"><NuxtLink to="/forgot-password">Forgot password?</NuxtLink></div>
        <button class="button button--primary auth-submit" type="submit" :disabled="loading">{{ loading ? 'Signing in…' : 'Sign in' }} <ArrowRight :size="16" /></button>
        <p class="auth-switch">New to Framewise? <NuxtLink to="/register">Create a private workspace</NuxtLink></p>
      </form>
    </section>
  </main>
</template>
