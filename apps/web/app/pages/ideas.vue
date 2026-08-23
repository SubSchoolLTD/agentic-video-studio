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
const generationError = ref('')
const search = ref('')
const audienceFilter = ref('')
const objectiveFilter = ref('')
const selectedIdea = ref<any>(null)
const draggingId = ref('')
const dragTarget = ref('')
const form = reactive({ title: '', hook: '', audience: '', objective: 'awareness', visual_mode: 'ugc_creator', audio_mode: 'google_tts', native_voice_preset: 'warm_conversational', character_id: '' })
const generation = reactive({ visual_mode: 'ugc_creator', audio_mode: 'google_tts', native_voice_preset: 'warm_conversational', character_id: '', aspect_ratios: ['9:16'] as string[], target_duration_seconds: 30, approval_mode: 'final_only', variants: 1, burn_in_captions: false, max_cost_usd: 30 })
const sceneRange = ref('4-6')
const allowSceneFlex = ref(true)
const videoTypes = [
  { value: 'ugc_creator', label: 'Creator-led UGC', description: 'A recurring or AI-cast creator addresses the viewer in an informal social-first style.' },
  { value: 'storytelling', label: 'Storytelling / sketch', description: 'A compact story with recurring roles, a setup, conflict, dialogue, action and payoff.' },
  { value: 'cinematic', label: 'Cinematic b-roll', description: 'Story-driven atmospheric shots with camera movement and no required presenter.' },
  { value: 'motion_graphics', label: 'Motion graphics', description: 'Graphic-led visual explanation for concepts that do not need a physical presenter.' },
]
const audioModes = [
  { value: 'google_tts', label: 'Google TTS', description: 'Veo generates visuals silently; a consistent Google voiceover is added during rendering.' },
  { value: 'veo_native', label: 'Veo 3 native voice', description: 'For UGC, Veo extends one continuous performance to preserve face, voice and lip sync. Other formats use intentional scene-local roles and voices.' },
]
const nativeVoicePresets = [
  { value: 'warm_conversational', label: 'Warm conversational', description: 'Lower-mid pitch, warm timbre and relaxed friendly cadence.' },
  { value: 'calm_expert', label: 'Calm expert', description: 'Medium-low pitch, precise articulation and quiet confidence.' },
  { value: 'bright_creator', label: 'Bright creator', description: 'Bright pitch, lively cadence and upbeat social energy.' },
  { value: 'grounded_storyteller', label: 'Grounded storyteller', description: 'Rich timbre, unhurried pacing and intimate emphasis.' },
]

watch(() => route.query.create, value => { if (value === '1') ideaModalOpen.value = true })

const { data, refresh } = await useAsyncData('ideas-list', () => api<any>(`/v1/projects/${projectId.value}/ideas`), { default: () => ({ items: [] }) })
const { data: characterData } = await useAsyncData('idea-characters', () => api<any>(`/v1/projects/${projectId.value}/characters`), { default: () => ({ items: [] }) })
const { data: billingSummary, refresh: refreshBilling } = await useAsyncData('ideas-billing-summary', () => api<any>('/v1/billing/summary'), { default: () => ({ balance_cents: 0, balance_usd: 0, prices: [] }) })
const ideas = computed(() => data.value.items || [])
const characters = computed(() => (characterData.value?.items || []).filter((item: any) => item.status === 'ready'))
const ideaUsesCharacter = computed(() => form.visual_mode === 'ugc_creator')
const generationUsesCharacter = computed(() => generation.visual_mode === 'ugc_creator')
const continuousNativeUgc = computed(() => generation.visual_mode === 'ugc_creator' && generation.audio_mode === 'veo_native')
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
const generationFeature = computed(() => generation.audio_mode === 'veo_native' ? 'video.generate_native_audio' : 'video.generate')
const generationUnitCents = computed(() => Number((billingSummary.value?.prices || []).find((item: any) => item.feature_key === generationFeature.value)?.charge_cents || 0))
const veoDuration = (seconds: number) => seconds <= 4 ? 4 : seconds <= 6 ? 6 : 8
const generationBillableSeconds = computed(() => {
  if (!parsedSceneRange.value) return 0
  if (continuousNativeUgc.value) {
    const candidates: number[] = []
    for (let count = 2; count <= 5; count += 1) {
      for (const opening of [4, 6, 8]) {
        const finalVisible = generation.target_duration_seconds - opening - 7 * Math.max(0, count - 2)
        if (finalVisible >= 2.5 && finalVisible <= 7) candidates.push(opening + 7 * (count - 1))
      }
    }
    return candidates.length ? Math.min(...candidates) : 0
  }
  const flex = allowSceneFlex.value ? 2 : 0
  const min = Math.max(2, parsedSceneRange.value.min - flex)
  const max = Math.min(20, parsedSceneRange.value.max + flex)
  return Math.max(...Array.from({ length: max - min + 1 }, (_, index) => {
    const sceneCount = min + index
    return sceneCount * veoDuration(generation.target_duration_seconds / sceneCount)
  }))
})
const generationRequiredCents = computed(() => generationUnitCents.value * generationBillableSeconds.value * generation.aspect_ratios.length)
const generationAvailableCents = computed(() => Number(billingSummary.value?.balance_cents || 0))
const hasGenerationBalance = computed(() => generationRequiredCents.value <= generationAvailableCents.value)
const money = (cents: number) => `$${(Number(cents || 0) / 100).toFixed(2)}`

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
    Object.assign(form, { title: '', hook: '', audience: '', objective: 'awareness', visual_mode: 'ugc_creator', audio_mode: 'google_tts', native_voice_preset: 'warm_conversational', character_id: '' })
    await router.replace({ query: {} })
    await refresh()
  }
  catch (error: any) { show('Could not add idea', error.message, 'error') }
  finally { saving.value = false }
}

async function openGeneration(idea: any) {
  selectedIdea.value = idea
  Object.assign(generation, {
    visual_mode: idea.visual_mode || 'ugc_creator',
    audio_mode: idea.audio_mode || 'google_tts',
    native_voice_preset: idea.native_voice_preset || 'warm_conversational',
    character_id: idea.character_id || '',
    aspect_ratios: ['9:16'],
    target_duration_seconds: Number(idea.target_duration_seconds || 30),
    approval_mode: 'final_only',
    variants: 1,
    burn_in_captions: false,
    max_cost_usd: 30,
  })
  const recommendedMin = Number(idea.scene_count_min || 4)
  const recommendedMax = Number(idea.scene_count_max || 6)
  sceneRange.value = recommendedMin === recommendedMax ? `${recommendedMin}` : `${recommendedMin}-${recommendedMax}`
  allowSceneFlex.value = true
  generationError.value = ''
  await refreshBilling()
  generationModalOpen.value = true
}

function toggleRatio(ratio: string) {
  const existing = generation.aspect_ratios.indexOf(ratio)
  if (existing >= 0 && generation.aspect_ratios.length > 1) generation.aspect_ratios.splice(existing, 1)
  else if (existing < 0) generation.aspect_ratios.push(ratio)
}

async function startGeneration() {
  if (!selectedIdea.value || !parsedSceneRange.value) return show('Check the scene range', 'Use one number such as 4 or a range such as 12-18 (2 to 20).', 'error')
  if (continuousNativeUgc.value && generation.target_duration_seconds > 36) return show('Shorten native UGC', 'A continuous Veo-native performance is limited to 36 seconds. Choose Google TTS or a vignette format for a longer video.', 'error')
  if (continuousNativeUgc.value && parsedSceneRange.value.min > 5) return show('Reduce the scene count', 'Continuous native UGC supports one opening clip plus up to four Veo extensions.', 'error')
  if (!hasGenerationBalance.value) {
    generationError.value = `This production needs up to ${money(generationRequiredCents.value)}; the workspace has ${money(generationAvailableCents.value)}.`
    return show('Not enough balance', generationError.value, 'error')
  }
  generationError.value = ''
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
        audio_mode: generation.audio_mode,
        native_voice_preset: generation.native_voice_preset,
        character_id: generation.character_id || null,
        scene_count_min: parsedSceneRange.value.min,
        scene_count_max: parsedSceneRange.value.max,
        scene_count_flex: allowSceneFlex.value ? 2 : 0,
        burn_in_captions: generation.burn_in_captions,
        max_cost_usd: generation.max_cost_usd,
      },
    })
    generationModalOpen.value = false
    show('Production started', 'Its stage and progress are now attached to this idea card.', 'success')
    await Promise.all([refresh(), refreshBilling()])
    if (result.status === 'budget_blocked') show('Production needs a higher cost guard', 'Open the production to review the configured limit.', 'error')
  }
  catch (error: any) {
    if (error.status === 402 || error.code === 'insufficient_balance') {
      await refreshBilling()
      const available = Number(error.details?.available_cents ?? generationAvailableCents.value)
      const required = Number(error.details?.required_cents ?? generationRequiredCents.value)
      generationError.value = `This production needs ${money(required)}; the workspace has ${money(available)}.`
      show('Not enough balance', generationError.value, 'error')
    }
    else show('Could not start production', error.message, 'error')
  }
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
          <div class="idea-card__tags"><span>{{ idea.audience || 'General audience' }}</span><span>{{ idea.objective || 'awareness' }}</span><span>{{ (idea.visual_mode || 'ugc_creator').replaceAll('_', ' ') }}</span><span>{{ idea.audio_mode === 'veo_native' ? 'Veo native voice' : 'Google TTS' }}</span></div>
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
        <div class="modal__body"><div class="form-grid"><div class="field field--full"><label for="idea-title">Idea or topic</label><input id="idea-title" v-model="form.title" data-testid="idea-title" required minlength="3" placeholder="Explain one valuable idea clearly" /></div><div class="field field--full"><label for="idea-hook">Opening hook</label><textarea id="idea-hook" v-model="form.hook" placeholder="What should the audience understand in the first two seconds?" /></div><div class="field"><label for="idea-audience">Primary audience</label><input id="idea-audience" v-model="form.audience" required minlength="2" placeholder="Product leaders" /></div><div class="field"><label for="idea-objective">Objective</label><select id="idea-objective" v-model="form.objective"><option value="awareness">Awareness</option><option value="education">Education</option><option value="traffic">Traffic</option><option value="lead">Lead</option><option value="install">Install</option><option value="purchase">Purchase</option></select></div><div class="field field--full"><label for="idea-visual-mode">Default visual style <UiSettingHelp :text="videoTypes.find(item => item.value === form.visual_mode)?.description || ''" /></label><select id="idea-visual-mode" v-model="form.visual_mode"><option v-for="type in videoTypes" :key="type.value" :value="type.value">{{ type.label }}</option></select></div><div class="field field--full"><label>Default voice generation</label><div class="audio-mode-switch"><label v-for="mode in audioModes" :key="mode.value" :class="{ active: form.audio_mode === mode.value }"><input v-model="form.audio_mode" type="radio" :value="mode.value" :aria-label="mode.label"><span>{{ mode.label }} <UiSettingHelp :text="mode.description" /></span></label></div></div><div v-if="form.audio_mode === 'veo_native'" class="field field--full"><label for="idea-native-voice">Native voice profile <UiSettingHelp text="This exact vocal profile and one stable Veo seed are reused for every scene. Later clips are compared with scene one and regenerated when the speaker changes." /></label><select id="idea-native-voice" v-model="form.native_voice_preset"><option v-for="voice in nativeVoicePresets" :key="voice.value" :value="voice.value">{{ voice.label }} · {{ voice.description }}</option></select></div><div v-if="ideaUsesCharacter" class="field field--full"><label for="idea-character">Default character</label><select id="idea-character" v-model="form.character_id"><option value="">Let the director cast a creator</option><option v-for="character in characters" :key="character.id" :value="character.id">{{ character.name }}</option></select></div></div></div>
        <div class="modal__footer"><button type="button" class="button" @click="ideaModalOpen = false">Cancel</button><button class="button button--primary" data-testid="save-idea" :disabled="saving">{{ saving ? 'Saving…' : 'Create idea' }}</button></div>
      </form>
    </div>

    <div v-if="generationModalOpen && selectedIdea" class="modal-backdrop" data-testid="generation-config" @click.self="generationModalOpen = false">
      <form class="modal generation-modal" @submit.prevent="startGeneration">
        <div class="modal__header"><div><span class="eyebrow">Production setup</span><h2>{{ selectedIdea.title }}</h2><p>Choose how this idea should become a video before provider spend begins.</p></div><button type="button" class="icon-button icon-button--plain" @click="generationModalOpen = false"><X :size="18" /></button></div>
        <div class="modal__body"><div class="form-grid"><div class="field field--full"><label>Video type</label><div class="video-type-grid" role="radiogroup" aria-label="Video type"><label v-for="type in videoTypes" :key="type.value" :class="{ active: generation.visual_mode === type.value }"><input v-model="generation.visual_mode" type="radio" :value="type.value" :aria-label="type.label"><span><strong>{{ type.label }}</strong><UiSettingHelp :text="type.description" /></span><small>{{ type.description }}</small></label></div></div><div class="field field--full"><label>Voice generation</label><div class="audio-mode-switch" role="radiogroup" aria-label="Voice generation"><label v-for="mode in audioModes" :key="mode.value" :class="{ active: generation.audio_mode === mode.value }"><input v-model="generation.audio_mode" type="radio" :value="mode.value" :aria-label="mode.label"><span>{{ mode.label }} <UiSettingHelp :text="mode.description" /></span></label></div></div><div v-if="generation.audio_mode === 'veo_native'" class="field field--full"><label for="generation-native-voice">Native voice profile <UiSettingHelp text="For creator-led UGC, the first Veo clip is extended as one continuous performance so face, voice and lip sync carry forward. Storytelling, cinematic and motion scenes use deliberate scene-local roles and voices." /></label><select id="generation-native-voice" v-model="generation.native_voice_preset"><option v-for="voice in nativeVoicePresets" :key="voice.value" :value="voice.value">{{ voice.label }} · {{ voice.description }}</option></select></div><div v-if="generationUsesCharacter" class="field field--full"><label for="generation-character">Character</label><select id="generation-character" v-model="generation.character_id"><option value="">Let the director cast a creator</option><option v-for="character in characters" :key="character.id" :value="character.id">{{ character.name }}</option></select><small v-if="!characters.length">Create a reusable identity in <NuxtLink to="/characters">Characters</NuxtLink>.</small></div><div class="field"><label for="generation-duration">Target duration</label><div class="input-with-unit"><input id="generation-duration" v-model.number="generation.target_duration_seconds" type="number" min="8" :max="continuousNativeUgc ? 36 : 60" required><span>seconds</span></div></div><div class="field"><label for="scene-range">Preferred scene count</label><input id="scene-range" v-model="sceneRange" :class="{ invalid: !parsedSceneRange }" required placeholder="4 or 12-18"><small>{{ parsedSceneRange ? `Director target ${parsedSceneRange.min}–${parsedSceneRange.max}` : 'Enter 2–20, for example 4 or 12-18' }}</small></div><div class="field field--full"><label>Aspect ratios</label><div class="choice-row"><button v-for="ratio in ['9:16','16:9']" :key="ratio" type="button" :class="['choice-button',{active:generation.aspect_ratios.includes(ratio)}]" @click="toggleRatio(ratio)"><Check v-if="generation.aspect_ratios.includes(ratio)" :size="13" /> {{ ratio }} · {{ ratio === '9:16' ? 'vertical' : 'landscape' }}</button></div></div><div class="field"><label for="approval-mode">Approval</label><select id="approval-mode" v-model="generation.approval_mode"><option value="final_only">Review final video</option><option value="manual_all">Review every stage</option><option value="draft_only">Draft only</option><option value="auto_low_risk">Auto only when low risk</option></select></div><div class="field"><label for="max-cost">Cost guard</label><div class="input-with-unit"><span>$</span><input id="max-cost" v-model.number="generation.max_cost_usd" type="number" min="0.1" max="1000" step="0.1"></div></div><label class="checkbox-row field--full"><input v-model="allowSceneFlex" type="checkbox"> Allow the director up to ±2 scenes when dialogue would be rushed or the idea finishes earlier.</label><label class="checkbox-row field--full"><input v-model="generation.burn_in_captions" type="checkbox"> Burn captions into the video. Captions use clean outlined text without a background panel.</label></div><div :class="['token-quote',{ 'token-quote--insufficient': !hasGenerationBalance }]"><span><small>Maximum production charge</small><strong>{{ money(generationRequiredCents) }}</strong></span><span><small>Workspace balance</small><strong>{{ money(generationAvailableCents) }}</strong></span><NuxtLink v-if="!hasGenerationBalance" to="/billing">Top up balance or apply a promo →</NuxtLink></div><div v-if="generationError" class="generation-error">{{ generationError }}</div><div class="generation-note"><Sparkles :size="16" /><span>The quote includes Veo's 4/6/8-second billing increments for up to {{ generationBillableSeconds }} generated seconds per aspect ratio and the configured 20% service margin. Separate SRT and VTT subtitle files are always generated for download. Estimated {{ averageSceneDuration ? averageSceneDuration.toFixed(1) : '—' }} seconds per scene. Native speech is transcribed after every clip; late hooks, clipped lines and UGC voice drift trigger automatic retry. UGC with native audio uses cumulative Veo video extension; other formats use self-contained authored vignettes.</span></div></div>
        <div class="modal__footer"><button type="button" class="button" @click="generationModalOpen = false">Cancel</button><button class="button button--primary" data-testid="start-generation" :disabled="starting || !parsedSceneRange || !hasGenerationBalance"><WandSparkles :size="14" /> {{ starting ? 'Starting…' : 'Start production' }}</button></div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.idea-card__move{display:flex;align-items:center;gap:4px}.idea-card__move select{width:76px;padding:3px 17px 3px 5px;border:1px solid var(--border);border-radius:6px;background:white;color:var(--muted);font-size:7px}
.segmented{display:flex;padding:3px;border:1px solid var(--border);border-radius:9px;background:white}.segmented button{display:grid;width:29px;height:27px;place-items:center;border-radius:6px;background:transparent;color:var(--muted)}.segmented button.active{background:var(--primary-100);color:var(--primary-700)}.ideas-toolbar{display:flex;align-items:center;gap:8px;margin-bottom:15px}.ideas-search{display:flex;min-width:210px;align-items:center;gap:7px;padding:8px 10px;border:1px solid var(--border);border-radius:9px;background:white;color:var(--muted);font-size:10px}.ideas-search input{min-width:0;border:0;outline:0}.toolbar-chip{padding:7px 9px;border:1px solid var(--border);border-radius:9px;background:white;color:var(--muted-strong);font-size:9px}.toolbar-count{margin-left:auto;color:var(--muted);font-size:9px}.idea-board{display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:12px;overflow-x:auto;padding-bottom:12px}.idea-column{min-width:220px;padding:3px;border:1px solid transparent;border-radius:13px;transition:.15s}.idea-column--target{border-color:var(--primary-300);background:var(--primary-50)}.idea-column>header{display:flex;align-items:center;gap:7px;padding:0 3px 10px;color:var(--muted-strong);font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.07em}.idea-column>header small{display:grid;min-width:19px;height:19px;place-items:center;border-radius:6px;background:#eae6ec;color:var(--muted);font-size:8px}.idea-card{margin-bottom:9px;padding:14px;border:1px solid var(--border);border-radius:12px;background:white;box-shadow:var(--shadow-sm);transition:.15s}.idea-card--linked{border-color:var(--primary-400);box-shadow:0 0 0 3px var(--primary-100)}.idea-card--dragging{opacity:.45}.idea-card__top{display:flex;align-items:center;justify-content:space-between}.drag-handle{display:grid;place-items:center;color:var(--muted);cursor:grab}.idea-card h3{margin:11px 0 5px;font-family:var(--font-display);font-size:12px;line-height:1.4}.idea-card>p{min-height:31px;margin:0;color:var(--muted);font-size:9px;line-height:1.55}.idea-card__tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}.idea-card__tags span{padding:4px 6px;border-radius:6px;background:var(--surface-soft);color:var(--muted-strong);font-size:7px}.idea-card__score{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:11px;padding-top:10px;border-top:1px solid #efecf0}.idea-card__score div{display:grid;gap:1px}.idea-card__score strong{font-family:var(--font-display);font-size:13px}.idea-card__score span{color:var(--muted);font-size:7px;text-transform:uppercase}.idea-production{display:grid;gap:6px;margin-top:10px}.idea-production>div{display:flex;align-items:center;gap:6px;color:var(--primary-700);font-size:8px;text-transform:capitalize}.idea-card__action{display:flex;width:100%;align-items:center;gap:6px;margin-top:11px;padding:7px 8px;border-radius:8px;background:var(--primary-50);color:var(--primary-700);font-size:9px;font-weight:800}.idea-card__action svg:last-child{margin-left:auto}.column-add{display:flex;width:100%;align-items:center;justify-content:center;gap:6px;padding:9px;border:1px dashed var(--border-strong);border-radius:10px;background:transparent;color:var(--muted);font-size:9px}.generation-modal{width:min(720px,calc(100vw - 32px))}.choice-row{display:flex;gap:8px}.choice-button{display:flex;flex:1;align-items:center;justify-content:center;gap:6px;padding:10px;border:1px solid var(--border-strong);border-radius:9px;background:white;color:var(--muted-strong);font-size:9px}.choice-button.active{border-color:var(--primary-400);background:var(--primary-50);color:var(--primary-700);font-weight:800}.input-with-unit{display:flex;align-items:center;border:1px solid var(--border-strong);border-radius:9px;background:white}.input-with-unit input{min-width:0;flex:1;border:0!important}.input-with-unit span{padding:0 9px;color:var(--muted);font-size:8px}.field input.invalid{border-color:var(--red)!important}.token-quote{display:flex;align-items:center;gap:24px;margin-top:15px;padding:11px 13px;border:1px solid var(--border);border-radius:10px;background:var(--surface-soft)}.token-quote span{display:grid;gap:2px}.token-quote small{color:var(--muted);font-size:7px;text-transform:uppercase}.token-quote strong{font-size:10px}.token-quote a{margin-left:auto;color:var(--primary-700);font-size:8px;font-weight:800}.token-quote--insufficient{border-color:#ebc5c5;background:#fff5f5}.token-quote--insufficient strong{color:var(--red)}.generation-error{margin-top:8px;color:var(--red);font-size:9px}.generation-note{display:flex;align-items:flex-start;gap:8px;margin-top:15px;padding:10px;border-radius:9px;background:var(--primary-50);color:var(--primary-700);font-size:9px;line-height:1.5}@media(max-width:700px){.ideas-toolbar{overflow-x:auto}.toolbar-count{display:none}.idea-board{grid-template-columns:repeat(4,250px)}.token-quote{align-items:flex-start;flex-direction:column;gap:8px}.token-quote a{margin-left:0}}
.video-type-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.video-type-grid>label{display:grid;gap:5px;padding:11px;border:1px solid var(--border-strong);border-radius:10px;background:white;cursor:pointer}.video-type-grid>label.active{border-color:var(--primary-400);background:var(--primary-50)}.video-type-grid input,.audio-mode-switch input{position:absolute;opacity:0;pointer-events:none}.video-type-grid span{display:flex;align-items:center}.video-type-grid strong{font-size:9px}.video-type-grid small{color:var(--muted);font-size:8px;line-height:1.45}.audio-mode-switch{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;padding:4px;border:1px solid var(--border);border-radius:10px;background:var(--surface-soft)}.audio-mode-switch>label{display:flex;align-items:center;justify-content:center;padding:9px;border-radius:7px;color:var(--muted);cursor:pointer;font-size:9px;font-weight:700}.audio-mode-switch>label.active{background:white;color:var(--primary-700);box-shadow:var(--shadow-sm)}.audio-mode-switch span{display:flex;align-items:center}@media(max-width:600px){.video-type-grid,.audio-mode-switch{grid-template-columns:1fr}}
</style>
