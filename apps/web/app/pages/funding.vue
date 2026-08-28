<script setup lang="ts">
import { ArrowRight, Check, ExternalLink, Film, ShieldCheck, Sparkles, WalletCards } from 'lucide-vue-next'

const { api, projectId } = useApi()
const route = useRoute()
const { show } = useToast()
const paying = ref(false)
const capturing = ref(false)
const activating = ref(false)
const selectedPlanId = ref(typeof route.query.plan === 'string' ? route.query.plan : 'week')

useHead({ title: 'Fund your content plan — Framewise', meta: [{ name: 'robots', content: 'noindex, nofollow' }] })

const { data: funding, refresh: refreshFunding } = await useAsyncData(
  'project-funding-status',
  () => api<any>(`/v1/projects/${projectId.value}/funding-status`),
  { watch: [projectId] },
)

const selectedPlan = computed(() => {
  const options = funding.value?.options || []
  return options.find((item: any) => item.id === selectedPlanId.value) || options[0]
})

function money(value: unknown) { return `$${Number(value || 0).toFixed(2)}` }

async function activateAutomation() {
  activating.value = true
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/automation/activate`, { method: 'POST' })
    if (result.status === 'automation_off') {
      show('Setup complete', 'Automation is off. You can start research manually whenever you are ready.', 'success')
      await navigateTo('/app')
      return
    }
    const resumed = Number(result.resumed_generation_job_ids?.length || 0)
    show(
      resumed ? 'Production resumed' : 'Your first research is running',
      resumed ? `${resumed} waiting production${resumed === 1 ? '' : 's'} resumed from the saved stage.` : 'Framewise will continue according to your automation mode.',
      'success',
    )
    await navigateTo(result.next_url || (result.research_run_id ? '/research' : '/app'))
  }
  catch (error: any) {
    show('Automation is still waiting', error.message, 'error')
    await refreshFunding()
  }
  finally { activating.value = false }
}

async function startTopup() {
  if (!selectedPlan.value) return
  paying.value = true
  try {
    const returnPath = `/funding?source=${encodeURIComponent(String(route.query.source || 'plan'))}&plan=${encodeURIComponent(selectedPlan.value.id)}&activate=1`
    const result = await api<any>('/v1/billing/topups/paypal', {
      method: 'POST',
      body: { amount_usd: Number(selectedPlan.value.amount_usd).toFixed(2), return_path: returnPath },
    })
    sessionStorage.setItem('framewise_paypal_topup', JSON.stringify({
      topup_id: result.topup_id,
      paypal_order_id: result.paypal_order_id,
      activate: true,
      plan: selectedPlan.value.id,
    }))
    window.location.assign(result.approval_url)
  }
  catch (error: any) { show('Could not open PayPal', error.message, 'error') }
  finally { paying.value = false }
}

onMounted(async () => {
  if (route.query.paypal === 'cancel') {
    show('Payment cancelled', 'Your balance was not changed. Your setup is saved.', 'info')
    await navigateTo(`/funding?source=${encodeURIComponent(String(route.query.source || 'plan'))}&plan=${encodeURIComponent(selectedPlanId.value)}`, { replace: true })
    return
  }
  if (route.query.paypal !== 'return') return
  let stored: Record<string, unknown> = {}
  try { stored = JSON.parse(sessionStorage.getItem('framewise_paypal_topup') || '{}') }
  catch { sessionStorage.removeItem('framewise_paypal_topup') }
  const topupId = String(route.query.topup_id || stored.topup_id || '')
  const orderId = String(route.query.token || stored.paypal_order_id || '')
  if (!topupId || !orderId) {
    show('Could not confirm payment', 'The PayPal return data is incomplete.', 'error')
    return
  }
  capturing.value = true
  try {
    const result = await api<any>('/v1/billing/topups/paypal/capture', {
      method: 'POST',
      body: { topup_id: topupId, paypal_order_id: orderId },
    })
    sessionStorage.removeItem('framewise_paypal_topup')
    await refreshFunding()
    show('Balance topped up', `${money(result.credited_usd)} was added. Starting your saved plan now.`, 'success')
    await activateAutomation()
  }
  catch (error: any) { show('Could not confirm payment', error.message, 'error') }
  finally { capturing.value = false }
})
</script>

<template>
  <div class="funding-page">
    <UiPageHeader
      eyebrow="Ready to run"
      title="Fund your automatic content plan"
      description="Choose how long Framewise should be funded for. The amounts use the production plan you just calculated and are rounded up to whole dollars."
    />

    <div class="funding-summary">
      <UiAppCard><span><Film :size="17" /></span><div><small>Planned pace</small><strong>{{ funding?.videos_per_week || 0 }} videos / week</strong></div></UiAppCard>
      <UiAppCard><span><Sparkles :size="17" /></span><div><small>Estimated weekly usage</small><strong>{{ money(funding?.weekly_cost_usd) }}</strong></div></UiAppCard>
      <UiAppCard><span><WalletCards :size="17" /></span><div><small>Current balance</small><strong>{{ money(funding?.balance_usd) }}</strong></div></UiAppCard>
    </div>

    <UiAppCard class="plan-card">
      <div class="section-heading">
        <div><h2>How far ahead should we fund the plan?</h2><p>Every option is a balance top-up, not a subscription. Unused money remains in your account.</p></div>
        <ShieldCheck :size="20" />
      </div>
      <div class="plan-options" data-testid="funding-options">
        <button
          v-for="option in funding?.options || []"
          :key="option.id"
          type="button"
          :class="['plan-option', { 'plan-option--selected': selectedPlan?.id === option.id }]"
          :data-testid="`funding-plan-${option.id}`"
          @click="selectedPlanId = option.id"
        >
          <span class="plan-option__check"><Check v-if="selectedPlan?.id === option.id" :size="15" /></span>
          <small>{{ option.label }}</small>
          <strong>${{ option.amount_usd }}</strong>
          <p>(approximately {{ option.video_count }} videos)</p>
        </button>
      </div>
      <div class="funding-action">
        <div><strong>Framewise starts automatically after PayPal confirms the payment.</strong><span>First research runs immediately; scripts, videos and publishing then follow your selected automation mode.</span></div>
        <button class="button button--primary" :disabled="paying || capturing || !selectedPlan" data-testid="funding-pay" @click="startTopup">
          <ExternalLink :size="16" /> {{ capturing ? 'Confirming payment…' : paying ? 'Opening PayPal…' : `Top up ${money(selectedPlan?.amount_usd)}` }}
        </button>
      </div>
      <button v-if="Number(funding?.balance_cents || 0) > 0" class="use-balance" :disabled="activating" @click="activateAutomation">
        {{ activating ? 'Starting…' : 'Use my current balance and start' }} <ArrowRight :size="15" />
      </button>
    </UiAppCard>
  </div>
</template>

<style scoped>
.funding-page{max-width:1120px;margin:0 auto}.funding-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0}.funding-summary .app-card{display:flex;align-items:center;gap:12px}.funding-summary .app-card>span{display:grid;width:38px;height:38px;place-items:center;border-radius:11px;background:var(--primary-50);color:var(--primary-700)}.funding-summary .app-card>div{display:grid;gap:3px}.funding-summary small{color:var(--muted);font-size:8px;text-transform:uppercase}.funding-summary strong{font-size:12px}.plan-card{padding:24px}.plan-options{display:grid;grid-template-columns:repeat(3,1fr);gap:13px;margin-top:18px}.plan-option{position:relative;display:grid;gap:7px;padding:22px;border:1px solid var(--border-strong);border-radius:15px;background:#fff;color:var(--ink);text-align:left;transition:.16s}.plan-option:hover{transform:translateY(-2px);border-color:var(--primary-300);box-shadow:var(--shadow-sm)}.plan-option--selected{border-color:var(--primary-500);background:linear-gradient(145deg,var(--primary-50),#fff);box-shadow:0 0 0 3px var(--primary-100)}.plan-option__check{position:absolute;top:14px;right:14px;display:grid;width:24px;height:24px;place-items:center;border:1px solid var(--border);border-radius:50%;color:#fff}.plan-option--selected .plan-option__check{border-color:var(--primary-600);background:var(--primary-600)}.plan-option small{color:var(--muted);font-size:9px;font-weight:800;text-transform:uppercase}.plan-option strong{font-family:var(--font-display);font-size:29px}.plan-option p{margin:0;color:var(--muted-strong);font-size:10px}.funding-action{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-top:20px;padding:18px;border-radius:13px;background:#21172b;color:#fff}.funding-action>div{display:grid;gap:5px}.funding-action strong{font-size:11px}.funding-action span{max-width:620px;color:#cfc5d4;font-size:9px;line-height:1.5}.funding-action .button{flex:none}.use-balance{display:flex;align-items:center;gap:6px;margin:14px auto 0;border:0;background:transparent;color:var(--primary-700);font-size:9px;font-weight:800}@media(max-width:800px){.funding-summary,.plan-options{grid-template-columns:1fr}.funding-action{align-items:flex-start;flex-direction:column}.funding-action .button{width:100%}}
</style>
