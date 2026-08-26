<script setup lang="ts">
import { ArrowRight, CheckCircle2, Clapperboard, ShieldCheck } from 'lucide-vue-next'

const config = useRuntimeConfig()
const auth = useAuth()
const form = reactive({ email: '', password: '', display_name: '', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' })
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

async function googleCredential(credential: string) {
  loading.value = true
  error.value = ''
  try {
    const payload = await auth.loginWithGoogle(credential)
    await navigateTo(payload.user?.onboarding_complete === false ? '/onboarding' : '/app')
  }
  catch (reason: any) { error.value = reason?.data?.error?.message || reason?.data?.detail || 'Google sign-up failed.' }
  finally { loading.value = false }
}
</script>

<template>
  <main class="auth-layout auth-layout--register" :data-hydrated="hydrated">
    <section class="auth-story">
      <div class="auth-brand"><span><Clapperboard :size="22" /></span><strong>Framewise</strong></div>
      <div><span class="auth-kicker">A workspace for your brand</span><h1>From a website to a production system.</h1><p>Create the account first. The guided setup then researches your project and prepares the production system.</p></div>
      <ul class="auth-benefits"><li><ShieldCheck :size="17" /> Tenant-isolated projects and media</li><li><CheckCircle2 :size="17" /> No subscription · top up from $12 when needed</li><li><CheckCircle2 :size="17" /> Real Parallel and Google AI pipeline</li></ul>
    </section>
    <section class="auth-panel">
      <div v-if="complete" class="auth-card auth-card--success">
        <span class="auth-success-icon"><CheckCircle2 :size="28" /></span><h2>{{ emailDelivered ? 'Check your email' : 'Workspace created' }}</h2><p v-if="emailDelivered">We sent a one-time confirmation link to <strong>{{ form.email }}</strong>. It activates your private workspace.</p><p v-else>Your workspace was created, but the confirmation email could not be sent. Please contact support before trying to register the same address again.</p><NuxtLink class="button button--primary auth-submit" to="/login">Back to sign in</NuxtLink>
      </div>
      <form v-else class="auth-card" @submit.prevent="submit">
        <div><span class="eyebrow">Start creating</span><h2>Create your account</h2><p>Continue with Google or use your email. Both methods link to the same account.</p></div>
        <GoogleSignInButton @credential="googleCredential" @error="error = $event" />
        <div class="auth-divider"><span>or use email</span></div>
        <div class="auth-grid"><label>Your name<input v-model="form.display_name" name="name" autocomplete="name" required minlength="2" placeholder="Alex Morgan"></label><label>Work email<input v-model="form.email" name="email" type="email" autocomplete="email" required placeholder="you@company.com"></label></div>
        <label>Password<input v-model="form.password" name="password" type="password" autocomplete="new-password" required minlength="10" placeholder="At least 10 characters"><small>Use at least 10 characters.</small></label>
        <div v-if="error" class="auth-error" role="alert">{{ error }}</div>
        <button class="button button--primary auth-submit" type="submit" :disabled="loading">{{ loading ? 'Creating account…' : 'Create account' }} <ArrowRight :size="16" /></button>
        <p class="auth-switch">Already have an account? <NuxtLink to="/login">Sign in</NuxtLink></p>
      </form>
    </section>
  </main>
</template>
