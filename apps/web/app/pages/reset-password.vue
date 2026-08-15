<script setup lang="ts">
import { CheckCircle2, Clapperboard } from 'lucide-vue-next'

const route = useRoute()
const config = useRuntimeConfig()
const password = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const done = ref(false)
const error = ref('')
useHead({ title: 'Choose a new password — Framewise', meta: [{ name: 'robots', content: 'noindex, nofollow' }] })
async function submit() { if (password.value !== confirmPassword.value) { error.value = 'Passwords do not match.'; return }; loading.value = true; error.value = ''; try { await $fetch('/v1/auth/password-reset/confirm', { baseURL: config.public.apiBase, method: 'POST', body: { token: route.query.token, password: password.value } }); done.value = true } catch (reason: any) { error.value = reason?.data?.error?.message || 'The reset link is invalid or expired.' } finally { loading.value = false } }
</script>

<template><main class="auth-centered"><div class="auth-brand"><span><Clapperboard :size="22" /></span><strong>Framewise</strong></div><form class="auth-card auth-card--status" @submit.prevent="submit"><CheckCircle2 v-if="done" class="status-success" :size="30" /><h2>{{ done ? 'Password updated' : 'Choose a new password' }}</h2><p>{{ done ? 'All previous sessions were revoked. Sign in with your new password.' : 'Use at least 10 characters. The link can only be used once.' }}</p><template v-if="!done"><label>New password<input v-model="password" type="password" autocomplete="new-password" required minlength="10"></label><label>Confirm password<input v-model="confirmPassword" type="password" autocomplete="new-password" required minlength="10"></label><div v-if="error" class="auth-error">{{ error }}</div><button class="button button--primary auth-submit" :disabled="loading">{{ loading ? 'Updating…' : 'Update password' }}</button></template><NuxtLink v-else class="button button--primary" to="/login">Sign in</NuxtLink></form></main></template>
