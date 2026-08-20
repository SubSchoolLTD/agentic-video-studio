<script setup lang="ts">
import { BadgeDollarSign, CircleDollarSign, ExternalLink, Gift, Sparkles, WalletCards } from 'lucide-vue-next'

const { api } = useApi()
const { show } = useToast()
const route = useRoute()
const amountUsd = ref(12)
const promoCode = ref('')
const redeeming = ref(false)
const paying = ref(false)
const capturing = ref(false)
const { data: summary, refresh: refreshSummary } = await useAsyncData('billing-summary', () => api<any>('/v1/billing/summary'), { default: () => ({ balance_cents: 0, balance_usd: 0, currency: 'USD', prices: [] }) })
const { data: ledger, refresh: refreshLedger } = await useAsyncData('billing-ledger', () => api<any>('/v1/billing/ledger'))
const { data: topups, refresh: refreshTopups } = await useAsyncData('billing-topups', () => api<any>('/v1/billing/topups'), { default: () => ({ items: [] }) })

function money(value: unknown) { return `$${Number(value || 0).toFixed(2)}` }

async function startTopup() {
  if (Number(amountUsd.value) < 12) {
    show('Minimum top-up is $12', 'Increase the amount and try again.', 'error')
    return
  }
  paying.value = true
  try {
    const result = await api<any>('/v1/billing/topups/paypal', {
      method: 'POST',
      body: { amount_usd: Number(amountUsd.value).toFixed(2) },
    })
    sessionStorage.setItem('framewise_paypal_topup', JSON.stringify({ topup_id: result.topup_id, paypal_order_id: result.paypal_order_id }))
    window.location.assign(result.approval_url)
  }
  catch (error: any) { show('Could not open PayPal', error.message, 'error') }
  finally { paying.value = false }
}

async function redeemPromo() {
  if (!promoCode.value.trim()) return
  redeeming.value = true
  try {
    const result = await api<any>('/v1/billing/promo-codes/redeem', {
      method: 'POST',
      body: { code: promoCode.value.trim() },
    })
    promoCode.value = ''
    await Promise.all([refreshSummary(), refreshLedger()])
    show('Promo code activated', `${money(result.credited_usd)} added to your balance.`, 'success')
  }
  catch (error: any) { show('Promo code could not be activated', error.message, 'error') }
  finally { redeeming.value = false }
}

onMounted(async () => {
  if (route.query.paypal === 'cancel') {
    show('Payment cancelled', 'Your balance was not changed.', 'info')
    await navigateTo('/billing', { replace: true })
    return
  }
  if (route.query.paypal !== 'return') return
  const stored = JSON.parse(sessionStorage.getItem('framewise_paypal_topup') || '{}')
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
    await Promise.all([refreshSummary(), refreshLedger(), refreshTopups()])
    show('Balance topped up', `${money(result.credited_usd)} credited to your account.`, 'success')
    await navigateTo('/billing', { replace: true })
  }
  catch (error: any) { show('Could not confirm payment', error.message, 'error') }
  finally { capturing.value = false }
})
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Workspace economics" title="Balance & usage" description="Pay only for what you generate. All amounts are kept and charged in US dollars." />
    <div class="metric-grid">
      <UiAppCard class="metric-card"><div class="metric-card__head"><span class="metric-card__icon metric-card__icon--purple"><WalletCards :size="17" /></span><span>Available balance</span></div><div class="billing-metric-value"><strong>{{ money(summary?.balance_usd) }}</strong><small>USD · no subscription</small></div></UiAppCard>
      <UiAppCard class="metric-card"><div class="metric-card__head"><span class="metric-card__icon metric-card__icon--green"><BadgeDollarSign :size="17" /></span><span>Payment model</span></div><div class="billing-metric-value"><strong>Usage based</strong><small>Provider cost + 20%</small></div></UiAppCard>
    </div>

    <div class="billing-grid">
      <UiAppCard class="topup-card">
        <div class="section-heading"><div><h2>Top up with PayPal</h2><p>Minimum $12. The full captured amount is added to your balance.</p></div><CircleDollarSign :size="19" /></div>
        <form class="topup-form" @submit.prevent="startTopup">
          <label><span>Amount, USD</span><div class="money-input"><b>$</b><input v-model.number="amountUsd" type="number" min="12" max="100000" step="0.01" aria-label="Top-up amount"></div></label>
          <button class="button button--primary" type="submit" :disabled="paying || capturing"><ExternalLink :size="16" /> {{ capturing ? 'Confirming payment…' : paying ? 'Opening PayPal…' : `Continue to PayPal · ${money(amountUsd)}` }}</button>
        </form>
      </UiAppCard>

      <UiAppCard class="promo-card">
        <div class="section-heading"><div><h2>Activate promo code</h2><p>A valid code credits your balance immediately. No payment is required.</p></div><Gift :size="19" /></div>
        <form class="topup-form" @submit.prevent="redeemPromo">
          <label><span>Promo code</span><div class="promo-input"><Gift :size="16" /><input v-model="promoCode" maxlength="64" placeholder="FRAME-2026" aria-label="Promo code"></div></label>
          <button class="button" type="submit" :disabled="redeeming || !promoCode.trim()">{{ redeeming ? 'Activating…' : 'Activate code' }}</button>
        </form>
      </UiAppCard>

      <UiAppCard class="prices-card"><div class="section-heading"><div><h2>AI function prices</h2><p>Current customer rate per configured unit</p></div><Sparkles :size="18" /></div><div class="price-list"><div v-for="item in summary?.prices || []" :key="item.feature_key"><span><strong>{{ item.label }}</strong><small>{{ item.unit }}</small></span><b>{{ money(item.charge_usd) }}</b></div></div></UiAppCard>
    </div>

    <UiAppCard v-if="topups?.items?.length" class="ledger-card"><div class="section-heading"><div><h2>PayPal top-ups</h2><p>Captured payment history</p></div></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Date</th><th>Amount</th><th>Status</th></tr></thead><tbody><tr v-for="item in topups.items" :key="item.id"><td>{{ new Date(item.created_at).toLocaleString() }}</td><td>{{ money(item.amount_usd) }}</td><td><UiStatusBadge :status="item.status" /></td></tr></tbody></table></div></UiAppCard>
    <UiAppCard class="ledger-card"><div class="section-heading"><div><h2>Dollar ledger</h2><p>Top-ups, promo credits, AI usage and refunds</p></div></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Date</th><th>Description</th><th>Type</th><th>Amount</th></tr></thead><tbody><tr v-for="item in ledger?.items || []" :key="item.id"><td>{{ new Date(item.created_at).toLocaleString() }}</td><td><strong>{{ item.description }}</strong><small>{{ item.feature_key || item.reference_id || '' }}</small></td><td><UiStatusBadge :status="item.event_type" /></td><td :class="item.amount_cents >= 0 ? 'money-positive' : 'money-negative'">{{ item.amount_cents > 0 ? '+' : '' }}{{ money(item.amount_usd) }}</td></tr></tbody></table></div></UiAppCard>
  </div>
</template>

<style scoped>
.billing-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:15px 0}.prices-card{grid-column:1/-1}.billing-metric-value{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}.billing-metric-value small{color:var(--muted)}.topup-form{display:grid;gap:13px}.topup-form label{display:grid;gap:6px}.topup-form label>span{font-size:9px;font-weight:800}.topup-form label small{color:var(--muted);font-weight:500}.money-input,.promo-input{height:45px;display:flex;align-items:center;gap:8px;border:1px solid var(--border-strong);border-radius:10px;padding:0 12px;background:#fff}.money-input b{color:var(--purple);font-size:15px}.money-input input,.promo-input input{border:0;outline:0;min-width:0;flex:1;font:inherit;font-size:11px;background:transparent}.promo-input input{text-transform:uppercase}.price-list{display:grid}.price-list>div{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:11px 0;border-bottom:1px solid var(--border)}.price-list span{display:grid;gap:2px}.price-list strong{font-size:10px}.price-list small{color:var(--muted);font-size:8px}.price-list b{font-size:10px}.ledger-card{margin-top:14px}.table-scroll{overflow:auto}.data-table{width:100%;border-collapse:collapse}.data-table th,.data-table td{padding:10px;border-bottom:1px solid var(--border);font-size:9px;text-align:left}.data-table th{color:var(--muted);font-size:8px;text-transform:uppercase}.data-table td:nth-child(2){display:grid;gap:2px}.data-table td small{color:var(--muted)}.money-positive{color:var(--green);font-weight:800}.money-negative{color:var(--red);font-weight:800}@media(max-width:800px){.billing-grid{grid-template-columns:1fr}.prices-card{grid-column:auto}}
</style>
