<script setup lang="ts">
import { ArrowUpRight, Check, ChevronRight, CircleHelp, Clock3, EyeOff, ExternalLink, RadioTower, Search, ShieldCheck, Sparkles, X } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { show } = useToast()
const objective = ref('Find fresh, evidence-backed short-form topics for independent teachers creating online courses.')
const modalOpen = ref(false)
const running = ref(false)
const selectedRun = ref<any>(null)

const { data, refresh } = await useAsyncData('research-radar', async () => {
  const [runs, candidates] = await Promise.all([
    api<any>(`/v1/projects/${projectId.value}/research-runs`),
    api<any>(`/v1/projects/${projectId.value}/topic-candidates`),
  ])
  return { runs: runs.items, candidates: candidates.items }
}, { default: () => ({ runs: [], candidates: [] }) })

const candidates = computed(() => data.value.candidates || [])
const latestRun = computed(() => selectedRun.value || data.value.runs?.[0])

async function runResearch() {
  running.value = true
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/research-runs`, { method: 'POST', body: { objective: objective.value, max_candidates: 5 } })
    modalOpen.value = false
    show('Parallel research started', 'Audience demand, freshness, evidence and saturation are being checked.', 'success')
    for (let index = 0; index < 30; index++) {
      const run = await api<any>(`/v1/research-runs/${result.research_run_id}`)
      if (['completed', 'failed'].includes(run.status)) { selectedRun.value = run; break }
      await new Promise(resolve => setTimeout(resolve, 250))
    }
    await refresh()
  }
  catch (error: any) { show('Research failed', error.message, 'error') }
  finally { running.value = false }
}

async function selectCandidate(id: string) {
  await api(`/v1/topic-candidates/${id}/select`, { method: 'POST' })
  show('Topic selected', 'The evidence packet will stay attached to the production.', 'success')
  await refresh()
}
async function muteCandidate(id: string) {
  await api(`/v1/topic-candidates/${id}/mute`, { method: 'POST', body: { reason: 'Not relevant to the current editorial plan', permanent: true } })
  show('Topic muted', 'It will stay out of scheduled research until a new meaningful signal appears.', 'success')
  await refresh()
}
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Parallel search" title="Research radar" description="Discover fresh angles before production. Every candidate carries source provenance, freshness, confidence and unresolved questions.">
      <button class="button button--primary" data-testid="run-research" @click="modalOpen = true"><RadioTower :size="16" /> Run research</button>
    </UiPageHeader>

    <div class="research-summary">
      <UiAppCard><span>Latest provider</span><strong>Parallel Search</strong><small>{{ latestRun?.parallel_request_ids?.[0] || 'Ready for first live call' }}</small></UiAppCard>
      <UiAppCard><span>Evidence sources</span><strong>{{ latestRun?.sources?.length || 0 }}</strong><small>Primary sources preferred</small></UiAppCard>
      <UiAppCard><span>Candidates</span><strong>{{ candidates.length }}</strong><small>Ranked before generation</small></UiAppCard>
      <UiAppCard><span>Research cadence</span><strong>3× weekly</strong><small>+ source-triggered</small></UiAppCard>
    </div>

    <div class="grid-two research-layout">
      <UiAppCard>
        <div class="section-heading"><div><h2>Topic candidates</h2><p>Opportunity is separate from publish readiness.</p></div><span class="filter-pill"><Sparkles :size="13" /> High relevance</span></div>
        <div v-if="!candidates.length" class="empty-state"><div><span class="empty-state__icon"><Search :size="23" /></span><h3>No research candidates yet</h3><p>Run a natural-language objective. Parallel will return sources and excerpts; the editor will turn them into ranked angles.</p><button class="button button--primary" @click="modalOpen = true">Run first research</button></div></div>
        <div v-else class="candidate-list">
          <article v-for="candidate in candidates" :key="candidate.id" class="candidate-card">
            <div class="candidate-card__score"><strong>{{ candidate.topic_opportunity_score }}</strong><span>topic</span></div>
            <div class="candidate-card__body"><div class="candidate-card__meta"><UiStatusBadge :status="candidate.status" /><span><Clock3 :size="12" /> fresh 7 days</span><span><ShieldCheck :size="12" /> {{ Math.round((candidate.score_confidence || 0) * 100) }}% confidence</span></div><h3>{{ candidate.title }}</h3><p>{{ candidate.angle }}</p><div class="candidate-card__footer"><span>{{ candidate.source_ids?.length || 0 }} cited sources</span><div class="candidate-actions"><button class="text-link" @click="muteCandidate(candidate.id)"><EyeOff :size="13" /> Mute</button><button class="text-link" @click="selectCandidate(candidate.id)">Turn into idea <ChevronRight :size="13" /></button></div></div></div>
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
          <div class="section-heading"><div><h2>Saved profile</h2><p>Teacher creator intelligence</p></div><button class="icon-button"><ArrowUpRight :size="14" /></button></div>
          <dl class="profile-list"><div><dt>Regions</dt><dd>United States · Global</dd></div><div><dt>Recency</dt><dd>30 days</dd></div><div><dt>Min. sources</dt><dd>2 independent</dd></div><div><dt>Coverage</dt><dd>Demand · news · evergreen · competition</dd></div></dl>
        </UiAppCard>
      </div>
    </div>

    <div v-if="modalOpen" class="modal-backdrop" @click.self="modalOpen = false">
      <form class="modal" @submit.prevent="runResearch">
        <div class="modal__header"><div><h2>Run Parallel research</h2><p>Describe the editorial objective—not a bag of keywords.</p></div><button type="button" class="icon-button icon-button--plain" @click="modalOpen = false"><X :size="18" /></button></div>
        <div class="modal__body"><div class="field"><label for="research-objective">Research objective</label><textarea id="research-objective" v-model="objective" required minlength="8" /><small>The run saves provider request IDs, retrieval time, freshness, excerpts and claim-source mappings.</small></div><div class="research-checks"><span><Check :size="14" /> Audience demand</span><span><Check :size="14" /> Fresh developments</span><span><Check :size="14" /> Primary evidence</span><span><Check :size="14" /> Competitive saturation</span></div></div>
        <div class="modal__footer"><button type="button" class="button" @click="modalOpen = false">Cancel</button><button class="button button--primary" :disabled="running"><RadioTower :size="15" /> {{ running ? 'Researching…' : 'Start research' }}</button></div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.research-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.research-summary .app-card{display:grid;gap:3px;padding:14px 16px}.research-summary span{color:var(--muted);font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.07em}.research-summary strong{font-family:var(--font-display);font-size:16px}.research-summary small{overflow:hidden;color:var(--muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.research-layout{margin-top:15px;align-items:start}.filter-pill{display:inline-flex;align-items:center;gap:5px;padding:5px 8px;border-radius:99px;background:var(--primary-50);color:var(--primary-700);font-size:9px;font-weight:700}.candidate-list{display:grid;gap:9px}.candidate-card{display:flex;gap:14px;padding:14px;border:1px solid var(--border);border-radius:12px;background:var(--surface-soft);transition:.16s}.candidate-card:hover{border-color:var(--primary-300);background:white}.candidate-card__score{display:grid;width:51px;height:51px;flex:none;place-items:center;align-content:center;border-radius:13px;background:linear-gradient(145deg,var(--primary-100),#fff);color:var(--primary-700)}.candidate-card__score strong{font-family:var(--font-display);font-size:18px}.candidate-card__score span{font-size:7px;font-weight:800;text-transform:uppercase}.candidate-card__body{min-width:0;flex:1}.candidate-card__meta{display:flex;flex-wrap:wrap;align-items:center;gap:9px}.candidate-card__meta>span{display:inline-flex;align-items:center;gap:4px;color:var(--muted);font-size:8px}.candidate-card h3{margin:10px 0 4px;font-family:var(--font-display);font-size:13px}.candidate-card p{margin:0;color:var(--muted);font-size:10px;line-height:1.5}.candidate-card__footer{display:flex;align-items:center;justify-content:space-between;margin-top:11px;color:var(--muted);font-size:9px}.candidate-card__footer button{display:flex;align-items:center;border:0;background:transparent}.candidate-actions{display:flex;align-items:center;gap:9px}.evidence-list{display:grid;gap:2px}.evidence-row{display:grid;grid-template-columns:auto 1fr auto;gap:9px;padding:10px 3px;border-bottom:1px solid #efecf0}.evidence-row:last-child{border:0}.evidence-row__index{display:grid;width:23px;height:23px;place-items:center;border-radius:7px;background:var(--blue-soft);color:var(--blue);font-size:8px;font-weight:800}.evidence-row div{min-width:0}.evidence-row strong{display:block;overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.evidence-row p{display:-webkit-box;overflow:hidden;margin:3px 0;color:var(--muted);font-size:8px;line-height:1.45;-webkit-box-orient:vertical;-webkit-line-clamp:2}.evidence-row small{color:var(--muted);font-size:7px}.evidence-row>svg{color:var(--muted)}.mini-empty{display:flex;align-items:center;gap:10px;padding:20px 4px;color:var(--muted)}.mini-empty p{margin:0;font-size:10px;line-height:1.5}.profile-list{display:grid;margin:0}.profile-list div{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid #efecf0}.profile-list div:last-child{border:0}.profile-list dt{color:var(--muted);font-size:9px}.profile-list dd{margin:0;font-size:9px;font-weight:600;text-align:right}.research-checks{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:15px}.research-checks span{display:flex;align-items:center;gap:6px;padding:8px;border-radius:8px;background:var(--green-soft);color:var(--green);font-size:9px;font-weight:700}@media(max-width:900px){.research-summary{grid-template-columns:repeat(2,1fr)}}@media(max-width:540px){.research-summary,.research-checks{grid-template-columns:1fr}.candidate-card{align-items:flex-start}.candidate-card__footer{align-items:flex-start;flex-direction:column;gap:8px}}
</style>
