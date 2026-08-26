<script setup lang="ts">
const emit = defineEmits<{ credential: [value: string], error: [message: string] }>()
const config = useRuntimeConfig()
const target = ref<HTMLElement | null>(null)

function renderButton() {
  const google = (window as any).google
  if (!google?.accounts?.id || !target.value || !config.public.googleClientId) return
  google.accounts.id.initialize({
    client_id: config.public.googleClientId,
    callback: (response: { credential?: string }) => response.credential
      ? emit('credential', response.credential)
      : emit('error', 'Google did not return a sign-in credential.'),
    auto_select: false,
    cancel_on_tap_outside: true,
  })
  google.accounts.id.renderButton(target.value, {
    type: 'standard', theme: 'outline', size: 'large', shape: 'rectangular',
    text: 'continue_with', width: Math.min(380, target.value.clientWidth || 380),
  })
}

onMounted(() => {
  if (!config.public.googleClientId) return
  if ((window as any).google?.accounts?.id) return renderButton()
  const existing = document.querySelector<HTMLScriptElement>('script[data-framewise-google]')
  if (existing) {
    existing.addEventListener('load', renderButton, { once: true })
    return
  }
  const script = document.createElement('script')
  script.src = 'https://accounts.google.com/gsi/client'
  script.async = true
  script.defer = true
  script.dataset.framewiseGoogle = 'true'
  script.addEventListener('load', renderButton, { once: true })
  script.addEventListener('error', () => emit('error', 'Google sign-in could not be loaded.'), { once: true })
  document.head.appendChild(script)
})
</script>

<template>
  <div v-if="config.public.googleClientId" ref="target" class="google-sign-in" data-testid="google-sign-in" />
</template>

<style scoped>
.google-sign-in{display:flex;min-height:44px;justify-content:center;overflow:hidden}
</style>
