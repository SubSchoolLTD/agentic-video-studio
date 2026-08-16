<script setup lang="ts">
import { ArrowRight, Check, Columns3, GripVertical, List, Plus, Search, Sparkles, Video, WandSparkles, X } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { show } = useToast()
const route = useRoute()
const router = useRouter()
const view = ref<'board' | 'table'>('board')
const ideaModalOpen = ref(route.query.create === '1')
const generationModalOpen = ref(false)
const saving = ref(false)
const starting = ref(false)
const search = ref('')
const audienceFilter = ref('')
const objectiveFilter = ref('')
const selectedIdea = ref<any>(null)
const draggingId = ref('')
const dragTarget = ref('')
const form = reactive({ title: '', hook: '', audience: '', objective: 'awareness', visual_mode: 'ugc_creator', character_id: '' })
const generation = reactive({ visual_mode: 'ugc_creator', character_id: '', aspect_ratios: ['9:16'] as string[], target_duration_seconds: 30, approval_mode: 'final_only', variants: 1, max_cost_usd: 20 })
const sceneRange = ref('4-6')
const allowSceneFlex = ref(true)

watch(() => route.query.create, value => { if (value === '1') ideaModalOpen.value = true })

const { data, refresh } = await useAsyncData('ideas-list', () => api<any>(`/v1/projects/${projectId.value}/ideas`), { default: () => ({ items: [] }) })
const { data: characterData } = await useAsyncData('idea-characters', () => api<any>(`/v1/projects/${projectId.value}/characters`), { default: () => ({ items: [] }) })
const ideas = computed(() => data.value.items || [])
const characters = computed(() => (characterData.value?.items || []).filter((item: any) => item.status === 'ready'))
const ideaUsesCharacter = computed(() => ['ugc_creator', 'ugc_native_audio'].includes(form.visual_mode))
const generationUsesCharacter = computed(() => ['ugc_creator', 'ugc_native_audio'].includes(generation.visual_mode))
const audiences = computed<string[]>(() => [...new Set<string>(ideas.value.map((item: any) => String(item.audience || '')).filter(Boolean))].sort())
const filteredIdeas = computed(() => ideas.value.filter((item: any) => {
  const query = search.value.trim().toLowerCase()
  const matchesQuery = !query || [item.title, item.hook, item.audience].some(value => String(value || '').toLowerCase().includes(query))
  return matchesQuery && (!audienceFilter.value || item.audience === audienceFilter.value) && (!objectiveFilter.value || item.objective === objectiveFilter.value)
}))
const columns = computed(() => [
  { key: 'draft', label: 'Draft', items: filteredIdeas.value.filter((item: any) => ['draft', 'candidate'].includes(item.status)) },
  { key: 'researching', label: 'Researching', items: filteredIdeas.value.filter((item: any) => item.status === 'researching') },
  { key: 'ready', label: 'Ready', items: filteredIdeas.value.filter((item: any) => ['ready', 'selected'].includes(item.status)) },
  { key: 'planned', label: 'Planned / production', items: filteredIdeas.value.filter((item: any) => item.status === 'planned') },
])
const parsedSceneRange = computed(() => {
  const match = sceneRange.value.trim().match(/^(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?$/)
  if (!match) return null
  const min = Number(match[1])
  const max = Number(match[2] || match[1])
  return min >= 2 && max <= 20 && min <= max ? { min, max } : null
})
const averageSceneDuration = computed(() => {
  if (!parsedSceneRange.value) return null
  return generation.target_duration_seconds / ((parsedSceneRange.value.min + parsedSceneRange.value.max) / 2)
})

let poller: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  poller = setInterval(() => {
    if (ideas.value.some((item: any) => item.production && !['ready', 'failed', 'blocked', 'cancelled'].includes(item.production.status))) void refresh()
  }, 1800)
  if (route.query.idea) nextTick(() => document.querySelector(`[data-idea-id="${route.query.idea}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }))
})
onBeforeUnmount(() => { if (poller) clearInterval(poller) })

async function saveIdea() {
  saving.value = true
  try {
    await api(`/v1/projects/${projectId.value}/ideas`, { method: 'POST', body: form })
    show('Idea added', 'Move it across the board or configure a production when it is ready.', 'success')
    ideaModalOpen.value = false
    Object.assign(form, { title: '', hook: '', audience: '', objective: 'awareness', visual_mode: 'ugc_creator', character_id: '' })
    await router.replace({ query: {} })
    await refresh()
  }
  catch (error: any) { show('Could not add idea', error.message, 'error') }
  finally { saving.value = false }
}

function openGeneration(idea: any) {
  selectedIdea.value = idea
  Object.assign(generation, {
    visual_mode: idea.visual_mode || 'ugc_creator',
    character_id: idea.character_id || '',
    aspect_ratios: ['9:16'],
    target_duration_seconds: 30,
    approval_mode: 'final_only',
    variants: 1,
    max_cost_usd: 20,
  })
  sceneRange.value = '4-6'
  allowSceneFlex.value = true
  generationModalOpen.value = true
}

function toggleRatio(ratio: string) {
  const existing = generation.aspect_ratios.indexOf(ratio)
  if (existing >= 0 && generation.aspect_ratios.length > 1) generation.aspect_ratios.splice(existing, 1)
  else if (existing < 0) generation.aspect_ratios.push(ratio)
}

async function startGeneration() {
  if (!selectedIdea.value || !parsedSceneRange.value) return show('Check the scene range', 'Use one number such as 4 or a range such as 12-18 (2 to 20).', 'error')
  if (generation.visual_mode === 'ugc_native_audio' && !generation.character_id) return show('Choose a character', 'Native-audio UGC needs a reusable identity reference.', 'error')
  starting.value = true
  try {
    const result = await api<any>(`/v1/projects/${projectId.value}/generation-jobs`, {
      method: 'POST', headers: { 'Idempotency-Key': `idea-${selectedIdea.value.id}-${Date.now()}` },
      body: {
        idea_id: selectedIdea.value.id,
        aspect_ratios: generation.aspect_ratios,
        target_duration_seconds: generation.target_duration_seconds,
        approval_mode: generation.approval_mode,
        variants: generation.variants,
        visual_mode: generation.visual_mode,
        character_id: generation.character_id || null,
        scene_count_min: parsedSceneRange.value.min,
        scene_count_max: parsedSceneRange.value.max,
        scene_count_flex: allowSceneFlex.value ? 2 : 0,
        max_cost_usd: generation.max_cost_usd,
      },
    })
    generationModalOpen.value = false
    show('Production started', 'Its stage and progress are now attached to this idea card.', 'success')
    await refresh()
    if (result.status === 'budget_blocked') show('Production needs a higher cost guard', 'Open the production to review the configured limit.', 'error')
  }
  catch (error: any) { show('Could not start production', error.message, 'error') }
  finally { starting.value = false }
}

function startDrag(event: DragEvent, idea: any) {
  draggingId.value = idea.id
  event.dataTransfer?.setData('text/plain', idea.id)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function columnStatus(status: string) {
  if (status === 'candidate') return 'draft'
  if (status === 'selected') return 'ready'
  return status
}

async function moveIdeaTo(idea: any, status: string) {
  draggingId.value = ''
  dragTarget.value = ''
  if (!idea || columnStatus(idea.status) === status) return
  try {
    await api(`/v1/ideas/${idea.id}`, { method: 'PATCH', body: { status } })
    await refresh()
    show('Idea moved', `${idea.title} → ${status}`, 'success')
  }
  catch (error: any) { show('Could not move idea', error.message, 'error') }
}

async function moveIdea(status: string) {
  const idea = ideas.value.find((item: any) => item.id === draggingId.value)
  await moveIdeaTo(idea, status)
}

function chooseIdeaStatus(event: Event, idea: any) {
  void moveIdeaTo(idea, (event.target as HTMLSelectElement).value)
}

function productionLabel(idea: any) {
  if (!idea.production) return ''
  if (idea.production.status === 'ready') return 'Video ready'
  if (idea.production.status === 'failed') return 'Generation failed'
  if (idea.production.status === 'blocked' || idea.production.status === 'budget_blocked') return 'Action required'
  return `${String(idea.production.current_stage || idea.production.status).replaceAll('_', ' ')} · ${Math.round((idea.production.progress || 0) * 100)}%`
}
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Editorial backlog" title="Ideas" description="Move ideas through the workflow, configure production deliberately, and follow generation without losing the originating card.">
      <div class="segmented"><button :class="{ active: view === 'board' }" aria-label="Board view" @click="view = 'board'"><Columns3 :size="14" /></button><button :class="{ active: view === 'table' }" aria-label="Table view" @click="view = 'table'"><List :size="14" /></button></div>
      <button class="button button--primary" data-testid="new-idea" @click="ideaModalOpen = true"><Plus :size="15" /> New idea</button>
    </UiPageHeader>

    <div class="ideas-toolbar"><label class="ideas-search"><Search :size="15" /><input v-model="search" aria-label="Search ideas" placeholder="Search ideas…"></label><select v-model="audienceFilter" class="toolbar-chip" aria-label="Filter by audience"><option value="">All audiences</option><option v-for="audience in audiences" :key="audience" :value="audience">{{ audience }}</option></select><select v-model="objectiveFilter" class="toolbar-chip" aria-label="Filter by objective"><option value="">All objectives</option><option v-for="objective in ['awareness','education','traffic','lead','install','purchase']" :key="objective" :value="objective">{{ objective }}</option></select><span class="toolbar-count">{{ filteredIdeas.length }} ideas</span></div>

    <div v-if="view === 'board'" class="idea-board">
      <section v-for="column in columns" :key="column.key" class="idea-column" :class="{ 'idea-column--target': dragTarget === column.key }" @dragover.prevent="dragTarget = column.key" @dragleave="dragTarget = ''" @drop.prevent="moveIdea(column.key)">
        <header><span>{{ column.label }}</span><small>{{ column.items.length }}</small></header>
        <article v-for="idea in column.items" :key="idea.id" class="idea-card" :class="{ 'idea-card--linked': route.query.idea === idea.id, 'idea-card--dragging': draggingId === idea.id }" :data-idea-id="idea.id" draggable="true" @dragstart="startDrag($event, idea)" @dragend="draggingId = ''; dragTarget = ''">
          <div class="idea-card__top"><UiStatusBadge :status="idea.status" /><div class="idea-card__move"><select :value="columnStatus(idea.status)" :aria-label="`Move idea: ${idea.title}`" @pointerdown.stop @click.stop @change="chooseIdeaStatus($event, idea)"><option value="draft">Draft</option><option value="researching">Researching</option><option value="ready">Ready</option><option value="planned">Planned / production</option></select><span class="drag-handle" title="Drag to move"><GripVertical :size="15" /></span></div></div>
          <h3>{{ idea.title }}</h3><p>{{ idea.hook || 'Add a sharper first-two-second hook.' }}</p>
          <div class="idea-card__tags"><span>{{ idea.audience || 'General audience' }}</span><span>{{ idea.objective || 'awareness' }}</span><span>{{ (idea.visual_mode || 'ugc_creator').replaceAll('_', ' ') }}</span></div>
          <div class="idea-card__score"><div><strong>{{ idea.topic_opportunity_score || '—' }}</strong><span>Opportunity</span></div><div><strong>{{ idea.score_confidence ? `${Math.round(idea.score_confidence * 100)}%` : 'Pending' }}</strong><span>Confidence</span></div></div>
          <div v-if="idea.production" class="idea-production"><div><Video :size="13" /><strong>{{ productionLabel(idea) }}</strong></div><UiProgressBar :value="idea.production.progress || 0" /></div>
          <NuxtLink v-if="idea.production" class="idea-card__action" :to="`/productions/${idea.production.generation_job_id}`"><Video :size="14" /> Open production <ArrowRight :size="13" /></NuxtLink>
          <button v-else class="idea-card__action" @click="openGeneration(idea)"><WandSparkles :size="14" /> Configure video <ArrowRight :size="13" /></button>
        </article>
        <button class="column-add" @click="ideaModalOpen = true"><Plus :size="14" /> Add idea</button>
      </section>
    </div>

    <UiAppCard v-else :padded="false" class="table-wrap">
      <table class="data-table"><thead><tr><th>Idea</th><th>Audience</th><th>Opportunity</th><th>Status</th><th>Production</th><th /></tr></thead><tbody><tr v-for="idea in filteredIdeas" :key="idea.id"><td><div class="table-title"><strong>{{ idea.title }}</strong><span>{{ idea.hook }}</span></div></td><td>{{ idea.audience }}</td><td>{{ idea.topic_opportunity_score || '—' }}</td><td><UiStatusBadge :status="idea.status" /></td><td>{{ productionLabel(idea) || 'Not started' }}</td><td><NuxtLink v-if="idea.production" class="button button--small" :to="`/productions/${idea.production.generation_job_id}`">Open</NuxtLink><button v-else class="button button--small" @click="openGeneration(idea)">Configure</button></td></tr></tbody></table>
    </UiAppCard>

    <div v-if="ideaModalOpen" class="modal-backdrop" @click.self="ideaModalOpen = false">
      <form class="modal" @submit.prevent="saveIdea">
        <div class="modal__header"><div><h2>New content idea</h2><p>Keep one audience and one core thought per short video.</p></div><button type="button" class="icon-button icon-button--plain" @click="ideaModalOpen = false"><X :size="18" /></button></div>
        <div class="modal__body"><div class="form-grid"><div class="field field--full"><label for="idea-title">Idea or topic</label><input id="idea-title" v-model="form.title" data-testid="idea-title" required minlength="3" placeholder="Explain one valuable idea clearly" /></div><div class="field field--full"><label for="idea-hook">Opening hook</label><textarea id="idea-hook" v-model="form.hook" placeholder="What should the audience understand in the first two seconds?" /></div><div class="field"><label for="idea-audience">Primary audience</label><input id="idea-audience" v-model="form.audience" required minlength="2" placeholder="Product leaders" /></div><div class="field"><label for="idea-objective">Objective</label><select id="idea-objective" v-model="form.objective"><option value="awareness">Awareness</option><option value="education">Education</option><option value="traffic">Traffic</option><option value="lead">Lead</option><option value="install">Install</option><option value="purchase">Purchase</option></select></div><div class="field field--full"><label for="idea-visual-mode">Default visual style</label><select id="idea-visual-mode" v-model="form.visual_mode"><option value="ugc_creator">Creator-led UGC · separate voiceover</option><option value="ugc_native_audio">Talking-head UGC · native Veo speech</option><option value="product_demo">Product demo</option><option value="cinematic">Cinematic b-roll</option><option value="motion_graphics">Motion graphics</option></select></div><div v-if="ideaUsesCharacter" class="field field--full"><label for="idea-character">Default character</label><select id="idea-character" v-model="form.character_id" :required="form.visual_mode === 'ugc_native_audio'"><option value="">{{ form.visual_mode === 'ugc_native_audio' ? 'Select a character' : 'Let the director cast a creator' }}</option><option v-for="character in characters" :key="character.id" :value="character.id">{{ character.name }}</option></select></div></div></div>
        <div class="modal__footer"><button type="button" class="button" @click="ideaModalOpen = false">Cancel</button><button class="button button--primary" data-testid="save-idea" :disabled="saving">{{ saving ? 'Saving…' : 'Create idea' }}</button></div>
      </form>
    </div>

    <div v-if="generationModalOpen && selectedIdea" class="modal-backdrop" data-testid="generation-config" @click.self="generationModalOpen = false">
      <form class="modal generation-modal" @submit.prevent="startGeneration">
        <div class="modal__header"><div><span class="eyebrow">Production setup</span><h2>{{ selectedIdea.title }}</h2><p>Choose how this idea should become a video before provider spend begins.</p></div><button type="button" class="icon-button icon-button--plain" @click="generationModalOpen = false"><X :size="18" /></button></div>
        <div class="modal__body"><div class="form-grid"><div class="field field--full"><label for="generation-mode">Video type</label><select id="generation-mode" v-model="generation.visual_mode"><option value="ugc_creator">Creator-led UGC · Google TTS</option><option value="ugc_native_audio">Talking-head UGC · Veo native speech</option><option value="product_demo">Product demo</option><option value="cinematic">Cinematic b-roll</option><option value="motion_graphics">Motion graphics</option></select></div><div v-if="generationUsesCharacter" class="field field--full"><label for="generation-character">Character</label><select id="generation-character" v-model="generation.character_id" :required="generation.visual_mode === 'ugc_native_audio'"><option value="">{{ generation.visual_mode === 'ugc_native_audio' ? 'Select a reusable character' : 'Let the director cast a creator' }}</option><option v-for="character in characters" :key="character.id" :value="character.id">{{ character.name }}</option></select><small v-if="!characters.length">Create a reusable identity in <NuxtLink to="/characters">Characters</NuxtLink>.</small></div><div class="field"><label for="generation-duration">Target duration</label><div class="input-with-unit"><input id="generation-duration" v-model.number="generation.target_duration_seconds" type="number" min="8" max="60" required><span>seconds</span></div></div><div class="field"><label for="scene-range">Preferred scene count</label><input id="scene-range" v-model="sceneRange" :class="{ invalid: !parsedSceneRange }" required placeholder="4 or 12-18"><small>{{ parsedSceneRange ? `Director target ${parsedSceneRange.min}–${parsedSceneRange.max}` : 'Enter 2–20, for example 4 or 12-18' }}</small></div><div class="field field--full"><label>Aspect ratios</label><div class="choice-row"><button v-for="ratio in ['9:16','16:9']" :key="ratio" type="button" :class="['choice-button',{active:generation.aspect_ratios.includes(ratio)}]" @click="toggleRatio(ratio)"><Check v-if="generation.aspect_ratios.includes(ratio)" :size="13" /> {{ ratio }} · {{ ratio === '9:16' ? 'vertical' : 'landscape' }}</button></div></div><div class="field"><label for="approval-mode">Approval</label><select id="approval-mode" v-model="generation.approval_mode"><option value="final_only">Review final video</option><option value="manual_all">Review every stage</option><option value="draft_only">Draft only</option><option value="auto_low_risk">Auto only when low risk</option></select></div><div class="field"><label for="max-cost">Cost guard</label><div class="input-with-unit"><span>$</span><input id="max-cost" v-model.number="generation.max_cost_usd" type="number" min="0.1" max="1000" step="0.1"></div></div><label class="checkbox-row field--full"><input v-model="allowSceneFlex" type="checkbox"> Allow the director up to ±2 scenes when dialogue would be rushed or the idea finishes earlier.</label></div><div class="generation-note"><Sparkles :size="16" /><span>Estimated {{ averageSceneDuration ? averageSceneDuration.toFixed(1) : '—' }} seconds per scene. Native speech is transcribed after every clip; incomplete lines are shortened and regenerated automatically. The final frame of each scene seeds the next one.</span></div></div>
        <div class="modal__footer"><button type="button" class="button" @click="generationModalOpen = false">Cancel</button><button class="button button--primary" data-testid="start-generation" :disabled="starting || !parsedSceneRange"><WandSparkles :size="14" /> {{ starting ? 'Starting…' : 'Start production' }}</button></div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.idea-card__move{display:flex;align-items:center;gap:4px}.idea-card__move select{width:76px;padding:3px 17px 3px 5px;border:1px solid var(--border);border-radius:6px;background:white;color:var(--muted);font-size:7px}
.segmented{display:flex;padding:3px;border:1px solid var(--border);border-radius:9px;background:white}.segmented button{display:grid;width:29px;height:27px;place-items:center;border-radius:6px;background:transparent;color:var(--muted)}.segmented button.active{background:var(--primary-100);color:var(--primary-700)}.ideas-toolbar{display:flex;align-items:center;gap:8px;margin-bottom:15px}.ideas-search{display:flex;min-width:210px;align-items:center;gap:7px;padding:8px 10px;border:1px solid var(--border);border-radius:9px;background:white;color:var(--muted);font-size:10px}.ideas-search input{min-width:0;border:0;outline:0}.toolbar-chip{padding:7px 9px;border:1px solid var(--border);border-radius:9px;background:white;color:var(--muted-strong);font-size:9px}.toolbar-count{margin-left:auto;color:var(--muted);font-size:9px}.idea-board{display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:12px;overflow-x:auto;padding-bottom:12px}.idea-column{min-width:220px;padding:3px;border:1px solid transparent;border-radius:13px;transition:.15s}.idea-column--target{border-color:var(--primary-300);background:var(--primary-50)}.idea-column>header{display:flex;align-items:center;gap:7px;padding:0 3px 10px;color:var(--muted-strong);font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.07em}.idea-column>header small{display:grid;min-width:19px;height:19px;place-items:center;border-radius:6px;background:#eae6ec;color:var(--muted);font-size:8px}.idea-card{margin-bottom:9px;padding:14px;border:1px solid var(--border);border-radius:12px;background:white;box-shadow:var(--shadow-sm);transition:.15s}.idea-card--linked{border-color:var(--primary-400);box-shadow:0 0 0 3px var(--primary-100)}.idea-card--dragging{opacity:.45}.idea-card__top{display:flex;align-items:center;justify-content:space-between}.drag-handle{display:grid;place-items:center;color:var(--muted);cursor:grab}.idea-card h3{margin:11px 0 5px;font-family:var(--font-display);font-size:12px;line-height:1.4}.idea-card>p{min-height:31px;margin:0;color:var(--muted);font-size:9px;line-height:1.55}.idea-card__tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}.idea-card__tags span{padding:4px 6px;border-radius:6px;background:var(--surface-soft);color:var(--muted-strong);font-size:7px}.idea-card__score{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:11px;padding-top:10px;border-top:1px solid #efecf0}.idea-card__score div{display:grid;gap:1px}.idea-card__score strong{font-family:var(--font-display);font-size:13px}.idea-card__score span{color:var(--muted);font-size:7px;text-transform:uppercase}.idea-production{display:grid;gap:6px;margin-top:10px}.idea-production>div{display:flex;align-items:center;gap:6px;color:var(--primary-700);font-size:8px;text-transform:capitalize}.idea-card__action{display:flex;width:100%;align-items:center;gap:6px;margin-top:11px;padding:7px 8px;border-radius:8px;background:var(--primary-50);color:var(--primary-700);font-size:9px;font-weight:800}.idea-card__action svg:last-child{margin-left:auto}.column-add{display:flex;width:100%;align-items:center;justify-content:center;gap:6px;padding:9px;border:1px dashed var(--border-strong);border-radius:10px;background:transparent;color:var(--muted);font-size:9px}.generation-modal{width:min(720px,calc(100vw - 32px))}.choice-row{display:flex;gap:8px}.choice-button{display:flex;flex:1;align-items:center;justify-content:center;gap:6px;padding:10px;border:1px solid var(--border-strong);border-radius:9px;background:white;color:var(--muted-strong);font-size:9px}.choice-button.active{border-color:var(--primary-400);background:var(--primary-50);color:var(--primary-700);font-weight:800}.input-with-unit{display:flex;align-items:center;border:1px solid var(--border-strong);border-radius:9px;background:white}.input-with-unit input{min-width:0;flex:1;border:0!important}.input-with-unit span{padding:0 9px;color:var(--muted);font-size:8px}.field input.invalid{border-color:var(--red)!important}.generation-note{display:flex;align-items:flex-start;gap:8px;margin-top:15px;padding:10px;border-radius:9px;background:var(--primary-50);color:var(--primary-700);font-size:9px;line-height:1.5}@media(max-width:700px){.ideas-toolbar{overflow-x:auto}.toolbar-count{display:none}.idea-board{grid-template-columns:repeat(4,250px)}}
</style>
