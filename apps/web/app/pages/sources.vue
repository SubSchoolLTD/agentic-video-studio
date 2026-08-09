<script setup lang="ts">
import { Braces, FileText, Globe2, Plus, Rss, ShieldCheck, Upload, X } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { show } = useToast()
const modalOpen = ref(false)
const saving = ref(false)
const form = reactive({ type: 'rss', name: '', url: '' })
const { data, refresh } = await useAsyncData('sources', async () => {
  const [sources, items] = await Promise.all([api<any>(`/v1/projects/${projectId.value}/sources`), api<any>(`/v1/projects/${projectId.value}/source-items`)])
  return { sources: sources.items, items: items.items }
}, { default: () => ({ sources: [], items: [] }) })
const iconFor = (type: string) => ({ website: Globe2, rss: Rss, api: Braces, text: FileText } as any)[type] || FileText

async function saveSource() {
  saving.value = true
  try {
    await api(`/v1/projects/${projectId.value}/sources`, { method: 'POST', body: { type: form.type, name: form.name, url: form.url || undefined, config: { generation_policy: 'research_then_approval' } } })
    show('Source connected', 'New items will be normalized, deduplicated and checked before research.', 'success')
    modalOpen.value = false
    await refresh()
  }
  catch (error: any) { show('Could not connect source', error.message, 'error') }
  finally { saving.value = false }
}
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Owned inputs" title="Sources" description="Websites, RSS, API and pasted material become one normalized, rights-aware source model."><button class="button"><Upload :size="15" /> Add content</button><button class="button button--primary" @click="modalOpen = true"><Plus :size="15" /> Connect source</button></UiPageHeader>
    <div class="source-grid"><UiAppCard v-for="source in data.sources" :key="source.id" interactive class="source-card"><div class="source-card__head"><span><component :is="iconFor(source.type)" :size="19" /></span><UiStatusBadge :status="source.status" /></div><h3>{{ source.name }}</h3><p>{{ source.url || `${source.type} intake` }}</p><dl><div><dt>Trust</dt><dd>{{ source.trust_level || 'review' }}</dd></div><div><dt>Policy</dt><dd>{{ source.generation_policy?.replaceAll('_',' ') }}</dd></div><div><dt>Last checked</dt><dd>{{ source.last_checked ? 'Today' : 'Not yet' }}</dd></div></dl></UiAppCard><button class="source-add" @click="modalOpen = true"><Plus :size="22" /><strong>Connect another source</strong><span>RSS, website, API or text</span></button></div>
    <UiAppCard class="items-card"><div class="section-heading"><div><h2>Recent source items</h2><p>Canonical URLs, hashes and provenance are preserved.</p></div><span class="rights-pill"><ShieldCheck :size="13" /> Rights required</span></div><div v-if="data.items.length" class="table-wrap"><table class="data-table"><thead><tr><th>Material</th><th>Type</th><th>Language</th><th>Dedupe</th><th>Status</th></tr></thead><tbody><tr v-for="item in data.items" :key="item.id"><td><div class="table-title"><strong>{{ item.title }}</strong><span>{{ item.canonical_url || item.external_id || item.content_hash?.slice(0,16) }}</span></div></td><td>{{ item.source_type }}</td><td>{{ item.language }}</td><td>{{ item.duplicate_status }}</td><td><UiStatusBadge :status="item.status" /></td></tr></tbody></table></div><div v-else class="empty-state"><div><span class="empty-state__icon"><FileText :size="23" /></span><h3>No source items received</h3><p>Send an article through REST, connect an RSS feed, or paste owned content.</p></div></div></UiAppCard>
    <div v-if="modalOpen" class="modal-backdrop" @click.self="modalOpen = false"><form class="modal" @submit.prevent="saveSource"><div class="modal__header"><div><h2>Connect content source</h2><p>Polling and automation policies remain independent.</p></div><button type="button" class="icon-button icon-button--plain" @click="modalOpen = false"><X :size="18" /></button></div><div class="modal__body"><div class="form-grid"><div class="field"><label>Source type</label><select v-model="form.type"><option value="rss">RSS / Atom</option><option value="website">Website</option><option value="api">REST API</option><option value="manual">Manual intake</option></select></div><div class="field"><label>Name</label><input v-model="form.name" required placeholder="SubSchool blog" /></div><div v-if="!['api','manual'].includes(form.type)" class="field field--full"><label>Public URL</label><input v-model="form.url" type="url" required placeholder="https://subschool.us/rss.xml" /></div></div><label class="checkbox-row"><input type="checkbox" checked /> I own this content or have permission to use it in generated media.</label></div><div class="modal__footer"><button type="button" class="button" @click="modalOpen = false">Cancel</button><button class="button button--primary" :disabled="saving">{{ saving ? 'Connecting…' : 'Connect source' }}</button></div></form></div>
  </div>
</template>

<style scoped>
.source-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.source-card__head{display:flex;align-items:center;justify-content:space-between}.source-card__head>span{display:grid;width:38px;height:38px;place-items:center;border-radius:11px;background:var(--primary-50);color:var(--primary-600)}.source-card h3{margin:15px 0 4px;font-family:var(--font-display);font-size:13px}.source-card>p{overflow:hidden;margin:0;color:var(--muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.source-card dl{display:grid;margin:14px 0 0}.source-card dl div{display:flex;justify-content:space-between;padding:6px 0;border-top:1px solid var(--border)}.source-card dt{color:var(--muted);font-size:8px}.source-card dd{margin:0;font-size:8px;font-weight:600;text-transform:capitalize}.source-add{display:grid;min-height:190px;place-items:center;align-content:center;gap:5px;border:1px dashed var(--border-strong);border-radius:var(--radius);background:transparent;color:var(--primary-600)}.source-add strong{margin-top:5px;color:var(--ink);font-size:11px}.source-add span{color:var(--muted);font-size:8px}.items-card{margin-top:15px}.rights-pill{display:flex;align-items:center;gap:5px;padding:5px 8px;border-radius:99px;background:var(--green-soft);color:var(--green);font-size:8px;font-weight:700}@media(max-width:1050px){.source-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:580px){.source-grid{grid-template-columns:1fr}}
</style>

