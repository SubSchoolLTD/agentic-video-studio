<script setup lang="ts">
import { ArrowRight, Columns3, List, MoreHorizontal, Plus, Search, Sparkles, WandSparkles, X } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { show } = useToast()
const route = useRoute()
const router = useRouter()
const view = ref<'board' | 'table'>('board')
const modalOpen = ref(route.query.create === '1')
const saving = ref(false)
const form = reactive({ title: '', hook: '', audience: 'Independent teachers', objective: 'education' })

watch(() => route.query.create, value => { if (value === '1') modalOpen.value = true })

const { data, refresh } = await useAsyncData('ideas-list', () => api<any>(`/v1/projects/${projectId.value}/ideas`), { default: () => ({ items: [] }) })
const ideas = computed(() => data.value.items || [])
const columns = computed(() => [
  { key: 'draft', label: 'Draft', items: ideas.value.filter((item: any) => ['draft', 'candidate'].includes(item.status)) },
  { key: 'researching', label: 'Researching', items: ideas.value.filter((item: any) => item.status === 'researching') },
  { key: 'ready', label: 'Ready', items: ideas.value.filter((item: any) => ['ready', 'selected'].includes(item.status)) },
  { key: 'planned', label: 'Planned', items: ideas.value.filter((item: any) => item.status === 'planned') },
])

async function saveIdea() {
  saving.value = true
  try {
    await api(`/v1/projects/${projectId.value}/ideas`, { method: 'POST', body: form })
    show('Idea added', 'You can research, score or send it into production.', 'success')
    modalOpen.value = false
    Object.assign(form, { title: '', hook: '', audience: 'Independent teachers', objective: 'education' })
    await router.replace({ query: {} })
    await refresh()
  }
  catch (error: any) { show('Could not add idea', error.message, 'error') }
  finally { saving.value = false }
}

async function generate(idea: any) {
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/generation-jobs`, {
      method: 'POST', headers: { 'Idempotency-Key': `idea-${idea.id}-${Date.now()}` },
      body: { idea_id: idea.id, aspect_ratios: ['9:16'], target_duration_seconds: 30, approval_mode: 'final_only' },
    })
    show('Production started', idea.title, 'success')
    await router.push(`/productions/${result.generation_job_id}`)
  }
  catch (error: any) { show('Could not start production', error.message, 'error') }
}
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Editorial backlog" title="Ideas" description="A single primary audience, a traceable angle, and an opportunity score before generation spend.">
      <div class="segmented"><button :class="{ active: view === 'board' }" @click="view = 'board'"><Columns3 :size="14" /></button><button :class="{ active: view === 'table' }" @click="view = 'table'"><List :size="14" /></button></div>
      <button class="button button--primary" data-testid="new-idea" @click="modalOpen = true"><Plus :size="15" /> New idea</button>
    </UiPageHeader>

    <div class="ideas-toolbar"><div class="ideas-search"><Search :size="15" /><span>Search ideas…</span></div><span class="toolbar-chip">All audiences</span><span class="toolbar-chip">All objectives</span><span class="toolbar-count">{{ ideas.length }} ideas</span></div>

    <div v-if="view === 'board'" class="idea-board">
      <section v-for="column in columns" :key="column.key" class="idea-column">
        <header><span>{{ column.label }}</span><small>{{ column.items.length }}</small></header>
        <article v-for="idea in column.items" :key="idea.id" class="idea-card">
          <div class="idea-card__top"><UiStatusBadge :status="idea.status" /><button class="icon-button icon-button--plain"><MoreHorizontal :size="15" /></button></div>
          <h3>{{ idea.title }}</h3><p>{{ idea.hook || 'Add a sharper first-two-second hook.' }}</p>
          <div class="idea-card__tags"><span>{{ idea.audience || 'Independent teachers' }}</span><span>{{ idea.objective || 'education' }}</span></div>
          <div class="idea-card__score"><div><strong>{{ idea.topic_opportunity_score || '—' }}</strong><span>Opportunity</span></div><div><strong>{{ idea.confidence ? `${Math.round(idea.confidence * 100)}%` : 'Pending' }}</strong><span>Confidence</span></div></div>
          <button class="idea-card__action" @click="generate(idea)"><WandSparkles :size="14" /> Generate video <ArrowRight :size="13" /></button>
        </article>
        <button class="column-add" @click="modalOpen = true"><Plus :size="14" /> Add idea</button>
      </section>
    </div>

    <UiAppCard v-else :padded="false" class="table-wrap">
      <table class="data-table"><thead><tr><th>Idea</th><th>Audience</th><th>Opportunity</th><th>Status</th><th /></tr></thead><tbody><tr v-for="idea in ideas" :key="idea.id"><td><div class="table-title"><strong>{{ idea.title }}</strong><span>{{ idea.hook }}</span></div></td><td>{{ idea.audience }}</td><td>{{ idea.topic_opportunity_score || '—' }}</td><td><UiStatusBadge :status="idea.status" /></td><td><button class="button button--small" @click="generate(idea)">Generate</button></td></tr></tbody></table>
    </UiAppCard>

    <div v-if="modalOpen" class="modal-backdrop" @click.self="modalOpen = false">
      <form class="modal" @submit.prevent="saveIdea">
        <div class="modal__header"><div><h2>New content idea</h2><p>Keep one audience and one core thought per short video.</p></div><button type="button" class="icon-button icon-button--plain" @click="modalOpen = false"><X :size="18" /></button></div>
        <div class="modal__body"><div class="form-grid"><div class="field field--full"><label for="idea-title">Idea or topic</label><input id="idea-title" v-model="form.title" data-testid="idea-title" required minlength="3" placeholder="Turn one lesson into a reusable course" /></div><div class="field field--full"><label for="idea-hook">Opening hook</label><textarea id="idea-hook" v-model="form.hook" placeholder="One lesson can do more than you think." /></div><div class="field"><label for="idea-audience">Primary audience</label><select id="idea-audience" v-model="form.audience"><option>Independent teachers</option><option>Students</option><option>Parents</option><option>Course creators</option></select></div><div class="field"><label for="idea-objective">Objective</label><select id="idea-objective" v-model="form.objective"><option value="education">Education</option><option value="awareness">Awareness</option><option value="traffic">Traffic</option><option value="lead">Lead</option></select></div></div><div class="idea-note"><Sparkles :size="16" /><span>Research can strengthen this angle with live audience demand, fresh evidence and competitive saturation.</span></div></div>
        <div class="modal__footer"><button type="button" class="button" @click="modalOpen = false">Cancel</button><button class="button button--primary" data-testid="save-idea" :disabled="saving">{{ saving ? 'Saving…' : 'Create idea' }}</button></div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.segmented{display:flex;padding:3px;border:1px solid var(--border);border-radius:9px;background:white}.segmented button{display:grid;width:29px;height:27px;place-items:center;border-radius:6px;background:transparent;color:var(--muted)}.segmented button.active{background:var(--primary-100);color:var(--primary-700)}.ideas-toolbar{display:flex;align-items:center;gap:8px;margin-bottom:15px}.ideas-search{display:flex;min-width:210px;align-items:center;gap:7px;padding:8px 10px;border:1px solid var(--border);border-radius:9px;background:white;color:var(--muted);font-size:10px}.toolbar-chip{padding:7px 9px;border:1px solid var(--border);border-radius:9px;background:white;color:var(--muted-strong);font-size:9px}.toolbar-count{margin-left:auto;color:var(--muted);font-size:9px}.idea-board{display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:12px;overflow-x:auto;padding-bottom:12px}.idea-column{min-width:220px}.idea-column>header{display:flex;align-items:center;gap:7px;padding:0 3px 10px;color:var(--muted-strong);font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.07em}.idea-column>header small{display:grid;min-width:19px;height:19px;place-items:center;border-radius:6px;background:#eae6ec;color:var(--muted);font-size:8px}.idea-card{margin-bottom:9px;padding:14px;border:1px solid var(--border);border-radius:12px;background:white;box-shadow:var(--shadow-sm)}.idea-card__top{display:flex;align-items:center;justify-content:space-between}.idea-card h3{margin:11px 0 5px;font-family:var(--font-display);font-size:12px;line-height:1.4}.idea-card>p{min-height:31px;margin:0;color:var(--muted);font-size:9px;line-height:1.55}.idea-card__tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}.idea-card__tags span{padding:4px 6px;border-radius:6px;background:var(--surface-soft);color:var(--muted-strong);font-size:7px}.idea-card__score{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:11px;padding-top:10px;border-top:1px solid #efecf0}.idea-card__score div{display:grid;gap:1px}.idea-card__score strong{font-family:var(--font-display);font-size:13px}.idea-card__score span{color:var(--muted);font-size:7px;text-transform:uppercase}.idea-card__action{display:flex;width:100%;align-items:center;gap:6px;margin-top:11px;padding:7px 8px;border-radius:8px;background:var(--primary-50);color:var(--primary-700);font-size:9px;font-weight:800}.idea-card__action svg:last-child{margin-left:auto}.column-add{display:flex;width:100%;align-items:center;justify-content:center;gap:6px;padding:9px;border:1px dashed var(--border-strong);border-radius:10px;background:transparent;color:var(--muted);font-size:9px}.idea-note{display:flex;align-items:flex-start;gap:8px;margin-top:15px;padding:10px;border-radius:9px;background:var(--primary-50);color:var(--primary-700);font-size:9px;line-height:1.5}@media(max-width:700px){.ideas-toolbar{overflow-x:auto}.toolbar-count{display:none}.idea-board{grid-template-columns:repeat(4,250px)}}
</style>
