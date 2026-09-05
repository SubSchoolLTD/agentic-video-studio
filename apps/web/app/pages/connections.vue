<script setup lang="ts">
import { CheckCircle2, KeyRound, Link2, LockKeyhole, RefreshCw, ShieldCheck, Unplug, X } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { show } = useToast()
const route = useRoute()
const busyProvider = ref('')
const selectedProvider = ref<any>(null)
const loginStep = ref<'credentials' | 'verification'>('credentials')
const verificationConnectionId = ref('')
const credentials = reactive({ username: '', password: '', code: '' })
const loginError = ref('')
const { data, refresh } = await useAsyncData(
  'connections',
  () => api<any>(`/v1/projects/${projectId.value}/connections`),
  { default: () => ({ items: [] }) },
)

const descriptions: Record<string, string> = {
  youtube: 'Connect Google once, then upload to the selected YouTube channel.',
  instagram: 'Sign in to Instagram here once. Framewise keeps only the encrypted browser session and uploads through the regular web composer.',
  tiktok: 'Sign in to TikTok here once. Framewise publishes through TikTok Studio just as you would upload the video manually.',
}

function capabilityLabels(item: any): string[] {
  const capabilities = item.capabilities || {}
  const labels: string[] = []
  if (capabilities.publish) labels.push('Direct publishing')
  if (capabilities.schedule) labels.push('Scheduling')
  if (capabilities.connection_mode === 'playwright_web') labels.push('Browser session')
  if (capabilities.autopublish) labels.push('Autopilot eligible')
  if (Array.isArray(capabilities.privacy)) labels.push(`Privacy: ${capabilities.privacy.map((value: string) => value.replaceAll('_', ' ').toLowerCase()).join(', ')}`)
  if (Array.isArray(capabilities.metrics) && capabilities.metrics.length) labels.push('Performance metrics')
  if (capabilities.requires_per_post_consent) labels.push('Consent per post')
  return labels
}

onMounted(async () => {
  const provider = String(route.query.connected || '')
  if (provider) {
    await refresh()
    show(`${provider[0]?.toUpperCase()}${provider.slice(1)} connected`, 'The account is ready for publication.', 'success')
    await navigateTo('/connections', { replace: true })
  }
})

function closeLogin() {
  loginError.value = ''
  selectedProvider.value = null
  loginStep.value = 'credentials'
  verificationConnectionId.value = ''
  credentials.username = ''
  credentials.password = ''
  credentials.code = ''
}

async function connect(item: any) {
  loginError.value = ''
  if (item.provider === 'instagram' || item.provider === 'tiktok') {
    selectedProvider.value = item
    loginStep.value = item.status === 'verification_required' ? 'verification' : 'credentials'
    verificationConnectionId.value = item.status === 'verification_required' ? item.id : ''
    credentials.username = item.status === 'verification_required' ? String(item.display_name || '').replace(/^@/, '') : ''
    return
  }
  busyProvider.value = item.provider
  const authWindow = window.open('about:blank', `${item.provider}-oauth`)
  if (authWindow) authWindow.opener = null
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/connections/${item.provider}/authorize`, { method: 'POST' })
    if (result.authorize_url) {
      if (authWindow) authWindow.location.replace(result.authorize_url)
      else window.location.assign(result.authorize_url)
      return
    }
    authWindow?.close()
    show(`${item.display_name} connected`, 'The account is ready for publication.', 'success')
    await refresh()
  }
  catch (error: any) {
    authWindow?.close()
    show('Connection failed', error.message, 'error')
  }
  finally {
    busyProvider.value = ''
  }
}

async function submitCredentials() {
  if (!selectedProvider.value) return
  loginError.value = ''
  busyProvider.value = selectedProvider.value.provider
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/connections/${selectedProvider.value.provider}/browser-login`, {
      method: 'POST',
      retry: 0,
      body: { username: credentials.username, password: credentials.password },
    })
    credentials.password = ''
    if (result.verification_required) {
      verificationConnectionId.value = result.id
      loginStep.value = 'verification'
      show('Verification required', 'Enter the one-time code sent by the provider.', 'info')
      return
    }
    show(`${selectedProvider.value.provider === 'instagram' ? 'Instagram' : 'TikTok'} connected`, 'Only the encrypted browser session was saved. Your password was discarded.', 'success')
    closeLogin()
    await refresh()
  }
  catch (error: any) {
    credentials.password = ''
    loginError.value = error.message
  }
  finally {
    busyProvider.value = ''
  }
}

async function submitVerification() {
  if (!verificationConnectionId.value) return
  loginError.value = ''
  busyProvider.value = selectedProvider.value?.provider || 'verification'
  try {
    await api(`/v1/connections/${verificationConnectionId.value}/browser-verify`, {
      method: 'POST',
      retry: 0,
      body: { code: credentials.code },
    })
    credentials.code = ''
    show('Account connected', 'The verified browser session is ready for publication.', 'success')
    closeLogin()
    await refresh()
  }
  catch (error: any) {
    credentials.code = ''
    loginError.value = error.message
  }
  finally {
    busyProvider.value = ''
  }
}

async function disconnect(item: any) {
  if (item.id.startsWith('unconfigured_')) return
  try {
    await api(`/v1/connections/${item.id}`, { method: 'DELETE' })
    show(`${item.display_name} disconnected`, 'The stored browser session or authorization was revoked.', 'success')
    await refresh()
  }
  catch (error: any) {
    show('Could not disconnect', error.message, 'error')
  }
}
</script>

<template>
  <div>
    <UiPageHeader
      eyebrow="Social publishing"
      title="Connections"
      description="Sign in once, then Framewise uploads through the same provider website you would use manually. Downloads never require a connector."
    >
      <button class="button" @click="() => refresh()"><RefreshCw :size="15" /> Refresh status</button>
    </UiPageHeader>

    <div class="connection-grid">
      <UiAppCard v-for="item in data.items" :key="item.id" class="connection-card">
        <div class="connection-card__top">
          <span class="provider-mark" :class="`provider-mark--${item.provider}`"><Link2 :size="21" /></span>
          <UiStatusBadge :status="item.status" />
        </div>
        <div>
          <h2>{{ item.display_name }}</h2>
          <p>{{ descriptions[item.provider] }}</p>
        </div>
        <div class="capability-list">
          <span v-for="capability in capabilityLabels(item)" :key="capability">
            <CheckCircle2 :size="12" /> {{ capability }}
          </span>
        </div>
        <div class="connection-card__actions">
          <button
            class="button button--primary"
            :disabled="busyProvider === item.provider"
            @click="connect(item)"
          >
            <KeyRound :size="14" />
            {{ busyProvider === item.provider ? 'Checking…' : item.status === 'not_connected' || item.status === 'revoked' ? 'Connect' : item.status === 'verification_required' ? 'Enter code' : 'Sign in again' }}
          </button>
          <button v-if="!item.id.startsWith('unconfigured_')" class="button button--danger" @click="disconnect(item)">
            <Unplug :size="14" /> Disconnect
          </button>
        </div>
      </UiAppCard>
    </div>

    <UiAppCard class="security-card">
      <ShieldCheck :size="22" />
      <div><strong>Passwords are never stored</strong><span>Credentials and one-time codes live only for the current sign-in request. The reusable browser session is encrypted before it is stored in the tenant-isolated database.</span></div>
    </UiAppCard>

    <div v-if="selectedProvider" class="modal-backdrop" @click.self="closeLogin">
      <form class="modal login-modal" @submit.prevent="loginStep === 'credentials' ? submitCredentials() : submitVerification()">
        <div class="modal__header">
          <div><h2>Connect {{ selectedProvider.provider === 'instagram' ? 'Instagram' : 'TikTok' }}</h2><p>Regular provider sign-in, automated by a private Playwright browser.</p></div>
          <button type="button" class="icon-button icon-button--plain" aria-label="Close" @click="closeLogin"><X :size="18" /></button>
        </div>
        <div class="modal__body">
          <div class="login-security"><LockKeyhole :size="18" /><span>{{ loginStep === 'credentials' ? 'Your password is sent to the temporary browser and discarded as soon as this request finishes.' : 'The code is submitted to the existing temporary provider session and is never stored.' }}</span></div>
          <div v-if="loginStep === 'credentials'" class="form-grid">
            <div class="field field--full"><label for="social-username">Username or email</label><input id="social-username" v-model="credentials.username" autocomplete="username" required /></div>
            <div class="field field--full"><label for="social-password">Password</label><input id="social-password" v-model="credentials.password" type="password" autocomplete="current-password" required /></div>
          </div>
          <div v-else class="field"><label for="social-code">One-time verification code</label><input id="social-code" v-model="credentials.code" inputmode="numeric" autocomplete="one-time-code" minlength="4" maxlength="16" required /></div>
          <p v-if="loginError" class="auth-error" role="alert">{{ loginError }}</p>
        </div>
        <div class="modal__footer">
          <button type="button" class="button" @click="closeLogin">Cancel</button>
          <button class="button button--primary" :disabled="Boolean(busyProvider)"><KeyRound :size="14" /> {{ busyProvider ? 'Signing in…' : loginStep === 'credentials' ? 'Sign in securely' : 'Verify account' }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.connection-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.connection-card{display:grid;gap:17px}.connection-card__top,.connection-card__actions{display:flex;align-items:center;justify-content:space-between;gap:9px}.provider-mark{display:grid;width:45px;height:45px;place-items:center;border-radius:13px;background:var(--primary-50);color:var(--primary-600)}.provider-mark--youtube{background:var(--red-soft);color:var(--red)}.connection-card h2{margin:0 0 5px;font-family:var(--font-display);font-size:17px}.connection-card p{margin:0;color:var(--muted);font-size:10px;line-height:1.55}.capability-list{display:flex;flex-wrap:wrap;gap:6px;min-height:52px}.capability-list span{display:flex;align-items:center;gap:4px;padding:5px 7px;border-radius:7px;background:var(--surface-soft);color:var(--muted-strong);font-size:8px;text-transform:capitalize}.connection-card__actions{justify-content:flex-start}.security-card{display:flex;align-items:center;gap:11px;margin-top:15px;color:var(--green)}.security-card div{display:grid;gap:2px}.security-card strong{color:var(--ink);font-size:11px}.security-card span{color:var(--muted);font-size:9px}.login-modal{width:min(520px,100%)}.login-security{display:flex;gap:9px;align-items:flex-start;margin-bottom:15px;padding:10px;border-radius:9px;background:var(--green-soft);color:var(--green)}.login-security span{font-size:9px;line-height:1.5}@media(max-width:820px){.connection-grid{grid-template-columns:1fr}}
</style>
