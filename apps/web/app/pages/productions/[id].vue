<script setup lang="ts">
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, CircleDollarSign, Clock3, Download, ExternalLink, FileText, Film, ImageIcon, Lock, Maximize2, RadioTower, RotateCcw, ShieldCheck, Sparkles, WandSparkles, X } from 'lucide-vue-next'

const route = useRoute()
const { api, apiBase } = useApi()
const { show } = useToast()
const jobId = String(route.params.id)
const activeTab = ref('overview')
const approving = ref(false)
const regenerateId = ref<string | null>(null)
const retryingStage = ref<string | null>(null)
const selectedVersionId = ref('')
const previewScene = ref<any>(null)
let poller: ReturnType<typeof setInterval> | null = null

const { data: job, refresh: refreshJob } = await useAsyncData(`job-${jobId}`, () => api<any>(`/v1/generation-jobs/${jobId}`))
const video = ref<any>(null)

const terminal = computed(() => ['ready', 'failed', 'blocked', 'cancelled'].includes(job.value?.status))
const previewVersion = computed(() => video.value?.versions?.find((item: any) => item.id === selectedVersionId.value) || video.value?.versions?.find((item: any) => item.aspect_ratio === '9:16') || video.value?.versions?.[0])
const previewUrl = computed(() => previewVersion.value?.render_url ? `${apiBase}${previewVersion.value.render_url}` : '')
const scenes = computed(() => video.value?.scenes || [])
const score = computed(() => video.value?.score_report || {})
const qa = computed(() => video.value?.qa_report || {})
const script = computed(() => video.value?.script?.script || {})
const subtitleAssets = computed(() => video.value?.subtitle_assets || [])

async function loadVideo() {
  if (job.value?.video_id) {
    video.value = await api(`/v1/videos/${job.value.video_id}`)
    if (!selectedVersionId.value) selectedVersionId.value = previewVersion.value?.id || ''
  }
}

async function tick() {
  await refreshJob()
  if (job.value?.video_id && !video.value) await loadVideo()
  if (terminal.value && poller) { clearInterval(poller); poller = null }
}

function startPolling() {
  if (!poller) poller = setInterval(() => void tick(), 600)
}

onMounted(() => {
  if (job.value?.video_id) void loadVideo()
  if (!terminal.value) startPolling()
})
onBeforeUnmount(() => { if (poller) clearInterval(poller) })

async function approve() {
  const version = previewVersion.value
  if (!version) return
  approving.value = true
  try {
    await api(`/v1/video-versions/${version.id}/approve`, { method: 'POST', body: { comment: 'Approved in production workspace' } })
    show('Video approved', 'The version is now eligible for publication preparation.', 'success')
    await loadVideo()
  }
  catch (error: any) { show('Approval failed', error.message, 'error') }
  finally { approving.value = false }
}

async function regenerate(scene: any) {
  regenerateId.value = scene.id
  try {
    const queued = await api<any>(`/v1/scenes/${scene.id}/regenerate`, { method: 'POST', body: { reason: 'Scene-level review requested a cleaner visual' } })
    show('Selective regeneration queued', 'Veo will replace only this scene and append a new immutable video version.', 'success')
    for (let poll = 0; poll < 240; poll += 1) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      const state = await api<any>(`/v1/scene-regenerations/${queued.regeneration_id}`)
      if (state.status === 'completed') {
        await refreshJob()
        await loadVideo()
        selectedVersionId.value = video.value?.latest_version_id || selectedVersionId.value
        show('Scene regenerated', 'The updated render is ready for review.', 'success')
        return
      }
      if (state.status === 'failed') throw new Error(state.error || 'Scene regeneration failed')
    }
    show('Regeneration is still running', 'You can leave this page; the durable job will continue.', 'success')
  }
  catch (error: any) { show('Regeneration failed', error.message, 'error') }
  finally { regenerateId.value = null }
}

async function retryStage(stage: any) {
  if (!stage) return
  retryingStage.value = stage.name
  try {
    const result = await api<any>(`/v1/generation-jobs/${jobId}/stages/${stage.name}/retry`, { method: 'POST' })
    await refreshJob()
    startPolling()
    show('Stage retry queued', `${stage.name.replaceAll('_', ' ')} will run again; ${result.preserved_stages?.length || 0} completed checkpoints stay intact.`, 'success')
  }
  catch (error: any) { show('Could not retry stage', error.message, 'error') }
  finally { retryingStage.value = null }
}

function formatDuration(ms?: number) { return ms ? `${Math.round(ms / 1000)} sec` : '—' }
function sceneAttempt(scene: any) { return scene.attempts?.find((item: any) => item.aspect_ratio === previewVersion.value?.aspect_ratio) || scene.attempts?.[0] }
function scenePreviewUrl(scene: any) { const url = sceneAttempt(scene)?.preview_url || scene.preview_url; return url ? `${apiBase}${url}` : '' }
function speechQa(scene: any) { return sceneAttempt(scene)?.speech_qa || {} }
function voiceQa(scene: any) { return sceneAttempt(scene)?.voice_qa || {} }
function subtitleUrl(format: string) { const item = subtitleAssets.value.find((asset: any) => asset.format === format); return item?.url ? `${apiBase}${item.url}` : '' }
</script>

<template>
  <div v-if="job">
    <div class="production-breadcrumb"><NuxtLink to="/productions"><ArrowLeft :size="14" /> Productions</NuxtLink><span>/</span><span>{{ job.id }}</span></div>
    <UiPageHeader eyebrow="Production workspace" :title="job.title || 'Video production'" :description="`${job.aspect_ratios?.join(' + ') || '9:16'} · ${job.target_duration_seconds || 30} seconds · ${(job.visual_mode || 'ugc_creator').replaceAll('_', ' ')} · ${job.audio_mode === 'veo_native' ? `Veo native speech · ${(job.native_voice_preset || 'warm_conversational').replaceAll('_', ' ')}` : 'Google TTS voiceover'} · ${job.continue_scenes ? 'continued Veo scenes' : 'independent scenes'} · immutable brand profile v${job.brand_profile_version || 1}`">
      <UiStatusBadge :status="job.status" />
      <a v-if="subtitleUrl('srt')" :href="subtitleUrl('srt')" download="captions.srt" class="button" data-testid="download-captions-srt"><Download :size="14" /> Download SRT</a>
      <a v-if="subtitleUrl('vtt')" :href="subtitleUrl('vtt')" download="captions.vtt" class="button" data-testid="download-captions-vtt"><Download :size="14" /> VTT</a>
      <button v-if="job.status === 'ready' && previewVersion?.status !== 'approved'" class="button button--primary" data-testid="approve-video" :disabled="approving" @click="approve"><Check :size="15" /> {{ approving ? 'Approving…' : 'Approve video' }}</button>
      <NuxtLink v-if="previewVersion?.status === 'approved'" :to="`/publishing?version=${previewVersion.id}`" class="button button--primary">Prepare publication <ExternalLink :size="14" /></NuxtLink>
    </UiPageHeader>

    <div v-if="!terminal" class="live-banner"><span class="live-banner__pulse" /><div><strong>{{ job.current_stage?.replaceAll('_', ' ') }}</strong><span>Durable state saved · safe to leave this page</span></div><strong>{{ Math.round((job.progress || 0) * 100) }}%</strong></div>
    <UiProgressBar v-if="!terminal" :value="job.progress || 0" class="job-progress" />

    <div class="production-hero">
      <UiAppCard class="preview-card">
        <div class="preview-toolbar"><div><span>Preview</span><strong>{{ previewVersion?.aspect_ratio || '9:16' }} · {{ formatDuration(previewVersion?.duration_ms) }}</strong></div><select v-if="video?.versions?.length" v-model="selectedVersionId" class="toolbar-toggle" aria-label="Select final render"><option v-for="version in video.versions" :key="version.id" :value="version.id">{{ version.aspect_ratio }} · {{ version.status }}</option></select></div>
        <div class="video-stage" :class="{ 'video-stage--horizontal': previewVersion?.aspect_ratio === '16:9' }">
          <video v-if="previewUrl" :src="previewUrl" controls playsinline preload="metadata" data-testid="video-preview" />
          <div v-else class="video-placeholder"><span class="video-placeholder__rings"><WandSparkles :size="27" /></span><h3>{{ job.status === 'failed' ? 'Production stopped' : 'Building your production' }}</h3><p v-if="job.status !== 'failed'">{{ job.current_stage?.replaceAll('_', ' ') }} is in progress. Partial artifacts are already saved.</p><p v-else>{{ job.last_error?.message }}</p><UiProgressBar :value="job.progress || 0" /><button v-if="job.status === 'failed'" class="button button--primary retry-primary" :disabled="retryingStage === job.current_stage" data-testid="retry-failed-stage" @click="retryStage(job.stages?.find((item:any) => item.name === job.current_stage))"><RotateCcw :size="14" /> {{ retryingStage ? 'Retrying…' : `Retry ${job.current_stage?.replaceAll('_', ' ')}` }}</button></div>
        </div>
        <div class="preview-meta"><span><Film :size="13" /> H.264 / AAC</span><span><ShieldCheck :size="13" /> {{ previewVersion?.captions_burned_in ? 'Clean captions burned in · no panel' : 'Captions kept as separate SRT / VTT' }}</span><span v-if="previewVersion?.logo_applied"><ImageIcon :size="13" /> Uploaded logo applied</span><span><Lock :size="13" /> Checksum saved</span></div>
      </UiAppCard>

      <UiAppCard class="timeline-card">
        <div class="section-heading"><div><h2>Stage timeline</h2><p>Typed outputs and attempts</p></div><span class="timeline-total"><Clock3 :size="13" /> {{ job.stages?.length || 0 }} stages</span></div>
        <ol class="stage-list">
          <li v-for="(stage, index) in job.stages" :key="stage.name" :class="[`stage-list__item--${stage.status}`]">
            <span class="stage-list__marker"><Check v-if="stage.status === 'completed'" :size="12" /><span v-else>{{ Number(index) + 1 }}</span></span>
            <div><strong>{{ stage.name.replaceAll('_', ' ') }}</strong><small>{{ stage.status }}<template v-if="stage.attempt"> · attempt {{ stage.attempt }}</template></small></div>
            <div class="stage-list__actions"><UiStatusBadge :status="stage.status" /><button v-if="['failed','blocked'].includes(stage.status)" class="icon-button" :aria-label="`Retry ${stage.name.replaceAll('_', ' ')}`" :disabled="retryingStage === stage.name" @click="retryStage(stage)"><RotateCcw :size="13" /></button></div>
          </li>
        </ol>
      </UiAppCard>
    </div>

    <div class="workspace-tabs" role="tablist"><button v-for="tab in ['overview','evidence','script','storyboard','qa','scores']" :key="tab" :class="{ active: activeTab === tab }" @click="activeTab = tab">{{ tab }}</button></div>

    <div v-if="activeTab === 'overview'" class="grid-three workspace-content">
      <UiAppCard><div class="detail-icon"><RadioTower :size="18" /></div><span class="eyebrow">Research</span><h3>{{ job.stages?.find((item:any) => item.name === 'research')?.output?.parallel_request_id || 'Pending' }}</h3><p>Parallel request ID and all retrieved evidence are persisted with the production.</p></UiAppCard>
      <UiAppCard><div class="detail-icon"><CircleDollarSign :size="18" /></div><span class="eyebrow">Provider cost</span><h3>{{ job.actual_cost_usd != null ? `$${Number(job.actual_cost_usd).toFixed(2)} actual` : job.provider_cost_estimate_usd != null ? `$${Number(job.provider_cost_estimate_usd).toFixed(2)} configured estimate` : 'Not reported' }}</h3><p>Budget guard range ${{ job.estimated_cost?.min }}–${{ job.estimated_cost?.max }}. Token charges and the admin price-rule cost basis are recorded in Billing.</p></UiAppCard>
      <UiAppCard><div class="detail-icon"><Sparkles :size="18" /></div><span class="eyebrow">Model trace</span><h3>{{ video?.script?.provider_trace?.model || 'Google pipeline' }}</h3><p>Prompt/model versions remain attached to immutable generation artifacts.</p></UiAppCard>
    </div>

    <UiAppCard v-else-if="activeTab === 'evidence'" class="workspace-content"><div class="section-heading"><div><h2>Claim-to-source trace</h2><p>Retrieved text never gains instruction authority.</p></div><ShieldCheck :size="19" /></div><div class="claim-list"><article v-for="claim in script.source_claim_map || []" :key="claim.id"><span><CheckCircle2 :size="16" /></span><div><strong>{{ claim.claim }}</strong><small>{{ claim.source_ids?.join(', ') }} · confidence {{ Math.round((claim.confidence || 0)*100) }}%</small></div><UiStatusBadge :status="claim.status" /></article></div></UiAppCard>

    <UiAppCard v-else-if="activeTab === 'script'" class="workspace-content"><div class="section-heading"><div><h2>{{ script.title }}</h2><p>Versioned voice script with timed beats</p></div><FileText :size="19" /></div><blockquote>{{ script.hook }}</blockquote><div class="script-beats"><div v-for="beat in script.beats" :key="beat.id"><span>{{ beat.start_sec }}–{{ beat.end_sec }}s</span><p>{{ beat.narration }}</p><small>{{ beat.purpose }}</small></div></div><div class="cta-box"><strong>CTA</strong><span>{{ script.cta }}</span></div></UiAppCard>

    <div v-else-if="activeTab === 'storyboard'" class="scene-grid workspace-content"><UiAppCard v-for="scene in scenes" :key="scene.id" class="scene-card"><div class="scene-card__preview"><video v-if="scenePreviewUrl(scene)" :src="scenePreviewUrl(scene)" controls playsinline preload="metadata" :data-testid="`scene-preview-${scene.position}`" /><div v-else class="scene-card__missing"><Film :size="20" /><span>Scene media unavailable</span></div><span class="scene-number">{{ scene.position || scene.id.split('_').at(-1) }}</span><button v-if="scenePreviewUrl(scene)" class="scene-expand" aria-label="Open scene preview" @click="previewScene = scene"><Maximize2 :size="13" /></button></div><div class="scene-card__head"><div><strong>Scene {{ scene.position || '—' }}</strong><span>{{ scene.duration_target }} sec · attempt {{ scene.attempt }}</span></div><UiStatusBadge :status="scene.status" /></div><p>{{ scene.narration }}</p><div class="scene-speech" :class="{ 'scene-speech--failed': speechQa(scene).passed === false || voiceQa(scene).passed === false }"><ShieldCheck :size="13" /><span v-if="job.audio_mode === 'veo_native'">Speech {{ speechQa(scene).passed ? `${Math.round((speechQa(scene).coverage || 0) * 100)}%` : 'failed' }} · voice {{ voiceQa(scene).mode === 'reference_voice' ? 'reference' : voiceQa(scene).passed ? `${Math.round((voiceQa(scene).similarity || 0) * 100)}% match` : 'changed' }}</span><span v-else>Timing preflight: {{ speechQa(scene).passed === false ? 'too long' : 'fits the scene' }}</span></div><details v-if="speechQa(scene).transcript"><summary>Actual transcript</summary><small>{{ speechQa(scene).transcript }}</small></details><details><summary>Visual prompt</summary><small>{{ scene.visual_prompt }}</small></details><button class="button button--small" :disabled="scene.locked || regenerateId === scene.id" @click="regenerate(scene)"><RotateCcw :size="13" /> {{ regenerateId === scene.id ? 'Queued…' : 'Regenerate scene' }}</button></UiAppCard></div>

    <div v-else-if="activeTab === 'qa'" class="grid-two workspace-content"><UiAppCard><div class="section-heading"><div><h2>Hard gates</h2><p>Scores cannot override these decisions.</p></div><UiStatusBadge :status="qa.hard_gate_passed ? 'passed' : 'review_required'" /></div><div class="gate-list"><div v-for="(value,key) in qa.hard_gates" :key="key"><CheckCircle2 v-if="value" :size="16" /><AlertTriangle v-else :size="16" /><span>{{ String(key).replaceAll('_',' ') }}</span><strong>{{ value ? 'Pass' : 'Block' }}</strong></div></div></UiAppCard><UiAppCard><div class="section-heading"><div><h2>Technical QA</h2><p>Probe results for every ratio</p></div><Film :size="18" /></div><div v-for="(report,index) in qa.technical" :key="index" class="technical-report"><strong>{{ report.actual?.width }} × {{ report.actual?.height }}</strong><span>{{ report.actual?.video_codec }} / {{ report.actual?.audio_codec }} · {{ report.actual?.duration_seconds }} sec</span><UiStatusBadge :status="report.passed ? 'passed' : 'failed'" /></div></UiAppCard><UiAppCard class="speech-report"><div class="section-heading"><div><h2>Speech & timing</h2><p>{{ qa.speech?.mode === 'transcription' ? 'Gemini transcript checks per generated scene' : 'Narration timing before TTS' }}</p></div><UiStatusBadge :status="qa.speech?.passed ? 'passed' : 'failed'" /></div><div v-for="item in qa.speech?.scenes || []" :key="`${item.scene_id}-${item.aspect_ratio}`"><strong>{{ item.scene_id?.split('_').slice(-2).join(' ') }} · {{ item.aspect_ratio }}</strong><span>{{ item.transcript || (item.passed ? 'Timing fits' : item.issues?.join(' · ')) }}</span></div></UiAppCard></div>

    <div v-else-if="activeTab === 'scores'" class="scores-panel workspace-content"><UiAppCard><UiScoreRing :value="score.topic_opportunity || 0" label="Topic" size="large" /><div><h3>Topic opportunity</h3><p>Demand, relevance, freshness, novelty, evidence and format fit before production.</p></div></UiAppCard><UiAppCard><UiScoreRing :value="score.publish_readiness || 0" label="Readiness" size="large" /><div><h3>Publish readiness</h3><p>Independent from predicted performance; all hard gates must still pass.</p></div></UiAppCard><UiAppCard><UiScoreRing :value="score.predicted_performance || 0" label="Prediction" size="large" /><div><h3>Predicted performance</h3><p>Cold-start heuristic, not a viral promise.</p></div></UiAppCard><UiAppCard><UiScoreRing :value="Math.round((score.confidence || 0)*100)" label="Confidence" suffix="%" size="large" /><div><h3>Confidence</h3><p>Below the auto-safe threshold until real publication history exists.</p></div></UiAppCard></div>
    <div v-if="previewScene" class="modal-backdrop" @click.self="previewScene = null"><section class="modal scene-modal"><div class="modal__header"><div><h2>Scene {{ previewScene.position }}</h2><p>{{ previewScene.duration_target }} seconds · attempt {{ previewScene.attempt }} · {{ previewVersion?.aspect_ratio || '9:16' }}</p></div><button class="icon-button icon-button--plain" aria-label="Close scene preview" @click="previewScene = null"><X :size="18" /></button></div><div class="modal__body"><video :src="scenePreviewUrl(previewScene)" controls autoplay playsinline data-testid="scene-modal-video" /><p>{{ previewScene.narration }}</p><div class="scene-speech"><ShieldCheck :size="14" /><span>{{ speechQa(previewScene).passed ? 'Speech and timing QA passed' : speechQa(previewScene).issues?.join(' · ') || 'Timing preflight passed' }}</span></div></div><div class="modal__footer"><button class="button" @click="previewScene = null">Close</button><button class="button button--primary" :disabled="previewScene.locked || regenerateId === previewScene.id" @click="regenerate(previewScene); previewScene = null"><RotateCcw :size="13" /> Regenerate this scene</button></div></section></div>
  </div>
</template>

<style scoped>
.production-breadcrumb{display:flex;align-items:center;gap:7px;margin-bottom:18px;color:var(--muted);font-size:9px}.production-breadcrumb a{display:flex;align-items:center;gap:5px;color:var(--primary-700);font-weight:700}.live-banner{display:flex;align-items:center;gap:10px;padding:10px 13px;border:1px solid #cfe4f1;border-radius:10px 10px 0 0;background:var(--blue-soft);color:var(--blue)}.live-banner__pulse{width:7px;height:7px;border-radius:50%;background:var(--blue);box-shadow:0 0 0 4px rgb(36 117 175 / 11%);animation:pulse 1.6s infinite}.live-banner div{display:grid;flex:1;gap:1px}.live-banner strong{font-size:10px;text-transform:capitalize}.live-banner span{font-size:8px}.job-progress{border-radius:0 0 99px 99px}.production-hero{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,.8fr);gap:15px;margin-top:15px}.preview-card,.timeline-card{min-height:590px}.preview-toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.preview-toolbar>div:first-child{display:grid;gap:2px}.preview-toolbar span{color:var(--muted);font-size:8px;text-transform:uppercase}.preview-toolbar strong{font-size:11px}.toolbar-toggle{display:flex;align-items:center;gap:5px;padding:6px 8px;border:1px solid var(--border);border-radius:8px;background:white;font-size:8px}.video-stage{display:grid;min-height:475px;place-items:center;overflow:hidden;border-radius:13px;background:radial-gradient(circle at 50% 30%,#352341,#120f17 65%);box-shadow:inset 0 0 0 1px rgb(255 255 255 / 7%)}.video-stage video{max-width:100%;height:475px;max-height:62vh;border-radius:8px;background:black;object-fit:contain}.video-stage--horizontal{min-height:340px}.video-stage--horizontal video{width:100%;height:auto}.video-placeholder{display:grid;width:min(300px,80%);place-items:center;color:white;text-align:center}.video-placeholder__rings{display:grid;width:66px;height:66px;place-items:center;border:1px solid rgb(255 255 255 / 12%);border-radius:50%;background:rgb(255 255 255 / 5%);color:var(--primary-300);box-shadow:0 0 0 14px rgb(255 255 255 / 2%),0 0 0 28px rgb(255 255 255 / 1%)}.video-placeholder h3{margin:30px 0 7px;font-family:var(--font-display);font-size:16px}.video-placeholder p{margin:0 0 17px;color:#afa6b8;font-size:9px;line-height:1.55}.video-placeholder .progress-bar{width:100%;background:rgb(255 255 255 / 9%)}.preview-meta{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;color:var(--muted);font-size:8px}.preview-meta span{display:flex;align-items:center;gap:5px}.timeline-total{display:flex;align-items:center;gap:5px;color:var(--muted);font-size:8px}.stage-list{display:grid;margin:0;padding:0;list-style:none}.stage-list li{position:relative;display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:9px;min-height:43px}.stage-list li:not(:last-child)::after{position:absolute;top:30px;bottom:-13px;left:11px;width:1px;background:var(--border);content:''}.stage-list__marker{position:relative;z-index:1;display:grid;width:23px;height:23px;place-items:center;border:1px solid var(--border);border-radius:50%;background:white;color:var(--muted);font-size:8px}.stage-list__item--completed .stage-list__marker{border-color:var(--green);background:var(--green);color:white}.stage-list__item--running .stage-list__marker{border-color:var(--blue);background:var(--blue-soft);color:var(--blue)}.stage-list li>div{display:grid;gap:1px}.stage-list li>div strong{font-size:9px;text-transform:capitalize}.stage-list li>div small{color:var(--muted);font-size:7px;text-transform:capitalize}.workspace-tabs{display:flex;gap:2px;margin-top:20px;border-bottom:1px solid var(--border)}.workspace-tabs button{padding:10px 13px;border-bottom:2px solid transparent;background:transparent;color:var(--muted);font-size:9px;font-weight:800;text-transform:capitalize}.workspace-tabs button.active{border-color:var(--primary-600);color:var(--primary-700)}.workspace-content{margin-top:14px}.workspace-content>.app-card h3{margin:9px 0 5px;font-family:var(--font-display);font-size:14px}.workspace-content>.app-card p{margin:0;color:var(--muted);font-size:9px;line-height:1.55}.detail-icon{display:grid;width:35px;height:35px;place-items:center;margin-bottom:14px;border-radius:10px;background:var(--primary-50);color:var(--primary-600)}.claim-list{display:grid}.claim-list article{display:flex;align-items:center;gap:9px;padding:10px 0;border-bottom:1px solid var(--border)}.claim-list article>span{color:var(--green)}.claim-list article>div{display:grid;min-width:0;flex:1;gap:2px}.claim-list strong{overflow:hidden;font-size:9px;text-overflow:ellipsis;white-space:nowrap}.claim-list small{color:var(--muted);font-size:7px}.workspace-content blockquote{margin:5px 0 16px;padding:13px;border-left:3px solid var(--primary-500);background:var(--primary-50);font-family:var(--font-display);font-size:14px}.script-beats{display:grid}.script-beats>div{display:grid;grid-template-columns:60px 1fr auto;align-items:center;gap:9px;padding:9px 0;border-bottom:1px solid var(--border)}.script-beats span,.script-beats small{color:var(--muted);font-size:8px}.script-beats p{font-size:9px!important}.cta-box{display:flex;align-items:center;gap:10px;margin-top:13px;padding:10px;border-radius:9px;background:var(--green-soft);color:var(--green);font-size:9px}.scene-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.scene-card__preview{position:relative;display:grid;height:170px;place-items:center;overflow:hidden;border-radius:10px;background:linear-gradient(145deg,#32213e,#16111b);color:var(--primary-300)}.scene-card__preview video{width:100%;height:100%;background:#120f17;object-fit:contain}.scene-card__missing{display:grid;place-items:center;gap:7px;color:var(--muted);font-size:8px}.scene-number{position:absolute;top:9px;left:9px;padding:4px 6px;border-radius:6px;background:rgb(0 0 0 / 55%);color:white;font-size:8px}.scene-expand{position:absolute;top:8px;right:8px;display:grid;width:27px;height:27px;place-items:center;border-radius:7px;background:rgb(0 0 0 / 58%);color:white}.scene-card__head{display:flex;align-items:center;justify-content:space-between;margin-top:11px}.scene-card__head>div{display:grid;gap:1px}.scene-card__head strong{font-size:10px}.scene-card__head span{color:var(--muted);font-size:7px}.scene-card>p{min-height:42px!important;margin-top:9px!important}.scene-card details{margin:8px 0;color:var(--muted);font-size:8px}.scene-card summary{cursor:pointer;font-weight:700}.scene-card details small{display:block;margin-top:5px;line-height:1.5}.scene-card .button{width:100%}.scene-speech{display:flex;align-items:flex-start;gap:6px;margin:8px 0;padding:7px;border-radius:7px;background:var(--green-soft);color:var(--green);font-size:7px;line-height:1.4}.scene-speech--failed{background:var(--red-soft);color:var(--red)}.gate-list{display:grid}.gate-list>div{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:8px;padding:9px 0;border-bottom:1px solid var(--border);color:var(--green)}.gate-list span{color:var(--ink);font-size:9px;text-transform:capitalize}.gate-list strong{font-size:8px}.technical-report{display:grid;grid-template-columns:1fr auto;gap:3px;padding:10px 0;border-bottom:1px solid var(--border)}.technical-report strong{font-size:10px}.technical-report>span{grid-row:2;color:var(--muted);font-size:8px}.technical-report .status-badge{grid-row:1 / 3;grid-column:2;align-self:center}.speech-report{grid-column:1/-1}.speech-report>div:not(.section-heading){display:grid;grid-template-columns:130px 1fr;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)}.speech-report strong{font-size:8px}.speech-report span{color:var(--muted);font-size:8px}.scores-panel{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.scores-panel>.app-card{display:flex;align-items:center;gap:17px}.scores-panel h3{margin:0 0 5px!important}.scores-panel p{margin:0!important}.scene-modal{width:min(760px,calc(100vw - 32px))}.scene-modal video{display:block;width:100%;max-height:65vh;border-radius:12px;background:#120f17}.scene-modal p{color:var(--muted-strong);font-size:10px;line-height:1.55}@keyframes pulse{50%{opacity:.45}}@media(max-width:1020px){.production-hero{grid-template-columns:1fr}.timeline-card{min-height:auto}.scene-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.preview-card{min-height:auto}.video-stage{min-height:380px}.video-stage video{height:380px}.scene-grid,.scores-panel{grid-template-columns:1fr}.workspace-tabs{overflow-x:auto}.workspace-tabs button{white-space:nowrap}.script-beats>div{grid-template-columns:50px 1fr}.script-beats small{grid-column:2}}
.retry-primary{margin-top:14px}.stage-list__actions{display:flex!important;align-items:center;gap:5px}.stage-list__actions .icon-button{width:26px;height:26px}
</style>
