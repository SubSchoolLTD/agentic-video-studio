<script setup lang="ts">
import { CheckCircle2, Download, ExternalLink, Link2, RefreshCw, ShieldCheck, Unplug } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { show } = useToast()
const busyProvider = ref('')
const { data, refresh } = await useAsyncData(
  'connections',
  () => api<any>(`/v1/projects/${projectId.value}/connections`),
  { default: () => ({ items: [] }) },
)

const descriptions: Record<string, string> = {
  youtube: 'Official OAuth and resumable uploads with privacy and synthetic-media disclosure.',
  instagram: 'Capability-aware export fallback; no browser automation or simulated taps.',
  tiktok: 'Interactive consent, creator information and platform-owned privacy selection.',
  export: 'Download final MP4, captions, manifest, evidence and a publishing brief.',
}

async function connect(item: any) {
  busyProvider.value = item.provider
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/connections/${item.provider}/authorize`, { method: 'POST' })
    if (result.authorize_url) {
      window.location.assign(result.authorize_url)
      return
    }
    show(`${item.display_name} adapter checked`, result.action === 'export_fallback' ? 'An export workflow is available.' : 'The connection is ready.', 'success')
    await refresh()
  }
  catch (error: any) {
    show('Connection failed', error.message, 'error')
  }
  finally {
    busyProvider.value = ''
  }
}

async function disconnect(item: any) {
  if (item.id.startsWith('unconfigured_')) return
  try {
    await api(`/v1/connections/${item.id}`, { method: 'DELETE' })
    show(`${item.display_name} disconnected`, 'Stored authorization was revoked.', 'success')
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
      eyebrow="Official APIs only"
      title="Connections"
      description="Each platform declares what it can actually do. Unsupported actions become explicit export or interactive workflows."
    >
      <button class="button" @click="() => refresh()"><RefreshCw :size="15" /> Refresh status</button>
    </UiPageHeader>

    <div class="connection-grid">
      <UiAppCard v-for="item in data.items" :key="item.id" class="connection-card">
        <div class="connection-card__top">
          <span class="provider-mark" :class="`provider-mark--${item.provider}`">
            <Download v-if="item.provider === 'export'" :size="21" />
            <Link2 v-else :size="21" />
          </span>
          <UiStatusBadge :status="item.status" />
        </div>
        <div>
          <h2>{{ item.display_name }}</h2>
          <p>{{ descriptions[item.provider] }}</p>
        </div>
        <div class="capability-list">
          <span v-for="capability in item.capabilities" :key="String(capability)">
            <CheckCircle2 :size="12" /> {{ String(capability).replaceAll('_', ' ') }}
          </span>
        </div>
        <div class="connection-card__actions">
          <button
            class="button button--primary"
            :disabled="busyProvider === item.provider || item.provider === 'export'"
            @click="connect(item)"
          >
            <ExternalLink :size="14" />
            {{ busyProvider === item.provider ? 'Checking…' : item.status === 'not_connected' ? 'Connect' : 'Reconnect' }}
          </button>
          <button v-if="!item.id.startsWith('unconfigured_')" class="button button--danger" @click="disconnect(item)">
            <Unplug :size="14" /> Disconnect
          </button>
        </div>
      </UiAppCard>
    </div>

    <UiAppCard class="security-card">
      <ShieldCheck :size="22" />
      <div><strong>Least-privilege connection policy</strong><span>Tokens are encrypted outside the database; logs store only request IDs and capability metadata.</span></div>
    </UiAppCard>
  </div>
</template>

<style scoped>
.connection-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.connection-card{display:grid;gap:17px}.connection-card__top,.connection-card__actions{display:flex;align-items:center;justify-content:space-between;gap:9px}.provider-mark{display:grid;width:45px;height:45px;place-items:center;border-radius:13px;background:var(--primary-50);color:var(--primary-600)}.provider-mark--youtube{background:var(--red-soft);color:var(--red)}.provider-mark--export{background:var(--green-soft);color:var(--green)}.connection-card h2{margin:0 0 5px;font-family:var(--font-display);font-size:17px}.connection-card p{margin:0;color:var(--muted);font-size:10px;line-height:1.55}.capability-list{display:flex;flex-wrap:wrap;gap:6px;min-height:52px}.capability-list span{display:flex;align-items:center;gap:4px;padding:5px 7px;border-radius:7px;background:var(--surface-soft);color:var(--muted-strong);font-size:8px;text-transform:capitalize}.connection-card__actions{justify-content:flex-start}.security-card{display:flex;align-items:center;gap:11px;margin-top:15px;color:var(--green)}.security-card div{display:grid;gap:2px}.security-card strong{color:var(--ink);font-size:11px}.security-card span{color:var(--muted);font-size:9px}@media(max-width:820px){.connection-grid{grid-template-columns:1fr}}
</style>
