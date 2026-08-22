<script setup lang="ts">
import { ArrowUpRight, Check, ChevronRight, CircleHelp, Clock3, EyeOff, ExternalLink, FileSearch, RadioTower, Search, ShieldCheck, Sparkles, X } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { show } = useToast()
const objective = ref('Find fresh, evidence-backed short-form topics for this project and its primary audience.')
const launchModalOpen = ref(false)
const running = ref(false)
const selectedRun = ref<any>(null)
const selectedCandidate = ref<any>(null)
const candidateSearch = ref('')
const createdWithinDays = ref('')
const minimumScore = ref('')
const topicFilter = ref('')
const statusFilter = ref('visible')
let polling = false

const { data, refresh } = await useAsyncData('research-radar', async () => {
  const [runs, candidates, project, brand, profiles] = await Promise.all([
    api<any>(`/v1/projects/${projectId.value}/research-runs`),
    api<any>(`/v1/projects/${projectId.value}/topic-candidates`),
    api<any>(`/v1/projects/${projectId.value}`),
    api<any>(`/v1/projects/${projectId.value}/brand-profile`),
    api<any>(`/v1/projects/${projectId.value}/research-profiles`),
  ])
  return { runs: runs.items, candidates: candidates.items, project, brand, profiles: profiles.items }
}, { default: () => ({ runs: [], candidates: [], project: {}, brand: {}, profiles: [] }) })

const allCandidates = computed(() => data.value.candidates || [])
const topics = computed<string[]>(() => [...new Set<string>(allCandidates.value.flatMap((item: any) => item.suggested_formats || [item.format]).filter(Boolean))].sort())
const statuses = computed<string[]>(() => [...new Set<string>(allCandidates.value.map((item: any) => String(item.status || '')).filter(Boolean))].sort())
const candidates = computed(() => allCandidates.value.filter((item: any) => {
  const query = candidateSearch.value.trim().toLowerCase()
  const matchesSearch = !query || [item.title, item.angle, item.audience, ...(item.suggested_formats || [])].some(value => String(value || '').toLowerCase().includes(query))
  const createdAfter = createdWithinDays.value ? Date.now() - Number(createdWithinDays.value) * 86_400_000 : 0
  const matchesDate = !createdAfter || new Date(item.created_at || 0).getTime() >= createdAfter
  const matchesScore = !minimumScore.value || Number(item.topic_opportunity_score || 0) >= Number(minimumScore.value)
  const matchesTopic = !topicFilter.value || (item.suggested_formats || [item.format]).includes(topicFilter.value)
  const matchesStatus = statusFilter.value === 'all'
    || (statusFilter.value === 'visible' ? !['muted', 'rejected'].includes(item.status) : item.status === statusFilter.value)
  return matchesSearch && matchesDate && matchesScore && matchesTopic && matchesStatus
}))
const latestRun = computed(() => selectedRun.value || data.value.runs?.[0])
const researchProfile = computed(() => data.value.profiles?.[0])
const cadence = computed(() => researchProfile.value?.interval_hours ? `Every ${researchProfile.value.interval_hours}h` : 'On demand')
const selectedRunForCandidate = computed(() => data.value.runs?.find((run: any) => run.id === selectedCandidate.value?.research_run_id))
const selectedSources = computed(() => {
  const allowed = new Set(selectedCandidate.value?.source_ids || [])
  return (selectedRunForCandidate.value?.sources || []).filter((source: any) => allowed.has(source.id))
})

function freshnessLabel(value?: string) {
  if (!value) return 'freshness unknown'
  const remaining = Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000)
  return remaining > 0 ? `fresh ${remaining} day${remaining === 1 ? '' : 's'}` : 'refresh required'
}

function runDuration(run: any) {
  if (!run?.started_at) return '—'
  const end = run.completed_at ? new Date(run.completed_at).getTime() : Date.now()
  const seconds = Math.max(0, Math.round((end - new Date(run.started_at).getTime()) / 1000))
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

async function pollResearch(runId: string, announce = true) {
  if (polling) return
  polling = true
  running.value = true
  try {
    for (let index = 0; index < 240; index += 1) {
      const state = await api<any>(`/v1/research-runs/${runId}`)
      selectedRun.value = state
      if (['completed', 'failed'].includes(state.status)) {
        await refresh()
        selectedRun.value = data.value.runs?.find((run: any) => run.id === runId) || state
        if (state.status === 'failed') throw new Error(state.error || 'Parallel research failed')
        if (announce) show('Research completed', `${state.candidate_count || state.candidate_ids?.length || 0} new candidates · ${runDuration(state)}`, 'success')
        return
      }
      if (index % 3 === 0) await refresh()
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
    show('Research is still running', 'The durable task will continue; this page will resume tracking it when reopened.', 'success')
  }
  catch (error: any) { show('Research failed', error.message, 'error') }
  finally { running.value = false; polling = false }
}

async function runResearch() {
  running.value = true
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/research-runs`, { method: 'POST', body: { objective: objective.value, max_candidates: 5 } })
    launchModalOpen.value = false
    show('Parallel research started', 'The status and candidate count will update here until the run is actually complete.', 'success')
    await pollResearch(result.research_run_id)
  }
  catch (error: any) { running.value = false; show('Research failed', error.message, 'error') }
}

async function selectCandidate(candidate: any) {
  const result = await api<any>(`/v1/topic-candidates/${candidate.id}/select`, { method: 'POST' })
  show('Idea created', 'The evidence packet remains attached to the idea and future production.', 'success')
  selectedCandidate.value = null
  await refresh()
  await navigateTo(`/ideas?idea=${result.idea_id}`)
}

async function hideCandidate(candidate: any) {
  await api(`/v1/topic-candidates/${candidate.id}/reject`, { method: 'POST', body: { reason_code: 'not_relevant', comment: 'Hidden from the research radar by the editor' } })
  selectedCandidate.value = null
  show('Candidate hidden', 'It was removed from the radar.', 'success')
  await refresh()
}

onMounted(() => {
  const active = data.value.runs?.find((run: any) => ['queued', 'running'].includes(run.status))
  if (active) void pollResearch(active.id, false)
})
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Parallel search" title="Research radar" description="Discover fresh angles before production. Every candidate carries source provenance, freshness, confidence and unresolved questions.">
      <button class="button button--primary" data-testid="run-research" :disabled="running" @click="launchModalOpen = true"><RadioTower :size="16" /> {{ running ? 'Research running…' : 'Run research' }}</button>
    </UiPageHeader>

    <div v-if="running" class="research-running" data-testid="research-running"><span /><div><strong>{{ latestRun?.current_stage === 'candidate_generation' ? 'Turning evidence into candidates' : 'Searching and checking evidence' }}</strong><small>{{ latestRun?.objective }} · elapsed {{ runDuration(latestRun) }}</small></div><UiStatusBadge :status="latestRun?.status || 'queued'" /></div>

    <div class="research-summary">
      <UiAppCard><span>Latest provider</span><strong>Parallel Search</strong><small>{{ latestRun?.parallel_request_ids?.[0] || 'Ready for first live call' }}</small></UiAppCard>
      <UiAppCard><span>Evidence sources</span><strong>{{ latestRun?.sources?.length || 0 }}</strong><small>{{ latestRun?.status === 'completed' ? `Completed in ${runDuration(latestRun)}` : 'Primary sources preferred' }}</small></UiAppCard>
      <UiAppCard><span>Candidates</span><strong>{{ candidates.length }}</strong><small>{{ latestRun?.candidate_count != null ? `${latestRun.candidate_count} from latest run` : 'Ranked before generation' }}</small></UiAppCard>
      <UiAppCard><span>Research cadence</span><strong>{{ cadence }}</strong><small>{{ researchProfile ? 'Configured profile' : 'No schedule configured' }}</small><NuxtLink class="summary-settings-link" to="/settings?tab=automation">Configure automatic research <ArrowUpRight :size="12" /></NuxtLink></UiAppCard>
    </div>

    <div class="grid-two research-layout">
      <UiAppCard>
        <div class="section-heading"><div><h2>Topic candidates</h2><p>Open any card to inspect its evidence before converting it.</p></div><span class="filter-pill"><Sparkles :size="13" /> High relevance</span></div>
        <div class="research-filters" data-testid="research-filters"><label><Search :size="14" /><input v-model="candidateSearch" aria-label="Search research candidates" placeholder="Search title, angle or audience…"></label><select v-model="createdWithinDays" aria-label="Filter candidate creation date"><option value="">Any creation date</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option></select><select v-model="minimumScore" aria-label="Filter minimum opportunity score"><option value="">Any score</option><option value="50">Score 50+</option><option value="70">Score 70+</option><option value="85">Score 85+</option></select><select v-model="topicFilter" aria-label="Filter candidate topic"><option value="">All topics</option><option v-for="topic in topics" :key="topic" :value="topic">{{ topic.replaceAll('_', ' ') }}</option></select><select v-model="statusFilter" aria-label="Filter candidate status"><option value="visible">Visible statuses</option><option value="all">All statuses</option><option v-for="status in statuses" :key="status" :value="status">{{ status.replaceAll('_', ' ') }}</option></select><span>{{ candidates.length }} / {{ allCandidates.length }}</span></div>
        <div v-if="!candidates.length" class="empty-state"><div><span class="empty-state__icon"><Search :size="23" /></span><h3>{{ running ? 'Research is in progress' : 'No research candidates yet' }}</h3><p>{{ running ? 'Cards appear only after both Parallel retrieval and candidate generation finish.' : 'Run a natural-language objective. Parallel will return sources and excerpts; the editor will turn them into ranked angles.' }}</p><button v-if="!running" class="button button--primary" @click="launchModalOpen = true">Run first research</button></div></div>
        <div v-else class="candidate-list">
          <article v-for="candidate in candidates" :key="candidate.id" class="candidate-card" tabindex="0" role="button" @click="selectedCandidate = candidate" @keydown.enter="selectedCandidate = candidate">
            <div class="candidate-card__score"><strong>{{ candidate.topic_opportunity_score }}</strong><span>topic</span></div>
            <div class="candidate-card__body"><div class="candidate-card__meta"><UiStatusBadge :status="candidate.status" /><span><Clock3 :size="12" /> {{ freshnessLabel(candidate.freshness_expires_at) }}</span><span><ShieldCheck :size="12" /> {{ Math.round((candidate.score_confidence || 0) * 100) }}% confidence</span></div><h3>{{ candidate.title }}</h3><p>{{ candidate.angle }}</p><div class="candidate-card__footer"><span>{{ candidate.source_ids?.length || 0 }} cited sources</span><div class="candidate-actions"><button class="text-link" @click.stop="hideCandidate(candidate)"><EyeOff :size="13" /> Hide</button><button class="text-link" @click.stop="selectedCandidate = candidate"><FileSearch :size="13" /> Details</button><button class="text-link" :disabled="candidate.status === 'selected'" @click.stop="selectCandidate(candidate)">{{ candidate.status === 'selected' ? 'Idea created' : 'Turn into idea' }} <ChevronRight :size="13" /></button></div></div></div>
          </article>
        </div>
      </UiAppCard>

      <div class="stack">
        <UiAppCard>
          <div class="section-heading"><div><h2>Evidence packet</h2><p>{{ latestRun?.objective || 'Select a completed run' }}</p></div><UiStatusBadge :status="latestRun?.status || 'idle'" /></div>
          <div v-if="latestRun?.sources?.length" class="evidence-list">
            <a v-for="source in latestRun.sources.slice(0, 5)" :key="source.id" :href="source.url" target="_blank" rel="noreferrer" class="evidence-row"><span class="evidence-row__index">{{ source.id?.split('_').at(-1) }}</span><div><strong>{{ source.title }}</strong><p>{{ source.excerpt }}</p><small>{{ source.source_type }} · relevance {{ Math.round((source.relevance || 0) * 100) }}%</small></div><ExternalLink :size="14" /></a>
          </div>
          <div v-else class="mini-empty"><CircleHelp :size="20" /><p>A completed research run will show traceable sources and claims here.</p></div>
        </UiAppCard>
        <UiAppCard>
          <div class="section-heading"><div><h2>Project research profile</h2><p>{{ data.brand?.identity?.name || data.project?.name || 'Current project' }}</p></div><NuxtLink class="icon-button" to="/settings?tab=automation" aria-label="Configure automatic research"><ArrowUpRight :size="14" /></NuxtLink></div>
          <dl class="profile-list"><div><dt>Regions</dt><dd>{{ data.brand?.identity?.regions?.join(' · ') || 'Not set' }}</dd></div><div><dt>Recency</dt><dd>{{ researchProfile?.recency_days ? `${researchProfile.recency_days} days` : 'Per request' }}</dd></div><div><dt>Audience</dt><dd>{{ data.brand?.audiences?.primary?.join(' · ') || 'Review brand profile' }}</dd></div><div><dt>Coverage</dt><dd>Demand · news · evergreen · competition</dd></div></dl>
        </UiAppCard>
      </div>
    </div>

    <div v-if="launchModalOpen" class="modal-backdrop" @click.self="launchModalOpen = false">
      <form class="modal" @submit.prevent="runResearch">
        <div class="modal__header"><div><h2>Run Parallel research</h2><p>Describe the editorial objective—not a bag of keywords.</p></div><button type="button" class="icon-button icon-button--plain" @click="launchModalOpen = false"><X :size="18" /></button></div>
        <div class="modal__body"><div class="field"><label for="research-objective">Research objective</label><textarea id="research-objective" v-model="objective" required minlength="8" /><small>The run is complete only after evidence and candidate cards are both persisted.</small></div><div class="research-checks"><span><Check :size="14" /> Audience demand</span><span><Check :size="14" /> Fresh developments</span><span><Check :size="14" /> Primary evidence</span><span><Check :size="14" /> Competitive saturation</span></div></div>
        <div class="modal__footer"><button type="button" class="button" @click="launchModalOpen = false">Cancel</button><button class="button button--primary" :disabled="running"><RadioTower :size="15" /> Start research</button></div>
      </form>
    </div>

    <div v-if="selectedCandidate" class="modal-backdrop" data-testid="candidate-details" @click.self="selectedCandidate = null">
      <section class="modal candidate-modal">
        <div class="modal__header"><div><span class="eyebrow">Research candidate</span><h2>{{ selectedCandidate.title }}</h2><p>{{ selectedCandidate.why_now }}</p></div><button class="icon-button icon-button--plain" aria-label="Close candidate details" @click="selectedCandidate = null"><X :size="18" /></button></div>
        <div class="modal__body candidate-detail"><div class="candidate-detail__main"><h3>Editorial angle</h3><p>{{ selectedCandidate.angle }}</p><h3>Supported claims</h3><ul v-if="selectedCandidate.supported_claims?.length"><li v-for="claim in selectedCandidate.supported_claims" :key="claim.id || claim.claim">{{ claim.claim || claim.text }}</li></ul><p v-else class="muted-copy">No factual claim is promoted without attached evidence.</p><h3>Unresolved questions</h3><ul v-if="selectedCandidate.unresolved_questions?.length"><li v-for="question in selectedCandidate.unresolved_questions" :key="question">{{ question }}</li></ul><p v-else class="muted-copy">No unresolved questions were reported.</p></div><aside><dl><div><dt>Audience</dt><dd>{{ selectedCandidate.audience }}</dd></div><div><dt>Objective</dt><dd>{{ selectedCandidate.objective }}</dd></div><div><dt>Format</dt><dd>{{ selectedCandidate.format }}</dd></div><div><dt>Opportunity</dt><dd>{{ selectedCandidate.topic_opportunity_score }}</dd></div><div><dt>Confidence</dt><dd>{{ Math.round((selectedCandidate.score_confidence || 0) * 100) }}%</dd></div></dl><h3>Sources</h3><a v-for="source in selectedSources" :key="source.id" :href="source.url" target="_blank" rel="noreferrer">{{ source.title }} <ExternalLink :size="12" /></a></aside></div>
        <div class="modal__footer"><button class="button" @click="hideCandidate(selectedCandidate)"><EyeOff :size="14" /> Hide</button><button class="button button--primary" :disabled="selectedCandidate.status === 'selected'" @click="selectCandidate(selectedCandidate)">{{ selectedCandidate.status === 'selected' ? 'Idea already created' : 'Turn into idea' }} <ChevronRight :size="14" /></button></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.research-running{display:flex;align-items:center;gap:10px;margin-bottom:13px;padding:11px 13px;border:1px solid #cfe4f1;border-radius:10px;background:var(--blue-soft);color:var(--blue)}.research-running>span{width:8px;height:8px;border-radius:50%;background:var(--blue);animation:pulse 1.4s infinite}.research-running>div{display:grid;flex:1;gap:2px}.research-running strong{font-size:10px}.research-running small{color:var(--muted-strong);font-size:8px}.research-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.research-summary .app-card{display:grid;gap:3px;padding:14px 16px}.research-summary span{color:var(--muted);font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.07em}.research-summary strong{font-family:var(--font-display);font-size:16px}.research-summary small{overflow:hidden;color:var(--muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.research-layout{margin-top:15px;align-items:start}.filter-pill{display:inline-flex;align-items:center;gap:5px;padding:5px 8px;border-radius:99px;background:var(--primary-50);color:var(--primary-700);font-size:9px;font-weight:700}.candidate-list{display:grid;gap:9px}.candidate-card{display:flex;gap:14px;padding:14px;border:1px solid var(--border);border-radius:12px;background:var(--surface-soft);cursor:pointer;transition:.16s}.candidate-card:hover,.candidate-card:focus-visible{border-color:var(--primary-300);background:white;outline:0}.candidate-card__score{display:grid;width:51px;height:51px;flex:none;place-items:center;align-content:center;border-radius:13px;background:linear-gradient(145deg,var(--primary-100),#fff);color:var(--primary-700)}.candidate-card__score strong{font-family:var(--font-display);font-size:18px}.candidate-card__score span{font-size:7px;font-weight:800;text-transform:uppercase}.candidate-card__body{min-width:0;flex:1}.candidate-card__meta{display:flex;flex-wrap:wrap;align-items:center;gap:9px}.candidate-card__meta>span{display:inline-flex;align-items:center;gap:4px;color:var(--muted);font-size:8px}.candidate-card h3{margin:10px 0 4px;font-family:var(--font-display);font-size:13px}.candidate-card p{margin:0;color:var(--muted);font-size:10px;line-height:1.5}.candidate-card__footer{display:flex;align-items:center;justify-content:space-between;margin-top:11px;color:var(--muted);font-size:9px}.candidate-card__footer button{display:flex;align-items:center;border:0;background:transparent}.candidate-actions{display:flex;align-items:center;gap:9px}.evidence-list{display:grid;gap:2px}.evidence-row{display:grid;grid-template-columns:auto 1fr auto;gap:9px;padding:10px 3px;border-bottom:1px solid #efecf0}.evidence-row:last-child{border:0}.evidence-row__index{display:grid;width:23px;height:23px;place-items:center;border-radius:7px;background:var(--blue-soft);color:var(--blue);font-size:8px;font-weight:800}.evidence-row div{min-width:0}.evidence-row strong{display:block;overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.evidence-row p{display:-webkit-box;overflow:hidden;margin:3px 0;color:var(--muted);font-size:8px;line-height:1.45;-webkit-box-orient:vertical;-webkit-line-clamp:2}.evidence-row small{color:var(--muted);font-size:7px}.evidence-row>svg{color:var(--muted)}.mini-empty{display:flex;align-items:center;gap:10px;padding:20px 4px;color:var(--muted)}.mini-empty p{margin:0;font-size:10px;line-height:1.5}.profile-list{display:grid;margin:0}.profile-list div{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid #efecf0}.profile-list div:last-child{border:0}.profile-list dt{color:var(--muted);font-size:9px}.profile-list dd{margin:0;font-size:9px;font-weight:600;text-align:right}.research-checks{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:15px}.research-checks span{display:flex;align-items:center;gap:6px;padding:8px;border-radius:8px;background:var(--green-soft);color:var(--green);font-size:9px;font-weight:700}.candidate-modal{width:min(860px,calc(100vw - 32px))}.candidate-detail{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(220px,.8fr);gap:24px}.candidate-detail h3{margin:0 0 7px;font-family:var(--font-display);font-size:11px}.candidate-detail__main>p,.candidate-detail li{color:var(--muted-strong);font-size:9px;line-height:1.6}.candidate-detail__main h3:not(:first-child){margin-top:18px}.candidate-detail ul{display:grid;gap:6px;margin:0;padding-left:17px}.candidate-detail aside{padding:14px;border-radius:11px;background:var(--surface-soft)}.candidate-detail aside dl{display:grid;margin:0 0 16px}.candidate-detail aside dl div{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-bottom:1px solid var(--border)}.candidate-detail dt{color:var(--muted);font-size:8px}.candidate-detail dd{margin:0;font-size:8px;font-weight:700;text-align:right;text-transform:capitalize}.candidate-detail aside>a{display:flex;align-items:center;gap:5px;padding:6px 0;color:var(--primary-700);font-size:8px}.muted-copy{color:var(--muted)!important}@keyframes pulse{50%{opacity:.35}}@media(max-width:900px){.research-summary{grid-template-columns:repeat(2,1fr)}.candidate-detail{grid-template-columns:1fr}}@media(max-width:540px){.research-summary,.research-checks{grid-template-columns:1fr}.candidate-card{align-items:flex-start}.candidate-card__footer{align-items:flex-start;flex-direction:column;gap:8px}.candidate-actions{flex-wrap:wrap}}
.summary-settings-link{display:flex;align-items:center;gap:4px;margin-top:4px;color:var(--primary-700);font-size:8px;font-weight:700}.research-filters{display:grid;grid-template-columns:minmax(180px,1.5fr) repeat(4,minmax(95px,.8fr)) auto;gap:6px;margin-bottom:12px}.research-filters label{display:flex;align-items:center;gap:6px;padding:7px 8px;border:1px solid var(--border);border-radius:8px;background:white;color:var(--muted)}.research-filters input{min-width:0;border:0;outline:0;font-size:8px}.research-filters select{min-width:0;padding:7px 8px;border:1px solid var(--border);border-radius:8px;background:white;color:var(--muted-strong);font-size:8px;text-transform:capitalize}.research-filters>span{align-self:center;color:var(--muted);font-size:8px;white-space:nowrap}@media(max-width:1100px){.research-filters{grid-template-columns:repeat(2,minmax(0,1fr))}.research-filters label{grid-column:1/-1}}@media(max-width:540px){.research-filters{grid-template-columns:1fr}}
</style>
