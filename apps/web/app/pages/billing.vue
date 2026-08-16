<script setup lang="ts">
import { BadgeDollarSign, Gift, Sparkles, WalletCards } from 'lucide-vue-next'

const { api } = useApi()
const { show } = useToast()
const promo = ref('')
const redeeming = ref(false)
const { data: summary, refresh: refreshSummary } = await useAsyncData('billing-summary', () => api<any>('/v1/billing/summary'))
const { data: ledger, refresh: refreshLedger } = await useAsyncData('billing-ledger', () => api<any>('/v1/billing/ledger'))
const { data: redemptions, refresh: refreshRedemptions } = await useAsyncData('billing-promo-redemptions', () => api<any>('/v1/billing/promo-codes/redemptions'), { default: () => ({ items: [] }) })

async function redeem() {
  if (!promo.value.trim()) return
  redeeming.value = true
  try {
    const result = await api<any>('/v1/billing/promo-codes/redeem', { method: 'POST', body: { code: promo.value } })
    show('Promo code redeemed', `${result.credit_tokens || 0} AI tokens added.`, 'success')
    promo.value = ''
    await Promise.all([refreshSummary(), refreshLedger(), refreshRedemptions()])
  }
  catch (error: any) { show('Could not redeem code', error.message, 'error') }
  finally { redeeming.value = false }
}
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Workspace economics" title="Billing & AI tokens" description="Every credit and AI charge is recorded as an immutable ledger entry." />
    <div class="metric-grid">
      <UiAppCard class="metric-card"><div class="metric-card__head"><span class="metric-card__icon metric-card__icon--purple"><WalletCards :size="17" /></span><span>Available</span></div><strong>{{ Number(summary?.balance_tokens || 0).toLocaleString() }}</strong><small>AI tokens</small></UiAppCard>
      <UiAppCard class="metric-card"><div class="metric-card__head"><span class="metric-card__icon metric-card__icon--green"><BadgeDollarSign :size="17" /></span><span>Plan</span></div><strong>{{ summary?.subscription?.plan || 'free' }}</strong><small>{{ summary?.subscription?.expires_at ? `Until ${new Date(summary.subscription.expires_at).toLocaleDateString()}` : 'No expiration' }}</small></UiAppCard>
    </div>
    <div class="billing-grid">
      <UiAppCard><div class="section-heading"><div><h2>AI function prices</h2><p>Current charge per configured unit</p></div><Sparkles :size="18" /></div><div class="price-list"><div v-for="item in summary?.prices || []" :key="item.feature_key"><span><strong>{{ item.label }}</strong><small>{{ item.unit }}</small></span><b>{{ Number(item.charge_tokens).toLocaleString() }} tokens</b></div></div></UiAppCard>
      <UiAppCard><div class="section-heading"><div><h2>Redeem a promo code</h2><p>Credits or subscription time are applied immediately</p></div><Gift :size="18" /></div><form class="promo-form" @submit.prevent="redeem"><input v-model="promo" aria-label="Promo code" placeholder="FRAME-2026"><button type="button" class="button button--primary" :disabled="redeeming" @click="redeem">{{ redeeming ? 'Applying…' : 'Apply code' }}</button></form><div v-if="redemptions?.items?.length" class="redemption-list"><strong>Previously redeemed</strong><span v-for="item in redemptions.items" :key="item.id"><b>{{ item.code }}</b><small>{{ item.credit_tokens }} tokens · {{ item.subscription_days }} days · {{ new Date(item.redeemed_at).toLocaleDateString() }}</small></span></div></UiAppCard>
    </div>
    <UiAppCard class="ledger-card"><div class="section-heading"><div><h2>Token ledger</h2><p>Top-ups, promotions and AI usage</p></div></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Date</th><th>Description</th><th>Type</th><th>Amount</th></tr></thead><tbody><tr v-for="item in ledger?.items || []" :key="item.id"><td>{{ new Date(item.created_at).toLocaleString() }}</td><td><strong>{{ item.description }}</strong><small>{{ item.feature_key || item.reference_id || '' }}</small></td><td><UiStatusBadge :status="item.event_type" /></td><td :class="item.amount_tokens >= 0 ? 'token-positive' : 'token-negative'">{{ item.amount_tokens > 0 ? '+' : '' }}{{ Number(item.amount_tokens).toLocaleString() }}</td></tr></tbody></table></div></UiAppCard>
  </div>
</template>

<style scoped>.billing-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:14px;margin:15px 0}.price-list{display:grid}.price-list>div{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:11px 0;border-bottom:1px solid var(--border)}.price-list span{display:grid;gap:2px}.price-list strong{font-size:10px}.price-list small{color:var(--muted);font-size:8px}.price-list b{font-size:10px}.promo-form{display:grid;gap:10px}.promo-form input{height:43px;padding:0 12px;border:1px solid var(--border-strong);border-radius:10px;text-transform:uppercase}.redemption-list{display:grid;gap:7px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)}.redemption-list>strong{font-size:8px;text-transform:uppercase}.redemption-list span{display:flex;justify-content:space-between;gap:10px;font-size:8px}.redemption-list span b{font-family:monospace}.redemption-list small{color:var(--muted)}.ledger-card{margin-top:14px}.table-scroll{overflow:auto}.data-table{width:100%;border-collapse:collapse}.data-table th,.data-table td{padding:10px;border-bottom:1px solid var(--border);font-size:9px;text-align:left}.data-table th{color:var(--muted);font-size:8px;text-transform:uppercase}.data-table td:nth-child(2){display:grid;gap:2px}.data-table td small{color:var(--muted)}.token-positive{color:var(--green);font-weight:800}.token-negative{color:var(--red);font-weight:800}@media(max-width:800px){.billing-grid{grid-template-columns:1fr}}</style>
