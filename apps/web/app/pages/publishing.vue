<script setup lang="ts">
import { AlertTriangle, CalendarClock, Check, Download, RefreshCw, RotateCcw, Send, ShieldCheck, X } from 'lucide-vue-next'

const { api, projectId, apiBase } = useApi()
const { show } = useToast()
const route = useRoute()
const composerOpen = ref(Boolean(route.query.version))
const preparing = ref(false)
const confirming = ref(false)
const plan = ref<any>(null)
const form = reactive<any>({
  video_version_id: String(route.query.version || ''),
  connection_id: '',
  platform: 'youtube',
  title: '',
  caption: '',
  privacy: 'private',
  allow_comments: true,
  allow_duet: false,
  allow_stitch: false,
  creator_info_acknowledged: false,
})

const { data, refresh } = await useAsyncData('publishing-data', async () => {
  const [videos, connections, publications] = await Promise.all([
    api<any>(`/v1/projects/${projectId.value}/videos`),
    api<any>(`/v1/projects/${projectId.value}/connections`),
    api<any>(`/v1/projects/${projectId.value}/publications`),
  ])
  return { videos: videos.items, connections: connections.items, publications: publications.items }
}, { default: () => ({ videos: [], connections: [], publications: [] }) })

const versions = computed(() => data.value.videos.flatMap((video: any) => (video.versions || []).map((version: any) => ({
  ...version,
  title: video.title,
  status: version.status,
}))))
const publishableConnections = computed(() => data.value.connections.filter((item: any) => (
  ['active', 'healthy'].includes(item.status) && !String(item.id).startsWith('unconfigured_')
)))

watchEffect(() => {
  if (!form.video_version_id && versions.value[0]) form.video_version_id = versions.value[0].id
  const version = versions.value.find((item: any) => item.id === form.video_version_id)
  if (version && !form.title) form.title = version.title || 'Video publication'
  if (!publishableConnections.value.some((item: any) => item.id === form.connection_id) && publishableConnections.value[0]) {
    form.connection_id = publishableConnections.value[0].id
    form.platform = publishableConnections.value[0].provider
  }
})

const selectedVersion = computed(() => versions.value.find((item: any) => item.id === form.video_version_id))
const selectedConnection = computed(() => publishableConnections.value.find((item: any) => item.id === form.connection_id))
const tiktokPrivacyOptions = computed(() => selectedConnection.value?.creator_info?.privacy_level_options || ['SELF_ONLY'])

async function prepare() {
  if (!form.connection_id) {
    show('Connect a platform first', 'Open Connections and sign in to the account that should receive this video.', 'info')
    return
  }
  preparing.value = true
  try {
    plan.value = await api('/v1/publications', {
      method: 'POST',
      headers: { 'Idempotency-Key': `composer-${Date.now()}` },
      body: { ...form, synthetic_media_disclosure: true, made_for_kids: false },
    })
    show('Publication plan prepared', 'Review the provider warning before the final publish action.', 'success')
  }
  catch (error: any) {
    show('Could not prepare publication', error.message, 'error')
  }
  finally {
    preparing.value = false
  }
}

async function commit() {
  confirming.value = true
  try {
    await api(`/v1/publications/${plan.value.publication_id}/confirm`, {
      method: 'POST',
      body: {
        confirmation_token: plan.value.confirmation_token,
        explicit_consent: plan.value.requires_user_consent,
      },
    })
    show('Video published', 'The provider web composer confirmed the upload.', 'success')
    composerOpen.value = false
    plan.value = null
    await refresh()
  }
  catch (error: any) {
    show('Publication failed', error.message, 'error')
  }
  finally {
    confirming.value = false
  }
}

function changeConnection() {
  form.platform = selectedConnection.value?.provider || 'youtube'
  form.privacy = form.platform === 'tiktok'
    ? (selectedConnection.value?.creator_info?.privacy_level_options?.[0] || 'SELF_ONLY')
    : form.platform === 'instagram' ? 'public' : 'private'
  form.creator_info_acknowledged = false
  plan.value = null
}

async function refreshStatus(item: any) {
  try {
    await api(`/v1/publications/${item.id}/refresh-status`, { method: 'POST' })
    await refresh()
    show('Publication status refreshed', item.title, 'success')
  }
  catch (error: any) {
    show('Status refresh failed', error.message, 'error')
  }
}

async function retryPublication(item: any) {
  try {
    await api(`/v1/publications/${item.id}/retry`, { method: 'POST' })
    await refresh()
    show('Retry evaluated', 'A new attempt is allowed only when the previous post definitely did not reach the provider.', 'success')
  }
  catch (error: any) {
    show('Retry blocked', error.message, 'error')
  }
}
</script>

<template>
  <div>
    <UiPageHeader
      eyebrow="Browser publishing"
      title="Publishing"
      description="Connected browser sessions upload through each provider's regular website. Instagram and TikTok always require your final confirmation."
    >
      <button class="button button--primary" @click="composerOpen = true"><Send :size="15" /> Compose publication</button>
    </UiPageHeader>

    <div class="publish-summary">
      <UiAppCard><span>Ready to publish</span><strong>{{ versions.filter((item: any) => item.status === 'approved').length }}</strong><small>Approved immutable versions</small></UiAppCard>
      <UiAppCard><span>Processing</span><strong>{{ data.publications.filter((item: any) => ['queued', 'uploading', 'processing'].includes(item.status)).length }}</strong><small>Provider-side state</small></UiAppCard>
      <UiAppCard><span>Published</span><strong>{{ data.publications.filter((item: any) => item.status === 'published').length }}</strong><small>Confirmed provider uploads</small></UiAppCard>
      <UiAppCard><span>Needs action</span><strong>{{ data.publications.filter((item: any) => ['awaiting_consent', 'blocked', 'rejected', 'reauth', 'retryable_failure'].includes(item.status)).length }}</strong><small>Consent, retry or sign-in</small></UiAppCard>
    </div>

    <UiAppCard class="publishing-table">
      <div class="section-heading">
        <div><h2>Publication jobs</h2><p>Browser upload, provider confirmation and unknown remote outcomes stay distinct.</p></div>
        <ShieldCheck :size="18" />
      </div>
      <div v-if="data.publications.length" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Title</th><th>Platform</th><th>Status</th><th>Privacy</th><th>Scheduled</th><th>Actions</th></tr></thead>
          <tbody>
            <tr v-for="item in data.publications" :key="item.id">
              <td>{{ item.title }}</td><td>{{ item.platform }}</td><td><UiStatusBadge :status="item.status" /></td><td>{{ item.privacy || 'provider choice' }}</td><td>{{ item.scheduled_at || 'Immediate' }}</td>
              <td><div class="row-actions"><button v-if="['uploading', 'processing', 'retryable_failure'].includes(item.status)" class="icon-button" title="Refresh publication status" @click="refreshStatus(item)"><RefreshCw :size="13" /></button><button v-if="item.status === 'retryable_failure'" class="icon-button" title="Retry safely" @click="retryPublication(item)"><RotateCcw :size="13" /></button><a v-if="item.export_package_url" class="icon-button" :href="`${apiBase}${item.export_package_url}`" download title="Download package"><Download :size="13" /></a></div></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state"><div><span class="empty-state__icon"><Send :size="23" /></span><h3>No publication jobs yet</h3><p>Approve a video version, connect an account, then prepare a publication.</p></div></div>
    </UiAppCard>

    <div v-if="composerOpen" class="modal-backdrop" @click.self="composerOpen = false">
      <form class="modal publish-modal" @submit.prevent="plan ? commit() : prepare()">
        <div class="modal__header"><div><h2>Publish composer</h2><p>The final action uploads through the connected account's normal web interface.</p></div><button type="button" class="icon-button icon-button--plain" @click="composerOpen = false"><X :size="18" /></button></div>
        <div class="modal__body">
          <div v-if="selectedVersion" class="composer-preview"><video :src="`${apiBase}${selectedVersion.render_url}`" muted playsinline /><div><strong>{{ selectedVersion.title }}</strong><span>{{ selectedVersion.aspect_ratio }} · {{ Math.round(selectedVersion.duration_ms / 1000) }} sec</span><UiStatusBadge :status="selectedVersion.status" /></div></div>
          <div v-if="!publishableConnections.length" class="provider-warning"><AlertTriangle :size="17" /><div><strong>No connected account</strong><span>Open Connections, sign in to Instagram, TikTok or YouTube, then return to publish.</span><NuxtLink to="/connections" class="text-link">Open Connections</NuxtLink></div></div>
          <div class="form-grid">
            <div class="field field--full"><label for="publication-version">Video version</label><select id="publication-version" v-model="form.video_version_id"><option v-for="version in versions" :key="version.id" :value="version.id">{{ version.title }} · {{ version.aspect_ratio }} · {{ version.status }}</option></select></div>
            <div class="field"><label for="publication-account">Platform account</label><select id="publication-account" v-model="form.connection_id" @change="changeConnection"><option v-for="connection in publishableConnections" :key="connection.id" :value="connection.id">{{ connection.display_name }} · {{ connection.provider }}</option></select></div>
            <div v-if="form.platform !== 'tiktok'" class="field"><label for="publication-privacy">Privacy</label><select id="publication-privacy" v-model="form.privacy" :disabled="form.platform === 'instagram'"><option v-if="form.platform !== 'instagram'" value="private">Private</option><option v-if="form.platform !== 'instagram'" value="unlisted">Unlisted</option><option value="public">Public</option></select></div>
            <div v-else class="field"><label for="publication-tiktok-privacy">TikTok privacy</label><select id="publication-tiktok-privacy" v-model="form.privacy"><option v-for="privacy in tiktokPrivacyOptions" :key="privacy" :value="privacy">{{ String(privacy).replaceAll('_', ' ') }}</option></select></div>
            <div class="field field--full"><label for="publication-title">Title</label><input id="publication-title" v-model="form.title" required /></div>
            <div class="field field--full"><label for="publication-caption">Caption / description</label><textarea id="publication-caption" v-model="form.caption" /></div>
          </div>
          <div v-if="['instagram', 'tiktok'].includes(form.platform)" class="provider-warning"><AlertTriangle :size="17" /><div><strong>{{ selectedConnection?.display_name || 'Social account not connected' }}</strong><span>Framewise will open the saved browser session, upload this file and press the provider's publish button only after your confirmation below.</span></div></div>
          <div v-if="form.platform === 'tiktok'" class="tiktok-controls"><label><input v-model="form.creator_info_acknowledged" type="checkbox" /> I reviewed the account, video and privacy</label><label><input v-model="form.allow_comments" type="checkbox" /> Allow comments</label><label><input v-model="form.allow_duet" type="checkbox" /> Allow duet</label><label><input v-model="form.allow_stitch" type="checkbox" /> Allow stitch</label></div>
          <div v-if="plan" class="publication-plan"><Check :size="17" /><div><strong>{{ plan.summary }}</strong><span>{{ plan.requires_user_consent ? 'Your final confirmation is required' : 'Ready to publish' }}</span><small v-for="warning in plan.warnings" :key="warning">{{ warning }}</small></div></div>
        </div>
        <div class="modal__footer"><button type="button" class="button" @click="composerOpen = false">Cancel</button><button v-if="!plan" class="button button--primary" data-testid="prepare-publication" :disabled="preparing || !form.connection_id || selectedVersion?.status !== 'approved'"><CalendarClock :size="14" /> {{ preparing ? 'Preparing…' : 'Prepare plan' }}</button><button v-else class="button button--primary" data-testid="confirm-publication" :disabled="confirming"><Send :size="14" /> {{ confirming ? 'Publishing in browser…' : 'Confirm and publish' }}</button></div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.publish-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.publish-summary .app-card{display:grid;gap:3px;padding:14px 16px}.publish-summary span{color:var(--muted);font-size:8px;text-transform:uppercase}.publish-summary strong{font-family:var(--font-display);font-size:22px}.publish-summary small{color:var(--muted);font-size:8px}.publishing-table{margin-top:15px}.publish-modal{width:min(720px,100%)}.composer-preview{display:flex;align-items:center;gap:12px;margin-bottom:16px;padding:10px;border:1px solid var(--border);border-radius:11px;background:var(--surface-soft)}.composer-preview video{width:70px;height:105px;border-radius:7px;background:#17131f;object-fit:contain}.composer-preview>div{display:grid;gap:4px}.composer-preview strong{font-size:11px}.composer-preview span{color:var(--muted);font-size:8px}.provider-warning,.publication-plan{display:flex;gap:9px;margin-top:14px;padding:10px;border-radius:9px;background:var(--amber-soft);color:#9b6707}.provider-warning>div,.publication-plan>div{display:grid;gap:2px}.provider-warning strong,.publication-plan strong{font-size:9px}.provider-warning span,.publication-plan span,.publication-plan small{font-size:8px;line-height:1.45}.publication-plan{background:var(--green-soft);color:var(--green)}.row-actions{display:flex;gap:5px}.tiktok-controls{display:grid;gap:8px;margin-top:12px}.tiktok-controls>label{display:flex;align-items:center;gap:7px;color:var(--muted-strong);font-size:9px}.tiktok-controls input{width:auto}@media(max-width:800px){.publish-summary{grid-template-columns:repeat(2,1fr)}}@media(max-width:500px){.publish-summary{grid-template-columns:1fr}}
</style>
