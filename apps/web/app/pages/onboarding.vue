<script setup lang="ts">
import { ArrowLeft, ArrowRight, Check, CheckCircle2, Clapperboard, Globe2, KeyRound, LoaderCircle, LockKeyhole, Sparkles, X } from 'lucide-vue-next'

definePageMeta({ layout: false })
useHead({ title: 'Set up your project — Framewise', meta: [{ name: 'robots', content: 'noindex, nofollow' }] })

const { api, projectId } = useApi()
const auth = useAuth()
const { show } = useToast()
const step = ref(0)
const loading = ref(false)
const error = ref('')
const estimatedWeeklyCost = ref<number | null>(null)
const planSaved = ref(false)
const analysisRunning = ref(false)
const website = ref('')
const busyProvider = ref('')
const selectedProvider = ref<any>(null)
const loginStep = ref<'credentials' | 'verification'>('credentials')
const verificationConnectionId = ref('')
const credentials = reactive({ username: '', password: '', code: '' })
let oauthPoll: ReturnType<typeof setInterval> | null = null
const firstBoundary = ref(20)
const secondBoundary = ref(50)
const preferences = reactive({ videos_per_week: 3, average_duration_seconds: 30, audio_quality: 'premium', automation_mode: 'research_only' })
const context = reactive({ product_essence: '', target_audience: '', problem_statement: '', solution_summary: '', product_keywords: '', problem_keywords: '', audience_interest_keywords: '' })
const mix = computed(() => ({ selling: Number(firstBoundary.value), viral: Number(secondBoundary.value) - Number(firstBoundary.value), informative: 100 - Number(secondBoundary.value) }))

watch(preferences, () => {
  planSaved.value = false
  estimatedWeeklyCost.value = null
}, { deep: true })

const { data: onboarding, refresh } = await useAsyncData('onboarding', () => api<any>(`/v1/projects/${projectId.value}/onboarding`))
const { data: connections, refresh: refreshConnections } = await useAsyncData(
  'onboarding-connections',
  () => api<any>(`/v1/projects/${projectId.value}/connections`),
  { default: () => ({ items: [] }) },
)

const channelOrder = ['youtube', 'tiktok', 'instagram']
const channels = computed(() => channelOrder.map(provider => (
  connections.value?.items?.find((item: any) => item.provider === provider) || {
    id: `unconfigured_${provider}`,
    provider,
    display_name: provider[0]?.toUpperCase() + provider.slice(1),
    status: 'not_connected',
  }
)))

function providerName(provider: string) {
  return provider === 'youtube' ? 'YouTube' : provider === 'tiktok' ? 'TikTok' : 'Instagram'
}

function isConnected(item: any) {
  return ['active', 'healthy', 'limited'].includes(String(item?.status || ''))
}

function stopOauthPolling() {
  if (oauthPoll) clearInterval(oauthPoll)
  oauthPoll = null
}

onBeforeUnmount(stopOauthPolling)

function closeLogin() {
  selectedProvider.value = null
  loginStep.value = 'credentials'
  verificationConnectionId.value = ''
  credentials.username = ''
  credentials.password = ''
  credentials.code = ''
  error.value = ''
}

async function connectChannel(item: any) {
  error.value = ''
  if (item.provider === 'instagram' || item.provider === 'tiktok') {
    selectedProvider.value = item
    loginStep.value = item.status === 'verification_required' ? 'verification' : 'credentials'
    verificationConnectionId.value = item.status === 'verification_required' ? item.id : ''
    credentials.username = item.status === 'verification_required' ? String(item.display_name || '').replace(/^@/, '') : ''
    return
  }

  busyProvider.value = item.provider
  const authWindow = window.open('about:blank', 'youtube-oauth', 'popup=yes,width=560,height=760')
  if (authWindow) authWindow.opener = null
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/connections/youtube/authorize`, { method: 'POST' })
    if (!result.authorize_url) {
      authWindow?.close()
      await refreshConnections()
      busyProvider.value = ''
      show('YouTube connected', 'The channel is ready for automatic publishing.', 'success')
      return
    }
    if (authWindow) authWindow.location.replace(result.authorize_url)
    else window.location.assign(result.authorize_url)

    stopOauthPolling()
    oauthPoll = setInterval(async () => {
      try {
        await refreshConnections()
        const youtube = connections.value?.items?.find((connection: any) => connection.provider === 'youtube')
        if (isConnected(youtube)) {
          stopOauthPolling()
          busyProvider.value = ''
          show('YouTube connected', 'The channel is ready for automatic publishing.', 'success')
        }
        else if (authWindow?.closed) {
          stopOauthPolling()
          busyProvider.value = ''
        }
      }
      catch {
        if (authWindow?.closed) {
          stopOauthPolling()
          busyProvider.value = ''
        }
      }
    }, 1500)
  }
  catch (reason: any) {
    authWindow?.close()
    error.value = reason.message
    busyProvider.value = ''
  }
}

async function submitCredentials() {
  if (!selectedProvider.value) return
  const provider = selectedProvider.value.provider
  busyProvider.value = provider
  error.value = ''
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/connections/${provider}/browser-login`, {
      method: 'POST',
      body: { username: credentials.username, password: credentials.password },
    })
    credentials.password = ''
    if (result.verification_required) {
      verificationConnectionId.value = result.id
      loginStep.value = 'verification'
      show('Verification required', 'Enter the one-time code sent by the provider.', 'info')
      return
    }
    const label = providerName(provider)
    closeLogin()
    await refreshConnections()
    show(`${label} connected`, 'Only the encrypted browser session was saved. Your password was discarded.', 'success')
  }
  catch (reason: any) {
    credentials.password = ''
    error.value = reason.message
  }
  finally { busyProvider.value = '' }
}

async function submitVerification() {
  const provider = selectedProvider.value?.provider
  if (!verificationConnectionId.value || !provider) return
  busyProvider.value = provider
  error.value = ''
  try {
    const label = providerName(provider)
    await api(`/v1/connections/${verificationConnectionId.value}/browser-verify`, {
      method: 'POST',
      body: { code: credentials.code },
    })
    closeLogin()
    await refreshConnections()
    show(`${label} connected`, 'The verified browser session is ready for automatic publishing.', 'success')
  }
  catch (reason: any) {
    credentials.code = ''
    error.value = reason.message
  }
  finally { busyProvider.value = '' }
}

function hydrateContext() {
  const value = onboarding.value?.project_context || {}
  context.product_essence = value.product_essence || ''
  context.target_audience = value.target_audience || ''
  context.problem_statement = value.problem_statement || ''
  context.solution_summary = value.solution_summary || ''
  context.product_keywords = (value.product_keywords || []).join('\n')
  context.problem_keywords = (value.problem_keywords || []).join('\n')
  context.audience_interest_keywords = (value.audience_interest_keywords || []).join('\n')
}

watch(onboarding, () => {
  if (!website.value) website.value = onboarding.value?.website_url || ''
  hydrateContext()
}, { immediate: true })

function lines(value: string) { return value.split('\n').map(item => item.trim()).filter(Boolean) }
function normalizeBoundaries(which: 'first' | 'second') {
  if (which === 'first' && Number(firstBoundary.value) > Number(secondBoundary.value)) secondBoundary.value = Number(firstBoundary.value)
  if (which === 'second' && Number(secondBoundary.value) < Number(firstBoundary.value)) firstBoundary.value = Number(secondBoundary.value)
}

async function submitWebsite() {
  loading.value = true; error.value = ''
  try {
    await api(`/v1/projects/${projectId.value}/onboarding/website`, { method: 'POST', body: { website_url: website.value } })
    analysisRunning.value = true
    step.value = 1
  }
  catch (reason: any) { error.value = reason.message }
  finally { loading.value = false }
}

async function savePreferences() {
  loading.value = true; error.value = ''
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/onboarding/preferences`, { method: 'PATCH', body: {
      selling_percent: mix.value.selling, viral_percent: mix.value.viral, informative_percent: mix.value.informative, ...preferences,
    } })
    estimatedWeeklyCost.value = result.estimated_weekly_cost_usd
    planSaved.value = true
  }
  catch (reason: any) { error.value = reason.message }
  finally { loading.value = false }
}

async function loadAnalysis() {
  loading.value = true; error.value = ''
  try {
    for (let attempt = 0; attempt < 20; attempt++) {
      await refresh()
      if (onboarding.value?.analysis?.status === 'completed') break
      if (onboarding.value?.analysis?.status === 'failed') throw new Error(onboarding.value.analysis.error || 'Website analysis failed.')
      await new Promise(resolve => setTimeout(resolve, 1500))
    }
    analysisRunning.value = onboarding.value?.analysis?.status !== 'completed'
    hydrateContext()
    step.value = 4
  }
  catch (reason: any) { error.value = reason.message }
  finally { loading.value = false }
}

async function complete() {
  loading.value = true; error.value = ''
  try {
    await api(`/v1/projects/${projectId.value}/onboarding/context`, { method: 'PATCH', body: {
      product_essence: context.product_essence,
      target_audience: context.target_audience,
      problem_statement: context.problem_statement,
      solution_summary: context.solution_summary,
      product_keywords: lines(context.product_keywords),
      problem_keywords: lines(context.problem_keywords),
      audience_interest_keywords: lines(context.audience_interest_keywords),
    } })
    const result = await api<any>(`/v1/projects/${projectId.value}/onboarding/complete`, { method: 'POST' })
    if (auth.user.value) auth.user.value.onboarding_complete = true
    await navigateTo(result.next_url || '/funding?source=onboarding')
  }
  catch (reason: any) { error.value = reason.message }
  finally { loading.value = false }
}
</script>

<template>
  <main class="onboarding-shell">
    <header><div class="auth-brand"><span><Clapperboard :size="21" /></span><strong>Framewise</strong></div><div class="step-meter"><i v-for="index in 5" :key="index" :class="{ done: index - 1 <= step }" /></div><small>Step {{ step + 1 }} of 5</small></header>
    <section class="onboarding-card">
      <template v-if="step === 0">
        <span class="onboarding-icon"><Globe2 /></span><p class="eyebrow">Project context</p><h1>What are we creating content for?</h1><p class="lead">Framewise studies your public website to understand the product, audience, problem, solution and useful research themes.</p>
        <label>Project website<input v-model="website" type="url" required placeholder="https://example.com" data-testid="onboarding-website" /></label>
        <button class="button button--primary" :disabled="loading || !website" @click="submitWebsite">{{ loading ? 'Starting analysis…' : 'Analyze website' }} <ArrowRight :size="16" /></button>
      </template>

      <template v-else-if="step === 1">
        <span class="onboarding-icon"><Sparkles /></span><p class="eyebrow">Editorial mix</p><h1>How should your content plan feel?</h1><p class="lead">Set two boundaries; the three shares always add up to 100%. Research will target this mix across each batch.</p>
        <div class="mix-summary"><div><strong>{{ mix.selling }}%</strong><span>Selling</span></div><div><strong>{{ mix.viral }}%</strong><span>Viral & entertaining</span></div><div><strong>{{ mix.informative }}%</strong><span>Informative</span></div></div>
        <div class="boundary-control"><label>End of selling share<input v-model.number="firstBoundary" type="range" min="0" max="100" @input="normalizeBoundaries('first')" /></label><label>End of viral share<input v-model.number="secondBoundary" type="range" min="0" max="100" @input="normalizeBoundaries('second')" /></label></div>
        <div class="actions"><button class="button" @click="step--"><ArrowLeft :size="15" /> Back</button><button class="button button--primary" @click="step = 2">Continue <ArrowRight :size="15" /></button></div>
      </template>

      <template v-else-if="step === 2">
        <p class="eyebrow">Production plan</p><h1>Choose a comfortable pace.</h1><p class="lead">The estimate uses your current model prices and selected sound quality. The balance guard still prevents overspend.</p>
        <div class="form-grid"><label>Videos per week<input v-model.number="preferences.videos_per_week" type="number" min="1" max="100" /></label><label>Average duration, seconds<input v-model.number="preferences.average_duration_seconds" type="number" min="8" max="3600" /></label><label>Sound quality<select v-model="preferences.audio_quality"><option value="premium">Premium · Veo native voice</option><option value="standard">Standard · Google TTS</option></select></label><label>Automation<select v-model="preferences.automation_mode"><option value="off">Off</option><option value="research_only">Research only</option><option value="scripts">Create scripts</option><option value="videos">Create videos</option><option value="publish">Publish</option></select></label></div>
        <div v-if="estimatedWeeklyCost != null" class="estimate"><strong>~${{ estimatedWeeklyCost.toFixed(2) }}/week</strong><span>Estimated from current model pricing</span></div>
        <div class="actions"><button class="button" @click="step--"><ArrowLeft :size="15" /> Back</button><button v-if="!planSaved" class="button button--primary" :disabled="loading" @click="savePreferences">{{ loading ? 'Calculating…' : 'Save & calculate' }} <ArrowRight :size="15" /></button><button v-else class="button button--primary" @click="step = 3">Continue <ArrowRight :size="15" /></button></div>
      </template>

      <template v-else-if="step === 3">
        <p class="eyebrow">Publishing</p><h1>Connect channels now or later.</h1><p class="lead">Connect each account here. YouTube opens its secure Google OAuth window; TikTok and Instagram use their regular sign-in and save only an encrypted browser session.</p>
        <div class="channel-grid">
          <button
            v-for="channel in channels"
            :key="channel.provider"
            type="button"
            class="channel-card"
            :class="{ 'channel-card--connected': isConnected(channel) }"
            :disabled="busyProvider === channel.provider"
            :aria-label="`${isConnected(channel) ? 'Reconnect' : 'Connect'} ${providerName(channel.provider)}`"
            :data-testid="`onboarding-connect-${channel.provider}`"
            @click="connectChannel(channel)"
          >
            <span><strong>{{ providerName(channel.provider) }}</strong><small>{{ isConnected(channel) ? channel.display_name : channel.provider === 'youtube' ? 'Continue with Google' : 'Sign in securely' }}</small></span>
            <span v-if="isConnected(channel)" class="connected-mark"><CheckCircle2 :size="17" /> Connected</span>
            <span v-else class="connect-mark"><KeyRound :size="16" /> {{ busyProvider === channel.provider ? 'Opening…' : 'Connect' }}</span>
          </button>
        </div>
        <p class="secondary-note"><LockKeyhole :size="14" /> Passwords and one-time codes are never stored. You can also skip this step and connect channels later.</p>
        <div class="actions"><button class="button" @click="step--"><ArrowLeft :size="15" /> Back</button><button class="button button--primary" :disabled="loading" @click="loadAnalysis">{{ loading ? 'Finishing analysis…' : 'Continue' }} <ArrowRight :size="15" /></button></div>
      </template>

      <template v-else>
        <p class="eyebrow">Review AI context</p><h1>Does this describe your project?</h1><p class="lead">Edit anything that is incomplete. This context is attached to research, candidate selection and final script review.</p>
        <div v-if="analysisRunning" class="analysis-note"><LoaderCircle class="spin" :size="16" /> Analysis is still running. You can retry or complete these fields manually.</div>
        <div class="form-grid context-grid"><label class="wide">Product essence<textarea v-model="context.product_essence" /></label><label>Target audience<textarea v-model="context.target_audience" /></label><label>Audience problem<textarea v-model="context.problem_statement" /></label><label class="wide">How the product solves it<textarea v-model="context.solution_summary" /></label><label>Product keywords · one per line<textarea v-model="context.product_keywords" /></label><label>Problem keywords · one per line<textarea v-model="context.problem_keywords" /></label><label class="wide">Audience interest keywords · one per line<textarea v-model="context.audience_interest_keywords" /></label></div>
        <div class="actions"><button class="button" @click="step--"><ArrowLeft :size="15" /> Back</button><button class="button button--primary" :disabled="loading || !context.product_essence || !context.target_audience || !context.problem_statement || !context.solution_summary" data-testid="complete-onboarding" @click="complete">{{ loading ? 'Saving…' : 'Finish setup' }} <Check :size="15" /></button></div>
      </template>
      <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
    </section>

    <div v-if="selectedProvider" class="modal-backdrop" @click.self="closeLogin">
      <form class="modal login-modal" data-testid="onboarding-social-login" @submit.prevent="loginStep === 'credentials' ? submitCredentials() : submitVerification()">
        <div class="modal__header">
          <div><h2>Connect {{ providerName(selectedProvider.provider) }}</h2><p>Sign in without leaving onboarding.</p></div>
          <button type="button" class="icon-button icon-button--plain" aria-label="Close" @click="closeLogin"><X :size="18" /></button>
        </div>
        <div class="modal__body">
          <div class="login-security"><LockKeyhole :size="18" /><span>{{ loginStep === 'credentials' ? 'Your credentials are passed to a temporary private browser and discarded when this request finishes. Only the encrypted reusable session is stored.' : 'Enter the one-time code requested by the provider. The code is submitted to the pending browser session and never stored.' }}</span></div>
          <div v-if="loginStep === 'credentials'" class="login-fields">
            <label>Username or email<input v-model="credentials.username" autocomplete="username" required /></label>
            <label>Password<input v-model="credentials.password" type="password" autocomplete="current-password" required /></label>
          </div>
          <label v-else>One-time verification code<input v-model="credentials.code" inputmode="numeric" autocomplete="one-time-code" minlength="4" maxlength="16" required /></label>
          <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
        </div>
        <div class="modal__footer">
          <button type="button" class="button" @click="closeLogin">Cancel</button>
          <button class="button button--primary" :disabled="Boolean(busyProvider)"><KeyRound :size="14" /> {{ busyProvider ? 'Signing in…' : loginStep === 'credentials' ? 'Sign in securely' : 'Verify account' }}</button>
        </div>
      </form>
    </div>
  </main>
</template>

<style scoped>
.onboarding-shell{min-height:100vh;padding:28px;background:radial-gradient(circle at 90% 0,#f6eafb,transparent 38%),#f7f5f4;color:#17131f}.onboarding-shell>header{display:grid;grid-template-columns:1fr minmax(180px,340px) 1fr;align-items:center;max-width:980px;margin:auto}.onboarding-shell header small{text-align:right;color:#766d7b}.step-meter{display:flex;gap:6px}.step-meter i{height:4px;flex:1;border-radius:10px;background:#e2dce5}.step-meter i.done{background:#982eb3}.onboarding-card{max-width:820px;margin:38px auto;padding:42px;border:1px solid #e3dce6;border-radius:24px;background:#fff;box-shadow:0 24px 70px rgba(38,23,43,.08)}h1{max-width:680px;margin:6px 0 12px;font-size:38px;letter-spacing:-.04em}.lead{max-width:680px;margin:0 0 28px;color:#716979;font-size:15px;line-height:1.6}.onboarding-icon{display:grid;width:46px;height:46px;place-items:center;border-radius:14px;background:#f8edfb;color:#982eb3}.onboarding-card label,.login-modal label{display:grid;gap:7px;color:#312b35;font-size:12px;font-weight:700}.onboarding-card input,.onboarding-card select,.onboarding-card textarea,.login-modal input{width:100%;padding:12px;border:1px solid #dcd4df;border-radius:10px;background:#fff;font:inherit}.onboarding-card textarea{min-height:95px;resize:vertical}.onboarding-card>.button{margin-top:18px}.mix-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.mix-summary div{display:grid;gap:5px;padding:18px;border:1px solid #e4dde7;border-radius:14px;background:#fcfafc}.mix-summary strong{font-size:24px}.mix-summary span{color:#716979;font-size:11px}.boundary-control{display:grid;gap:16px;margin:25px 0}.boundary-control input{padding:0;accent-color:#982eb3}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.context-grid .wide{grid-column:1/-1}.estimate{display:flex;justify-content:space-between;align-items:center;margin-top:18px;padding:16px;border-radius:12px;background:#f8edfb}.estimate span{color:#716979;font-size:11px}.actions{display:flex;justify-content:space-between;margin-top:28px}.channel-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.channel-card{display:grid;min-width:0;gap:16px;padding:18px;border:1px solid #e0d8e3;border-radius:14px;background:#fff;color:#26202a;text-align:left;transition:border-color .16s,box-shadow .16s,transform .16s}.channel-card:hover:not(:disabled){transform:translateY(-2px);border-color:#bd80ca;box-shadow:0 10px 30px rgba(57,29,63,.08)}.channel-card>span:first-child{display:grid;gap:4px}.channel-card strong{font-size:15px}.channel-card small{overflow:hidden;color:#716979;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.channel-card--connected{border-color:#b9dfcb;background:#f5fcf8}.connected-mark,.connect-mark{display:flex;align-items:center;gap:6px;color:#15824b;font-size:10px;font-weight:800}.connect-mark{color:#8c26a5}.secondary-note,.analysis-note{margin-top:14px;color:#716979;font-size:11px}.secondary-note{display:flex;align-items:center;gap:6px}.analysis-note{display:flex;align-items:center;gap:8px;padding:12px;border-radius:10px;background:#f8edfb}.login-modal{width:min(520px,100%)}.login-fields{display:grid;gap:14px}.login-security{display:flex;gap:9px;align-items:flex-start;margin-bottom:16px;padding:11px;border-radius:10px;background:#eef9f3;color:#15824b}.login-security span{font-size:10px;line-height:1.5}.login-modal .auth-error{margin-top:14px}@media(max-width:700px){.onboarding-shell{padding:16px}.onboarding-shell>header{grid-template-columns:1fr auto}.step-meter{display:none}.onboarding-card{margin-top:24px;padding:24px}.form-grid,.mix-summary,.channel-grid{grid-template-columns:1fr}.context-grid .wide{grid-column:auto}h1{font-size:30px}}
</style>
