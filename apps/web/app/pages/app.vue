<script setup lang="ts">
import { Activity, ArrowRight, CircleDollarSign, Clapperboard, FlaskConical, Pause, Play, Plus, RadioTower, Sparkles, WandSparkles } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { user } = useAuth()
const { enabled: testMode } = useTestMode()
const { show } = useToast()
const router = useRouter()
const generating = ref(false)
const pausing = ref(false)

const { data, refresh, status } = await useAsyncData('overview-data', async () => {
  const [project, analytics, jobs, ideas, connections] = await Promise.all([
    api<any>(`/v1/projects/${projectId.value}`),
    api<any>(`/v1/projects/${projectId.value}/analytics/summary`),
    api<any>(`/v1/projects/${projectId.value}/generation-jobs`),
    api<any>(`/v1/projects/${projectId.value}/ideas`),
    api<any>(`/v1/projects/${projectId.value}/connections`),
  ])
  return { project, analytics, jobs: jobs.items, ideas: ideas.items, connections: connections.items }
}, {
  default: () => ({
    project: { name: 'Project', status: 'active', autopilot_paused: false, settings: { budget: { monthly_usd: 0 } } },
    analytics: { kpis: { published: 0, videos_ready: 0, awaiting_approval: 0, active_jobs: 0, idea_backlog: 0, budget_used_usd: 0, budget_limit_usd: 0, budget_remaining_usd: 0, budget_percent_used: 0 }, patterns: [] },
    jobs: [], ideas: [], connections: [],
  }),
})

const kpis = computed(() => data.value.analytics?.kpis || {})
const recentJobs = computed(() => data.value.jobs?.slice(0, 5) || [])
const topIdeas = computed(() => [...(data.value.ideas || [])].sort((a, b) => (b.topic_opportunity_score || 0) - (a.topic_opportunity_score || 0)).slice(0, 4))
const topPattern = computed(() => data.value.analytics?.patterns?.[0] || null)
const budgetPercent = computed(() => {
  if (kpis.value.budget_percent_used != null) return Number(kpis.value.budget_percent_used)
  const limit = Number(kpis.value.budget_limit_usd || 1)
  return Math.min(1, Number(kpis.value.budget_used_usd || 0) / limit)
})
const budgetRemaining = computed(() => Math.max(0, Number(kpis.value.budget_remaining_usd || 0)))
const budgetConfigured = computed(() => Number(kpis.value.budget_limit_usd || 0) > 0)
const firstName = computed(() => (user.value?.display_name || 'Creator').trim().split(/\s+/)[0])

function formatDate(value?: string) {
  if (!value) return 'Just now'
  return new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value))
}

async function quickGenerate() {
  generating.value = true
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/generation-jobs`, {
      method: 'POST',
      headers: { 'Idempotency-Key': `overview-quick-${Date.now()}` },
      body: {
        title: `Introduce ${data.value.project?.name || 'our project'} with a clear, evidence-backed story`,
        aspect_ratios: ['9:16', '16:9'],
        target_duration_seconds: 30,
        approval_mode: 'final_only',
        generation_start_mode: 'review_script',
        test_mode: Boolean(user.value?.is_platform_admin && testMode.value),
      },
    })
    show('Production started', 'Research, script, scenes, render and QA are now running.', 'success')
    await router.push(`/productions/${result.generation_job_id}`)
  }
  catch (error: any) {
    show('Could not start production', error.message, 'error')
  }
  finally { generating.value = false }
}

async function toggleAutopilot() {
  pausing.value = true
  const paused = data.value.project?.autopilot_paused
  try {
    await api(`/v1/projects/${projectId.value}/${paused ? 'resume' : 'pause'}`, { method: 'POST' })
    show(paused ? 'Autopilot resumed' : 'Autopilot paused', paused ? 'Scheduled research can continue.' : 'No new automatic work will start.', 'success')
    await refresh()
  }
  catch (error: any) { show('Project update failed', error.message, 'error') }
  finally { pausing.value = false }
}
</script>

<template>
  <div>
    <UiPageHeader :eyebrow="`${data.project?.name || 'Project'} workspace`" :title="`Good morning, ${firstName}`" description="Your private evidence-first production desk is ready for research, generation, review and publishing.">
      <button class="button" :disabled="pausing" @click="toggleAutopilot">
        <Play v-if="data.project?.autopilot_paused" :size="15" /><Pause v-else :size="15" />
        {{ data.project?.autopilot_paused ? 'Resume autopilot' : 'Pause autopilot' }}
      </button>
      <button class="button button--primary" data-testid="quick-generate" :disabled="generating" @click="quickGenerate">
        <WandSparkles :size="16" /> {{ generating ? 'Starting…' : 'Generate video' }}
      </button>
    </UiPageHeader>

    <div class="metric-grid">
      <UiAppCard class="metric-card"><span class="metric-card__icon"><Clapperboard :size="18" /></span><span class="metric-card__label">Videos ready</span><div class="metric-card__value"><strong>{{ kpis.videos_ready || 0 }}</strong><span>{{ kpis.awaiting_approval || 0 }} to review</span></div></UiAppCard>
      <UiAppCard class="metric-card"><span class="metric-card__icon"><Sparkles :size="18" /></span><span class="metric-card__label">Idea backlog</span><div class="metric-card__value"><strong>{{ kpis.idea_backlog || 0 }}</strong><span>Target 7</span></div></UiAppCard>
      <UiAppCard class="metric-card"><span class="metric-card__icon"><Activity :size="18" /></span><span class="metric-card__label">Active productions</span><div class="metric-card__value"><strong>{{ kpis.active_jobs || 0 }}</strong><span>Durable jobs</span></div></UiAppCard>
      <NuxtLink class="metric-card-link" to="/settings?tab=budget" aria-label="Open monthly budget settings"><UiAppCard class="metric-card"><span class="metric-card__icon"><CircleDollarSign :size="18" /></span><span class="metric-card__label">Monthly budget remaining</span><div class="metric-card__value"><strong>{{ budgetConfigured ? `$${budgetRemaining.toFixed(2)}` : 'No cap' }}</strong><span>${{ Number(kpis.budget_used_usd || 0).toFixed(2) }} spent{{ budgetConfigured ? ` of $${Number(kpis.budget_limit_usd || 0).toFixed(2)}` : ' this month' }}</span></div><UiProgressBar v-if="budgetConfigured" :value="budgetPercent" style="margin-top: 9px" /></UiAppCard></NuxtLink>
    </div>

    <div class="overview-layout">
      <div class="stack">
        <UiAppCard>
          <div class="section-heading"><div><h2>Production queue</h2><p>Every external operation preserves its stage and retry history.</p></div><NuxtLink to="/productions" class="text-link">View all <ArrowRight :size="13" /></NuxtLink></div>
          <div v-if="status === 'pending'" class="loading-line" style="height: 80px" />
          <div v-else-if="!recentJobs.length" class="compact-empty"><Clapperboard :size="24" /><div><strong>No productions yet</strong><span>Start from an idea or generate a new project video.</span></div><button class="button button--small" @click="quickGenerate"><Plus :size="14" /> Generate</button></div>
          <div v-else class="table-wrap">
            <table class="data-table">
              <thead><tr><th>Production</th><th>Stage</th><th>Progress</th><th>Created</th><th /></tr></thead>
              <tbody>
                <tr v-for="job in recentJobs" :key="job.id">
                  <td><div class="table-title"><strong>{{ job.title || 'Video production' }}</strong><span>{{ job.aspect_ratios?.join(' · ') }} · {{ job.target_duration_seconds }} sec</span></div></td>
                  <td><UiStatusBadge :status="job.status" /></td>
                  <td><div class="table-progress"><UiProgressBar :value="job.progress || 0" /><span>{{ Math.round((job.progress || 0) * 100) }}%</span></div></td>
                  <td>{{ formatDate(job.created_at) }}</td>
                  <td><NuxtLink class="icon-button" :to="`/productions/${job.id}`" aria-label="Open production"><ArrowRight :size="15" /></NuxtLink></td>
                </tr>
              </tbody>
            </table>
          </div>
        </UiAppCard>

        <UiAppCard>
          <div class="section-heading"><div><h2>Research radar</h2><p>Evidence-backed opportunities ranked before expensive production.</p></div><NuxtLink to="/research" class="text-link">Open radar <ArrowRight :size="13" /></NuxtLink></div>
          <div class="idea-strip">
            <article v-for="idea in topIdeas" :key="idea.id" class="idea-mini-card">
              <div class="idea-mini-card__top"><span class="idea-mini-card__score">{{ idea.topic_opportunity_score || '—' }}</span><UiStatusBadge :status="idea.status" /></div>
              <strong>{{ idea.title }}</strong><p>{{ idea.hook }}</p>
            </article>
          </div>
        </UiAppCard>
      </div>

      <div class="stack">
        <UiAppCard class="next-action-card">
          <div class="next-action-card__icon"><RadioTower :size="20" /></div>
          <span class="eyebrow">Research on demand</span><h2>{{ data.project?.name || 'Project' }} signals</h2><p>Parallel searches audience demand, fresh developments, primary evidence and competing saturation for this project.</p>
          <NuxtLink to="/research" class="button button--primary">Run now <ArrowRight :size="15" /></NuxtLink>
        </UiAppCard>

        <UiAppCard>
          <div class="section-heading"><div><h2>Learning signal</h2><p>Early, project-specific evidence</p></div><FlaskConical :size="18" class="muted-icon" /></div>
          <div v-if="topPattern" class="learning-signal"><strong>{{ topPattern.name }}</strong><span class="learning-signal__delta">{{ Number(topPattern.delta_percentile) >= 0 ? '+' : '' }}{{ topPattern.delta_percentile }} percentile</span><p>Observed within this project's comparable account and format cohort.</p><div class="confidence-row"><span>Confidence {{ Math.round(Number(topPattern.confidence || 0) * 100) }}%</span><UiProgressBar :value="Number(topPattern.confidence || 0)" /></div><small>n = {{ topPattern.sample_size }}</small></div>
          <div v-else class="mini-empty">No statistically useful project-specific pattern yet.</div>
        </UiAppCard>

        <UiAppCard>
          <div class="section-heading"><div><h2>Connections</h2><p>Capabilities are checked before publishing</p></div><NuxtLink to="/connections" class="text-link">Manage</NuxtLink></div>
          <div class="connection-list">
            <div v-for="connection in data.connections?.slice(0, 4)" :key="connection.id" class="connection-row"><span class="connection-logo">{{ connection.provider?.slice(0, 2).toUpperCase() }}</span><div><strong>{{ connection.display_name }}</strong><span>{{ connection.provider }}</span></div><UiStatusBadge :status="connection.status" /></div>
          </div>
        </UiAppCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.metric-card-link{display:block;color:inherit;text-decoration:none;border-radius:14px}.metric-card-link .metric-card{height:100%;transition:transform .15s ease,box-shadow .15s ease}.metric-card-link:hover .metric-card,.metric-card-link:focus-visible .metric-card{transform:translateY(-2px);box-shadow:0 14px 32px rgb(47 25 52 / 12%)}.overview-layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(285px,.75fr);gap:16px;margin-top:16px}.table-progress{display:grid;grid-template-columns:minmax(80px,130px) auto;align-items:center;gap:8px}.table-progress span{color:var(--muted);font-size:9px}.compact-empty{display:flex;align-items:center;gap:13px;padding:22px 8px;color:var(--primary-500)}.compact-empty div{display:grid;flex:1;gap:3px}.compact-empty strong{color:var(--ink);font-size:12px}.compact-empty span{color:var(--muted);font-size:10px}.idea-strip{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.idea-mini-card{padding:13px;border:1px solid var(--border);border-radius:11px;background:var(--surface-soft)}.idea-mini-card__top{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px}.idea-mini-card__score{display:grid;width:29px;height:29px;place-items:center;border-radius:9px;background:var(--primary-100);color:var(--primary-700);font-family:var(--font-display);font-size:12px;font-weight:800}.idea-mini-card>strong{display:block;font-size:11px;line-height:1.45}.idea-mini-card p{margin:5px 0 0;color:var(--muted);font-size:9px;line-height:1.5}.next-action-card{overflow:hidden;background:linear-gradient(155deg,#24182d,#17131f);color:white;box-shadow:0 16px 40px rgb(30 20 36 / 13%)}.next-action-card__icon{display:grid;width:42px;height:42px;place-items:center;margin-bottom:23px;border:1px solid rgb(255 255 255 / 13%);border-radius:12px;background:rgb(255 255 255 / 7%);color:var(--primary-300)}.next-action-card .eyebrow{color:var(--primary-300)}.next-action-card h2{margin:7px 0 8px;font-family:var(--font-display);font-size:19px;letter-spacing:-.03em}.next-action-card p{margin:0;color:#bcb4c3;font-size:10px;line-height:1.65}.next-action-card__meta{display:flex;align-items:center;gap:7px;margin:20px 0 13px;color:#d5ced9;font-size:10px}.next-action-card .button{width:100%}.muted-icon{color:var(--muted)}.learning-signal{display:grid;gap:7px}.learning-signal>strong{font-family:var(--font-display);font-size:17px}.learning-signal__delta{width:fit-content;padding:3px 7px;border-radius:99px;background:var(--green-soft);color:var(--green);font-size:9px;font-weight:800}.learning-signal p{margin:1px 0;color:var(--muted);font-size:10px;line-height:1.55}.confidence-row{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:9px;color:var(--muted-strong);font-size:9px}.learning-signal small{color:var(--muted);font-size:8px}.connection-list{display:grid;gap:4px}.connection-row{display:flex;align-items:center;gap:9px;padding:8px 0;border-bottom:1px solid #efecf0}.connection-row:last-child{border:0}.connection-logo{display:grid;width:29px;height:29px;place-items:center;border-radius:9px;background:var(--primary-50);color:var(--primary-700);font-size:9px;font-weight:800}.connection-row div{display:grid;min-width:0;flex:1;gap:1px}.connection-row strong{overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.connection-row div span{color:var(--muted);font-size:8px;text-transform:capitalize}@media(max-width:1100px){.overview-layout{grid-template-columns:1fr}}@media(max-width:680px){.idea-strip{grid-template-columns:1fr}.compact-empty{align-items:flex-start;flex-wrap:wrap}.compact-empty .button{width:100%}}
</style>
