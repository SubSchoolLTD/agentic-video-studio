<script setup lang="ts">
import { Activity, Braces, Check, Copy, KeyRound, Plus, RadioTower, Send, ShieldCheck, X } from 'lucide-vue-next'

const { api, projectId, apiBase } = useApi()
const grafanaUrl = useRuntimeConfig().public.grafanaUrl
const { show } = useToast()
const keyModal = ref(false)
const webhookModal = ref(false)
const revealedKey = ref('')
const keyForm = reactive({ name: 'Local automation', scopes: ['projects:read', 'ideas:write', 'generations:write', 'videos:read'] })
const webhookForm = reactive({ url: 'https://example.com/webhooks/framewise', events: ['generation.completed', 'publication.published'] })
const { data, refresh } = await useAsyncData('developer', async () => {
  const [keys, webhooks] = await Promise.all([
    api<any>(`/v1/projects/${projectId.value}/api-keys`),
    api<any>(`/v1/projects/${projectId.value}/webhooks`),
  ])
  return { keys: keys.items, webhooks: webhooks.items }
}, { default: () => ({ keys: [], webhooks: [] }) })

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
      <button class="button button--primary" @click="keyModal = true"><Plus :size="15" /> Create API key</button>
    </UiPageHeader>

    <div class="developer-grid">
      <UiAppCard>
        <div class="section-heading"><div><h2>API keys</h2><p>Prefixes are visible; hashes are stored.</p></div><KeyRound :size="18" /></div>
        <div v-if="data.keys.length" class="developer-list">
          <article v-for="item in data.keys" :key="item.id"><div><strong>{{ item.name }}</strong><span><code>{{ item.key_prefix }}…</code> · {{ item.scopes.join(', ') }}</span></div><UiStatusBadge :status="item.revoked_at ? 'revoked' : 'active'" /></article>
        </div>
        <div v-else class="mini-empty">No user-created keys. The local demo token is limited to development.</div>
      </UiAppCard>
      <UiAppCard>
        <div class="section-heading"><div><h2>Webhooks</h2><p>At-least-once delivery with event IDs.</p></div><button class="button button--small" @click="webhookModal=true"><Plus :size="13" /> Add</button></div>
        <div v-if="data.webhooks.length" class="developer-list">
          <article v-for="item in data.webhooks" :key="item.id"><div><strong>{{ item.url }}</strong><span>{{ item.events.join(', ') }}</span></div><button class="button button--small" @click="testWebhook(item.id)"><Send :size="12" /> Test</button></article>
        </div>
        <div v-else class="mini-empty">No endpoints registered.</div>
      </UiAppCard>
    </div>

    <UiAppCard class="mcp-card"><span class="mcp-card__icon"><RadioTower :size="21" /></span><div><strong>Framewise MCP server</strong><span>Tools: project context, source ingestion, research, ideas, generation, review, publication and analytics. Resources expose immutable evidence and version manifests.</span><code>python -m apps.mcp.server</code></div><ShieldCheck :size="20" /></UiAppCard>

    <div v-if="keyModal" class="modal-backdrop" @click.self="keyModal=false">
      <form class="modal" @submit.prevent="revealedKey ? keyModal=false : createKey()">
        <div class="modal__header"><div><h2>Create API key</h2><p>Use the narrowest scopes that support the integration.</p></div><button type="button" class="icon-button icon-button--plain" @click="keyModal=false"><X :size="18" /></button></div>
        <div class="modal__body">
          <div v-if="!revealedKey" class="field"><label>Name</label><input v-model="keyForm.name" required /></div>
          <div v-if="!revealedKey" class="scope-grid"><label v-for="scope in keyForm.scopes" :key="scope"><Check :size="12" /> {{ scope }}</label></div>
          <div v-else class="revealed-key"><KeyRound :size="20" /><div><strong>Copy this key now</strong><code>{{ revealedKey }}</code><span>It cannot be recovered after this dialog closes.</span></div><button type="button" class="button" @click="copyKey"><Copy :size="13" /> Copy</button></div>
        </div>
        <div class="modal__footer"><button type="button" class="button" @click="keyModal=false">Cancel</button><button class="button button--primary">{{ revealedKey ? 'Done' : 'Create once' }}</button></div>
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
.developer-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.developer-list{display:grid}.developer-list article{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)}.developer-list article:last-child{border-bottom:0}.developer-list article>div{display:grid;gap:3px}.developer-list strong{font-size:10px}.developer-list span{max-width:420px;overflow:hidden;color:var(--muted);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.developer-list code{font-size:8px}.mini-empty{display:grid;min-height:100px;place-items:center;color:var(--muted);font-size:9px;text-align:center}.mcp-card{display:flex;align-items:center;gap:12px;margin-top:15px}.mcp-card__icon{display:grid;width:42px;height:42px;place-items:center;border-radius:12px;background:var(--primary-50);color:var(--primary-600)}.mcp-card>div{display:grid;flex:1;gap:3px}.mcp-card strong{font-size:11px}.mcp-card span{color:var(--muted);font-size:9px;line-height:1.5}.mcp-card code{width:max-content;margin-top:4px;padding:5px 7px;border-radius:6px;background:#211a25;color:#f4eaf6;font-size:8px}.scope-grid{display:flex;flex-wrap:wrap;gap:7px;margin-top:14px}.scope-grid label{display:flex;align-items:center;gap:5px;padding:6px 8px;border-radius:7px;background:var(--surface-soft);color:var(--muted-strong);font-size:8px}.revealed-key{display:flex;align-items:flex-start;gap:10px;padding:13px;border-radius:10px;background:var(--amber-soft);color:#9b6707}.revealed-key>div{display:grid;min-width:0;flex:1;gap:4px}.revealed-key code{overflow-wrap:anywhere;color:var(--ink);font-size:9px}.revealed-key span{font-size:8px}@media(max-width:900px){.developer-grid{grid-template-columns:1fr}.revealed-key{flex-wrap:wrap}}
</style>
