<script setup lang="ts">
import { Activity, Braces, Check, Copy, KeyRound, Plus, RadioTower, Send, ShieldCheck, Trash2, X } from 'lucide-vue-next'

const { api, projectId, apiBase } = useApi()
const grafanaUrl = useRuntimeConfig().public.grafanaUrl
const { show } = useToast()
const keyModal = ref(false)
const webhookModal = ref(false)
const revealedKey = ref('')
const automationScopes = [
  'projects:read', 'projects:write',
  'sources:read', 'sources:write',
  'research:read', 'research:run',
  'generations:read', 'generations:write',
  'videos:read', 'videos:approve',
  'publications:read', 'publications:write',
  'analytics:read',
]
const scopeOptions = [
  ...automationScopes,
  'analytics:write', 'integrations:read', 'integrations:write', 'webhooks:write',
]
const keyForm = reactive({ name: 'My automation agent', scopes: [...automationScopes] })
const webhookForm = reactive({ url: 'https://example.com/webhooks/framewise', events: ['generation.completed', 'publication.published'] })
const { data, refresh } = await useAsyncData('developer', async () => {
  const [keys, webhooks] = await Promise.all([
    api<any>(`/v1/projects/${projectId.value}/api-keys`),
    api<any>(`/v1/projects/${projectId.value}/webhooks`),
  ])
  return { keys: keys.items, webhooks: webhooks.items }
}, { default: () => ({ keys: [], webhooks: [] }) })
const mcpEndpoint = computed(() => `${String(apiBase).replace(/\/$/, '')}/mcp`)
const mcpConfig = computed(() => JSON.stringify({
  mcpServers: {
    framewise: {
      type: 'http',
      url: mcpEndpoint.value,
      headers: { Authorization: `Bearer ${revealedKey.value || '<FRAMEWISE_API_KEY>'}` },
    },
  },
}, null, 2))

function openKeyModal() {
  revealedKey.value = ''
  keyForm.name = 'My automation agent'
  keyForm.scopes = [...automationScopes]
  keyModal.value = true
}

function closeKeyModal() {
  keyModal.value = false
  revealedKey.value = ''
}

function toggleScope(scope: string) {
  keyForm.scopes = keyForm.scopes.includes(scope)
    ? keyForm.scopes.filter(item => item !== scope)
    : [...keyForm.scopes, scope]
}

async function createKey() {
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/api-keys`, { method: 'POST', body: keyForm })
    revealedKey.value = result.key
    show('API key created', 'Copy it now; the full value is never returned again.', 'success')
    await refresh()
  }
  catch (error: any) { show('Could not create key', error.message, 'error') }
}

async function copyKey() {
  await navigator.clipboard.writeText(revealedKey.value)
  show('Copied', 'The one-time key is on your clipboard.', 'success')
}

async function copyMcpConfig() {
  await navigator.clipboard.writeText(mcpConfig.value)
  show('MCP configuration copied', 'Paste it into the MCP client used by your agent.', 'success')
}

async function revokeKey(id: string) {
  try {
    await api(`/v1/api-keys/${id}`, { method: 'DELETE' })
    await refresh()
    show('API key revoked', 'Agents using this key can no longer access the project.', 'success')
  }
  catch (error: any) { show('Could not revoke key', error.message, 'error') }
}

async function createWebhook() {
  try {
    await api(`/v1/projects/${projectId.value}/webhooks`, { method: 'POST', body: webhookForm })
    webhookModal.value = false
    await refresh()
    show('Webhook registered', 'Deliveries are HMAC-SHA256 signed.', 'success')
  }
  catch (error: any) { show('Could not register webhook', error.message, 'error') }
}

async function testWebhook(id: string) {
  try {
    await api(`/v1/webhooks/${id}/test`, { method: 'POST' })
    show('Test delivery accepted', 'Check the endpoint for the signed event.', 'success')
  }
  catch (error: any) { show('Test failed', error.message, 'error') }
}
</script>

<template>
  <div>
    <UiPageHeader eyebrow="API + MCP" title="Developer" description="Typed REST resources, tenant-scoped keys, signed webhooks and a thin MCP surface over the same domain services.">
      <a v-if="grafanaUrl" class="button" :href="`${grafanaUrl}/d/avs-pipeline`" target="_blank"><Activity :size="15" /> Pipeline ops</a>
      <a class="button" :href="`${apiBase}/docs`" target="_blank"><Braces :size="15" /> OpenAPI docs</a>
      <button class="button button--primary" @click="openKeyModal"><Plus :size="15" /> Connect an agent</button>
    </UiPageHeader>

    <div class="developer-grid">
      <UiAppCard>
        <div class="section-heading"><div><h2>API keys</h2><p>Prefixes are visible; hashes are stored.</p></div><KeyRound :size="18" /></div>
        <div v-if="data.keys.length" class="developer-list">
          <article v-for="item in data.keys" :key="item.id"><div><strong>{{ item.name }}</strong><span><code>{{ item.key_prefix }}…</code> · {{ item.scopes.join(', ') }}</span></div><div class="key-actions"><UiStatusBadge :status="item.revoked_at ? 'revoked' : 'active'" /><button v-if="!item.revoked_at" class="icon-button icon-button--plain" type="button" aria-label="Revoke API key" @click="revokeKey(item.id)"><Trash2 :size="13" /></button></div></article>
        </div>
        <div v-else class="mini-empty">No API keys yet. Create a tenant-scoped key for your integration.</div>
      </UiAppCard>
      <UiAppCard>
        <div class="section-heading"><div><h2>Webhooks</h2><p>At-least-once delivery with event IDs.</p></div><button class="button button--small" @click="webhookModal=true"><Plus :size="13" /> Add</button></div>
        <div v-if="data.webhooks.length" class="developer-list">
          <article v-for="item in data.webhooks" :key="item.id"><div><strong>{{ item.url }}</strong><span>{{ item.events.join(', ') }}</span></div><button class="button button--small" @click="testWebhook(item.id)"><Send :size="12" /> Test</button></article>
        </div>
        <div v-else class="mini-empty">No endpoints registered.</div>
      </UiAppCard>
    </div>

    <UiAppCard class="mcp-card"><span class="mcp-card__icon"><RadioTower :size="21" /></span><div><strong>Framewise remote MCP</strong><span>Connect your own agent with a project-scoped bearer key. It can configure automation, update project context, run research, decide on candidates, start or resume production, publish safely and read performance feedback through the same REST permissions as this interface.</span><code>{{ mcpEndpoint }}</code></div><ShieldCheck :size="20" /></UiAppCard>

    <div v-if="keyModal" class="modal-backdrop" @click.self="closeKeyModal">
      <form class="modal developer-modal" @submit.prevent="revealedKey ? closeKeyModal() : createKey()">
        <div class="modal__header"><div><h2>Connect your agent</h2><p>Create a revocable project key, then paste the generated MCP configuration into your agent.</p></div><button type="button" class="icon-button icon-button--plain" @click="closeKeyModal"><X :size="18" /></button></div>
        <div class="modal__body">
          <div v-if="!revealedKey" class="field"><label>Name</label><input v-model="keyForm.name" required /></div>
          <div v-if="!revealedKey" class="scope-grid"><label v-for="scope in scopeOptions" :key="scope" :class="{ selected: keyForm.scopes.includes(scope) }"><input type="checkbox" :checked="keyForm.scopes.includes(scope)" @change="toggleScope(scope)"><Check :size="12" /> {{ scope }}</label></div>
          <template v-else>
            <div class="revealed-key"><KeyRound :size="20" /><div><strong>Copy this key now</strong><code>{{ revealedKey }}</code><span>It cannot be recovered after this dialog closes.</span></div><button type="button" class="button" @click="copyKey"><Copy :size="13" /> Key</button></div>
            <div class="mcp-config"><div><strong>MCP client configuration</strong><span>The bearer key stays revocable and restricted to this project and the scopes selected above.</span></div><pre>{{ mcpConfig }}</pre><button type="button" class="button" @click="copyMcpConfig"><Copy :size="13" /> Copy MCP config</button></div>
          </template>
        </div>
        <div class="modal__footer"><button type="button" class="button" @click="closeKeyModal">{{ revealedKey ? 'Close' : 'Cancel' }}</button><button v-if="!revealedKey" class="button button--primary" :disabled="!keyForm.scopes.length">Create key</button></div>
      </form>
    </div>

    <div v-if="webhookModal" class="modal-backdrop" @click.self="webhookModal=false">
      <form class="modal" @submit.prevent="createWebhook">
        <div class="modal__header"><div><h2>Add webhook</h2><p>Private, loopback and metadata-network addresses are rejected.</p></div><button type="button" class="icon-button icon-button--plain" @click="webhookModal=false"><X :size="18" /></button></div>
        <div class="modal__body"><div class="field"><label>HTTPS endpoint</label><input v-model="webhookForm.url" type="url" required /></div><div class="scope-grid"><label v-for="event in webhookForm.events" :key="event"><Check :size="12" /> {{ event }}</label></div></div>
        <div class="modal__footer"><button type="button" class="button" @click="webhookModal=false">Cancel</button><button class="button button--primary">Register endpoint</button></div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.developer-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.developer-list{display:grid}.developer-list article{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)}.developer-list article:last-child{border:0}.developer-list article>div:first-child{display:grid;min-width:0;gap:3px}.developer-list strong{font-size:10px}.developer-list span{max-width:420px;overflow:hidden;color:var(--muted);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.developer-list code{font-size:8px}.key-actions{display:flex;align-items:center;gap:5px}.mini-empty{display:grid;min-height:100px;place-items:center;color:var(--muted);font-size:9px;text-align:center}.mcp-card{display:flex;align-items:center;gap:12px;margin-top:15px}.mcp-card__icon{display:grid;width:42px;height:42px;place-items:center;border-radius:12px;background:var(--primary-50);color:var(--primary-600)}.mcp-card>div{display:grid;min-width:0;flex:1;gap:3px}.mcp-card strong{font-size:11px}.mcp-card span{color:var(--muted);font-size:9px;line-height:1.5}.mcp-card code{width:max-content;max-width:100%;margin-top:4px;padding:5px 7px;overflow:auto;border-radius:6px;background:#211a25;color:#f4eaf6;font-size:8px}.developer-modal{width:min(760px,calc(100vw - 32px))}.scope-grid{display:flex;flex-wrap:wrap;gap:7px;margin-top:14px}.scope-grid label{display:flex;align-items:center;gap:5px;padding:6px 8px;border:1px solid transparent;border-radius:7px;background:var(--surface-soft);color:var(--muted-strong);font-size:8px;cursor:pointer}.scope-grid label.selected{border-color:var(--primary-300);background:var(--primary-50);color:var(--primary-700)}.scope-grid input{position:absolute;opacity:0;pointer-events:none}.revealed-key{display:flex;align-items:flex-start;gap:10px;padding:13px;border-radius:10px;background:var(--amber-soft);color:#9b6707}.revealed-key>div{display:grid;min-width:0;flex:1;gap:4px}.revealed-key code{overflow-wrap:anywhere;color:var(--ink);font-size:9px}.revealed-key span{font-size:8px}.mcp-config{display:grid;gap:10px;margin-top:14px;padding:14px;border:1px solid var(--border);border-radius:10px;background:var(--surface-soft)}.mcp-config>div{display:grid;gap:3px}.mcp-config strong{font-size:10px}.mcp-config span{color:var(--muted);font-size:8px}.mcp-config pre{max-height:230px;margin:0;padding:12px;overflow:auto;border-radius:8px;background:#1d1721;color:#f4eaf6;font-size:8px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}.mcp-config .button{width:max-content}@media(max-width:900px){.developer-grid{grid-template-columns:1fr}.revealed-key{flex-wrap:wrap}}
</style>
