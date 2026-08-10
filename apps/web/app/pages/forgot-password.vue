<script setup lang="ts">
import { ArrowLeft, CheckCircle2, Clapperboard } from 'lucide-vue-next'

const config = useRuntimeConfig()
const email = ref('')
const sent = ref(false)
const loading = ref(false)
async function submit() { loading.value = true; await $fetch('/v1/auth/password-reset/request', { baseURL: config.public.apiBase, method: 'POST', body: { email: email.value } }).catch(() => undefined); loading.value = false; sent.value = true }
</script>

<template><main class="auth-centered"><div class="auth-brand"><span><Clapperboard :size="22" /></span><strong>Framewise</strong></div><form class="auth-card auth-card--status" @submit.prevent="submit"><CheckCircle2 v-if="sent" class="status-success" :size="30" /><h2>{{ sent ? 'Check your email' : 'Reset your password' }}</h2><p>{{ sent ? 'If the address belongs to an account, we sent a one-time reset link.' : 'Enter your account email and we will send a secure reset link.' }}</p><label v-if="!sent">Email<input v-model="email" type="email" autocomplete="email" required placeholder="you@company.com"></label><button v-if="!sent" class="button button--primary auth-submit" :disabled="loading">{{ loading ? 'Sending…' : 'Send reset link' }}</button><NuxtLink class="auth-back" to="/login"><ArrowLeft :size="14" /> Back to sign in</NuxtLink></form></main></template>
