<script setup lang="ts">
import { Activity, BadgeDollarSign, Gift, Save, ShieldCheck, TrendingUp, Users, WalletCards } from 'lucide-vue-next'

const { api } = useApi()
const { show } = useToast()
const tab = ref<'analytics' | 'users' | 'promos' | 'pricing'>('analytics')
const query = ref('')
const creditAmounts = reactive<Record<string, number>>({})
const creditUsd = reactive<Record<string, number>>({})
const promoForm = reactive({ code: '', kind: 'ai_tokens', credit_tokens: 1000, subscription_days: 0, max_redemptions: 1, expires_at: '' })
const createdCode = ref('')

const { data: overview, refresh: refreshOverview } = await useAsyncData('admin-overview', () => api<any>('/v1/platform-admin/overview'))
const { data: users, refresh: refreshUsers } = await useAsyncData('admin-users', () => api<any>('/v1/platform-admin/users'))
const { data: promos, refresh: refreshPromos } = await useAsyncData('admin-promos', () => api<any>('/v1/platform-admin/promo-codes'))
const { data: pricing, refresh: refreshPricing } = await useAsyncData('admin-pricing', () => api<any>('/v1/platform-admin/pricing'))

const filteredUsers = computed(() => (users.value?.items || []).filter((item: any) => `${item.email} ${item.display_name} ${item.organization_name}`.toLowerCase().includes(query.value.toLowerCase())))
const retention = (days: 7 | 30) => overview.value?.retention?.[`day_${days}`] || { eligible: 0, retained: 0, rate_percent: null }

async function setStatus(item: any, status: string) {
  await api(`/v1/platform-admin/users/${item.id}`, { method: 'PATCH', body: { status } })
  await refreshUsers()
  show('User updated', `${item.email} is now ${status}.`, 'success')
}

async function adjust(item: any) {
  const amount = Number(creditAmounts[item.id] || 0)
  if (!amount) return
  await api(`/v1/platform-admin/users/${item.id}/credits`, {
    method: 'POST',
    body: {
      amount_tokens: amount,
      deposited_usd: amount > 0 && Number(creditUsd[item.id] || 0) > 0 ? Number(creditUsd[item.id]) : null,
      description: 'Manual platform admin balance adjustment',
    },
  })
  creditAmounts[item.id] = 0
  creditUsd[item.id] = 0
  await Promise.all([refreshUsers(), refreshOverview()])
  show('Balance updated', `${amount > 0 ? '+' : ''}${amount} tokens applied.`, 'success')
}

async function createPromo() {
  try {
    const body = { ...promoForm, expires_at: promoForm.expires_at ? new Date(promoForm.expires_at).toISOString() : null }
    const result = await api<any>('/v1/platform-admin/promo-codes', { method: 'POST', body })
    createdCode.value = result.code
    await Promise.all([refreshPromos(), refreshOverview()])
    show('Promo created', 'Copy the code from the highlighted field.', 'success')
  }
  catch (error: any) { show('Could not create promo', error.message, 'error') }
}

async function disablePromo(item: any) {
  await api(`/v1/platform-admin/promo-codes/${item.id}`, { method: 'PATCH', body: { is_active: !item.is_active } })
  await refreshPromos()
}

async function savePrice(item: any) {
  await api(`/v1/platform-admin/pricing/${item.feature_key}`, {
    method: 'PATCH',
    body: {
      provider: item.provider,
      integration: item.integration,
      model_id: item.model_id,
      provider_cost_usd: Number(item.provider_cost_usd),
      charge_tokens: Number(item.charge_tokens),
      margin_percent: Number(item.margin_percent),
      is_active: item.is_active,
    },
  })
  await Promise.all([refreshPricing(), refreshOverview()])
  show('Price saved', item.label, 'success')
}
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Internal operations" title="Platform admin" description="Customer analytics, retention, balance economics, model pricing and promotional access."><span class="admin-lock"><ShieldCheck :size="14" /> Platform administrator</span></UiPageHeader>

    <div class="metric-grid admin-metrics">
      <UiAppCard class="metric-card"><div class="metric-card__head"><span class="metric-card__icon metric-card__icon--purple"><Users :size="17" /></span><span>Registered</span></div><strong>{{ overview?.users?.total || 0 }}</strong><small>+{{ overview?.users?.registered_30d || 0 }} in 30 days</small></UiAppCard>
      <UiAppCard class="metric-card"><div class="metric-card__head"><span class="metric-card__icon"><TrendingUp :size="17" /></span><span>D7 retention</span></div><strong>{{ retention(7).rate_percent == null ? '—' : `${retention(7).rate_percent}%` }}</strong><small>{{ retention(7).retained }} / {{ retention(7).eligible }} eligible</small></UiAppCard>
      <UiAppCard class="metric-card"><div class="metric-card__head"><span class="metric-card__icon"><Activity :size="17" /></span><span>D30 retention</span></div><strong>{{ retention(30).rate_percent == null ? '—' : `${retention(30).rate_percent}%` }}</strong><small>{{ retention(30).retained }} / {{ retention(30).eligible }} eligible</small></UiAppCard>
      <UiAppCard class="metric-card"><div class="metric-card__head"><span class="metric-card__icon metric-card__icon--green"><BadgeDollarSign :size="17" /></span><span>Deposited</span></div><strong>${{ Number(overview?.money?.deposited_usd || 0).toFixed(2) }}</strong><small>Paid/admin top-ups only</small></UiAppCard>
      <UiAppCard class="metric-card"><div class="metric-card__head"><span class="metric-card__icon"><WalletCards :size="17" /></span><span>AI usage</span></div><strong>{{ Number(overview?.tokens?.spent || 0).toLocaleString() }}</strong><small>tokens spent</small></UiAppCard>
    </div>

    <div class="admin-tabs"><button :class="{active:tab==='analytics'}" @click="tab='analytics'">Analytics</button><button :class="{active:tab==='users'}" @click="tab='users'">Users</button><button :class="{active:tab==='promos'}" @click="tab='promos'">Promo codes</button><button :class="{active:tab==='pricing'}" @click="tab='pricing'">Models & pricing</button></div>

    <div v-if="tab === 'analytics'" class="analytics-stack">
      <div class="analytics-columns">
        <UiAppCard><div class="section-heading"><div><h2>Retention definition</h2><p>Rolling threshold, not exact calendar-day return</p></div><TrendingUp :size="18" /></div><div class="retention-list"><div><strong>D7</strong><span>Any authenticated activity on or after day 7</span><b>{{ retention(7).retained }} / {{ retention(7).eligible }}</b></div><div><strong>D30</strong><span>Any authenticated activity on or after day 30</span><b>{{ retention(30).retained }} / {{ retention(30).eligible }}</b></div></div></UiAppCard>
        <UiAppCard><div class="section-heading"><div><h2>Cash and provider costs</h2><p>Recorded money only; free and promo credits are not revenue</p></div><BadgeDollarSign :size="18" /></div><div class="economics-list"><div><span>Deposited</span><strong>${{ Number(overview?.money?.deposited_usd || 0).toFixed(2) }}</strong></div><div><span>Configured provider cost used</span><strong>${{ Number(overview?.money?.provider_cost_usd || 0).toFixed(2) }}</strong></div><div><span>Cash after provider cost</span><strong>${{ Number(overview?.money?.cash_after_provider_cost_usd || 0).toFixed(2) }}</strong></div></div></UiAppCard>
      </div>
      <UiAppCard><div class="section-heading"><div><h2>Usage by model-backed function</h2><p>Immutable ledger totals grouped by the price rule used at charge time</p></div><Activity :size="18" /></div><div class="table-scroll"><table class="admin-table"><thead><tr><th>Function</th><th>Provider / model</th><th>Operations</th><th>Tokens used</th><th>Provider cost</th></tr></thead><tbody><tr v-for="item in overview?.usage_by_feature || []" :key="item.feature_key"><td><strong>{{ item.label }}</strong><small>{{ item.feature_key }}</small></td><td><strong>{{ item.provider }}</strong><small>{{ item.model_id || '—' }}</small></td><td>{{ item.operations }}</td><td>{{ Number(item.tokens_spent).toLocaleString() }}</td><td>${{ Number(item.provider_cost_usd).toFixed(4) }}</td></tr><tr v-if="!(overview?.usage_by_feature || []).length"><td colspan="5">No AI usage recorded yet.</td></tr></tbody></table></div></UiAppCard>
    </div>

    <UiAppCard v-else-if="tab==='users'"><div class="section-heading"><div><h2>User management</h2><p>Account activity, funding, usage and current balance</p></div><input v-model="query" class="admin-search" placeholder="Search users…"></div><div class="table-scroll"><table class="admin-table"><thead><tr><th>User</th><th>Workspace</th><th>Activity</th><th>Funded / used</th><th>Balance</th><th>Adjustment</th><th></th></tr></thead><tbody><tr v-for="item in filteredUsers" :key="item.id"><td><strong>{{ item.display_name }}</strong><small>{{ item.email }}</small></td><td><strong>{{ item.organization_name || '—' }}</strong><small><UiStatusBadge :status="item.status" /></small></td><td><strong>{{ item.last_activity_at ? new Date(item.last_activity_at).toLocaleDateString() : 'Never' }}</strong><small>Joined {{ new Date(item.created_at).toLocaleDateString() }}</small></td><td><strong>{{ Number(item.tokens_topped_up).toLocaleString() }} / {{ Number(item.tokens_spent).toLocaleString() }}</strong><small>${{ Number(item.deposited_usd).toFixed(2) }} deposited</small></td><td>{{ Number(item.balance_tokens).toLocaleString() }}</td><td><div class="credit-action"><input v-model.number="creditAmounts[item.id]" type="number" placeholder="± tokens"><input v-model.number="creditUsd[item.id]" type="number" min="0" step="0.01" placeholder="USD paid"><button class="button button--small" @click="adjust(item)">Apply</button></div></td><td><button class="button button--small" @click="setStatus(item,item.status==='blocked'?'active':'blocked')">{{ item.status==='blocked'?'Unblock':'Block' }}</button></td></tr></tbody></table></div></UiAppCard>

    <div v-else-if="tab==='promos'" class="admin-columns"><UiAppCard><div class="section-heading"><div><h2>Create promo code</h2><p>AI tokens, subscription time, or both</p></div><Gift :size="18" /></div><form class="admin-form" data-testid="admin-promo-form" @submit.prevent="createPromo"><label>Custom code<input v-model="promoForm.code" placeholder="Leave blank to generate"></label><label>Benefit<select v-model="promoForm.kind"><option value="ai_tokens">AI tokens</option><option value="subscription">Subscription</option><option value="bundle">Bundle</option></select></label><label>AI tokens<input v-model.number="promoForm.credit_tokens" type="number" min="0"></label><label>Subscription days<input v-model.number="promoForm.subscription_days" type="number" min="0"></label><label>Maximum redemptions<input v-model.number="promoForm.max_redemptions" type="number" min="1"></label><label>Expires at<input v-model="promoForm.expires_at" type="datetime-local"></label><button class="button button--primary">Create code</button><div v-if="createdCode" class="created-code">{{ createdCode }}</div></form></UiAppCard><UiAppCard><div class="section-heading"><div><h2>Existing codes</h2><p>Only a prefix is retained after creation</p></div></div><div class="promo-list"><div v-for="item in promos?.items || []" :key="item.id"><span><strong>{{ item.code }}</strong><small>{{ item.credit_tokens }} tokens · {{ item.subscription_days }} days · {{ item.redemption_count }}/{{ item.max_redemptions || '∞' }} · {{ item.expires_at ? `expires ${new Date(item.expires_at).toLocaleDateString()}` : 'no expiry' }}</small></span><button class="button button--small" @click="disablePromo(item)">{{ item.is_active ? 'Disable' : 'Enable' }}</button></div></div></UiAppCard></div>

    <UiAppCard v-else><div class="section-heading"><div><h2>Models, integrations and customer prices</h2><p>Provider cost is an estimate; token charge is the amount debited from the customer ledger</p></div><BadgeDollarSign :size="18" /></div><div class="table-scroll"><table class="admin-table pricing-table"><thead><tr><th>Function</th><th>Provider</th><th>Integration / model</th><th>Cost USD</th><th>Charge</th><th>Margin %</th><th>Active</th><th></th></tr></thead><tbody><tr v-for="item in pricing?.items || []" :key="item.feature_key"><td><strong>{{ item.label }}</strong><small>{{ item.feature_key }} · {{ item.unit }}</small></td><td><input v-model="item.provider"></td><td><input v-model="item.integration"><input v-model="item.model_id"></td><td><input v-model.number="item.provider_cost_usd" type="number" min="0" step="0.001"></td><td><input v-model.number="item.charge_tokens" type="number" min="0"></td><td><input v-model.number="item.margin_percent" type="number" step="0.1"></td><td><input v-model="item.is_active" type="checkbox"></td><td><button class="button button--small" @click="savePrice(item)"><Save :size="13" /> Save</button></td></tr></tbody></table></div></UiAppCard>
  </div>
</template>

<style scoped>
.admin-lock{display:flex;align-items:center;gap:6px;padding:7px 9px;border-radius:8px;background:var(--primary-50);color:var(--primary-700);font-size:9px;font-weight:800}.admin-metrics{grid-template-columns:repeat(5,minmax(0,1fr))}.admin-tabs{display:flex;gap:3px;margin:20px 0 12px;border-bottom:1px solid var(--border)}.admin-tabs button{padding:10px 13px;border-bottom:2px solid transparent;background:transparent;color:var(--muted);font-size:9px;font-weight:800}.admin-tabs button.active{border-color:var(--primary-600);color:var(--primary-700)}.analytics-stack{display:grid;gap:14px}.analytics-columns{display:grid;grid-template-columns:1fr 1fr;gap:14px}.retention-list,.economics-list{display:grid}.retention-list>div{display:grid;grid-template-columns:50px 1fr auto;align-items:center;gap:10px;padding:12px 0;border-bottom:1px solid var(--border)}.retention-list strong{font-size:14px}.retention-list span{color:var(--muted);font-size:8px}.retention-list b{font-size:11px}.economics-list>div{display:flex;justify-content:space-between;padding:11px 0;border-bottom:1px solid var(--border);font-size:9px}.admin-search{height:36px;padding:0 10px;border:1px solid var(--border);border-radius:9px}.table-scroll{overflow:auto}.admin-table{width:100%;border-collapse:collapse}.admin-table th,.admin-table td{padding:10px;border-bottom:1px solid var(--border);font-size:9px;text-align:left;white-space:nowrap}.admin-table th{color:var(--muted);font-size:8px;text-transform:uppercase}.admin-table td:first-child,.admin-table td:nth-child(2){display:grid;gap:2px}.admin-table small{color:var(--muted)}.credit-action{display:grid;grid-template-columns:85px 85px auto;gap:5px}.credit-action input,.pricing-table input:not([type=checkbox]){height:31px;padding:0 7px;border:1px solid var(--border);border-radius:7px}.pricing-table td:nth-child(3){display:grid;gap:4px}.pricing-table td:nth-child(3) input{width:190px}.pricing-table td:nth-child(4) input,.pricing-table td:nth-child(5) input,.pricing-table td:nth-child(6) input{width:85px}.admin-columns{display:grid;grid-template-columns:.8fr 1.2fr;gap:14px}.admin-form{display:grid;gap:11px}.admin-form label{display:grid;gap:5px;color:var(--muted);font-size:8px;font-weight:800;text-transform:uppercase}.admin-form input,.admin-form select{height:37px;padding:0 9px;border:1px solid var(--border);border-radius:8px}.created-code{padding:12px;border:1px solid var(--green);border-radius:9px;background:var(--green-soft);color:var(--green);font-family:monospace;font-weight:800;text-align:center}.promo-list{display:grid}.promo-list>div{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)}.promo-list span{display:grid;gap:2px}.promo-list strong{font-family:monospace;font-size:10px}.promo-list small{color:var(--muted);font-size:8px}@media(max-width:1100px){.admin-metrics{grid-template-columns:repeat(3,1fr)}}@media(max-width:950px){.admin-columns,.analytics-columns{grid-template-columns:1fr}}@media(max-width:650px){.admin-metrics{grid-template-columns:1fr 1fr}.admin-tabs{overflow:auto}.admin-tabs button{white-space:nowrap}}
</style>
