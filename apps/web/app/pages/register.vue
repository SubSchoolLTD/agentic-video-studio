<script setup lang="ts">
import { ArrowRight, CheckCircle2, Clapperboard, ShieldCheck } from 'lucide-vue-next'

const config = useRuntimeConfig()
const form = reactive({ email: '', password: '', display_name: '', organization_name: '', project_name: '', website_url: '', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' })
const loading = ref(false)
const error = ref('')
const complete = ref(false)
const emailDelivered = ref(true)
const hydrated = ref(false)

onMounted(() => { hydrated.value = true })

useHead({ title: 'Create account — Framewise', meta: [{ name: 'robots', content: 'noindex, nofollow' }] })

async function submit() {
  loading.value = true
  error.value = ''
  try {
    const result = await $fetch<{ email_sent?: boolean }>('/v1/auth/register', { baseURL: config.public.apiBase, method: 'POST', body: form })
    emailDelivered.value = result.email_sent !== false
    complete.value = true
  }
  catch (reason: any) {
    error.value = reason?.data?.error?.message || reason?.data?.detail || 'The account could not be created.'
  }
  finally { loading.value = false }
}
</script>

<template>
  <main class="auth-layout auth-layout--register" :data-hydrated="hydrated">
    <section class="auth-story">
      <div class="auth-brand"><span><Clapperboard :size="22" /></span><strong>Framewise</strong></div>
      <div><span class="auth-kicker">A workspace for your brand</span><h1>From a website to a production system.</h1><p>We use your project details to build a private brand profile. Nothing from another customer is visible in your workspace.</p></div>
      <ul class="auth-benefits"><li><ShieldCheck :size="17" /> Tenant-isolated projects and media</li><li><CheckCircle2 :size="17" /> No subscription · top up from $12 when needed</li><li><CheckCircle2 :size="17" /> Real Parallel and Google AI pipeline</li></ul>
    </section>
    <section class="auth-panel">
      <div v-if="complete" class="auth-card auth-card--success">
        <span class="auth-success-icon"><CheckCircle2 :size="28" /></span><h2>{{ emailDelivered ? 'Check your email' : 'Workspace created' }}</h2><p v-if="emailDelivered">We sent a one-time confirmation link to <strong>{{ form.email }}</strong>. It activates your private workspace.</p><p v-else>Your workspace was created, but the confirmation email could not be sent. Please contact support before trying to register the same address again.</p><NuxtLink class="button button--primary auth-submit" to="/login">Back to sign in</NuxtLink>
      </div>
      <form v-else class="auth-card" @submit.prevent="submit">
        <div><span class="eyebrow">Start creating</span><h2>Create your account</h2><p>Your first organization and project are created together.</p></div>
        <div class="auth-grid"><label>Your name<input v-model="form.display_name" name="name" autocomplete="name" required minlength="2" placeholder="Alex Morgan"></label><label>Work email<input v-model="form.email" name="email" type="email" autocomplete="email" required placeholder="you@company.com"></label></div>
        <label>Password<input v-model="form.password" name="password" type="password" autocomplete="new-password" required minlength="10" placeholder="At least 10 characters"><small>Use at least 10 characters.</small></label>
        <div class="auth-divider"><span>Workspace</span></div>
        <div class="auth-grid"><label>Organization<input v-model="form.organization_name" name="organization" required minlength="2" placeholder="Acme Studio"></label><label>Project name<input v-model="form.project_name" name="project" required minlength="2" placeholder="Acme Product"></label></div>
        <label>Project website<input v-model="form.website_url" name="website" type="url" required placeholder="https://example.com"><small>Used by Parallel to prepare your brand context after activation.</small></label>
        <div v-if="error" class="auth-error" role="alert">{{ error }}</div>
        <button class="button button--primary auth-submit" type="submit" :disabled="loading">{{ loading ? 'Creating workspace…' : 'Create private workspace' }} <ArrowRight :size="16" /></button>
        <p class="auth-switch">Already have an account? <NuxtLink to="/login">Sign in</NuxtLink></p>
      </form>
    </section>
  </main>
</template>
