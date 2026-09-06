<script setup lang="ts">
import { RotateCcw, Save, Sparkles, X } from 'lucide-vue-next'

const props = defineProps<{ scene: any, job: any, mode: 'edit' | 'regenerate' }>()
const emit = defineEmits(['close', 'saved', 'queued'])
const { api } = useApi()
const { show } = useToast()
const confirming = ref(props.mode === 'regenerate')
const busy = ref(false)
const rewriting = ref(false)
const loadingQuote = ref(false)
const quote = ref<any>(null)
const following = ref(false)
const errorMessage = ref('')
const summary = ref('')
const draft = reactive({
  narration: props.scene.narration || '',
  visual_prompt: props.scene.visual_prompt_base || props.scene.visual_prompt || '',
  speaker_kind: props.scene.speaker_kind || 'on_camera',
  feedback: '',
})
const valid = computed(() => draft.visual_prompt.trim().length >= 8 && (draft.speaker_kind === 'silent' || draft.narration.trim().length > 0))
const disabled = computed(() => busy.value || rewriting.value)

async function loadQuote() {
  quote.value = null
  errorMessage.value = ''
  loadingQuote.value = true
  try {
    quote.value = await api(`/v1/scenes/${props.scene.id}/regenerate/quote`, { method: 'POST', body: {
      reason: 'User reviewed and requested a new take', regenerate_following: following.value,
    } })
  } catch (error: any) { errorMessage.value = error.message }
  finally { loadingQuote.value = false }
}
async function rewrite() {
  rewriting.value = true
  errorMessage.value = ''
  try {
    const proposal = await api<any>(`/v1/scenes/${props.scene.id}/rewrite-prompt`, { method: 'POST', body: { ...draft } })
    draft.narration = proposal.narration
    draft.visual_prompt = proposal.visual_prompt
    summary.value = proposal.change_summary
  } catch (error: any) { errorMessage.value = error.message }
  finally { rewriting.value = false }
}
async function save(andRegenerate = false) {
  if (!valid.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    await api(`/v1/scenes/${props.scene.id}/prompt`, { method: 'PATCH', body: {
      narration: draft.narration, visual_prompt: draft.visual_prompt, speaker_kind: draft.speaker_kind,
    } })
    emit('saved')
    show('Prompt saved', 'The current video is unchanged. These instructions will be used for the next take.', 'success')
    if (andRegenerate) { confirming.value = true; await loadQuote() }
    else emit('close')
  } catch (error: any) { errorMessage.value = error.message }
  finally { busy.value = false }
}
async function confirm() {
  if (!quote.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    await api(`/v1/scenes/${props.scene.id}/regenerate`, { method: 'POST', body: {
      reason: 'User confirmed regeneration after reviewing the cost', regenerate_following: following.value,
      unlock_approved: true, quote_fingerprint: quote.value.fingerprint,
    } })
    emit('queued'); emit('close')
    show('Regeneration started', 'Progress is shown in the stage timeline. The previous render stays in version history.', 'success')
  } catch (error: any) { errorMessage.value = error.message; quote.value = null }
  finally { busy.value = false }
}
onMounted(() => { if (confirming.value) void loadQuote() })
</script>

<template>
  <div class="modal-backdrop" @click.self="!disabled && emit('close')">
    <form class="modal prompt-editor" role="dialog" aria-modal="true" aria-labelledby="scene-editor-title" @keydown.esc="!disabled && emit('close')" @submit.prevent="confirming ? confirm() : save()">
      <div class="modal__header">
        <div><span class="eyebrow">Scene {{ scene.position }} · next take</span><h2 id="scene-editor-title">{{ confirming ? 'Confirm scene regeneration' : 'Edit scene prompt' }}</h2></div>
        <button type="button" class="icon-button" aria-label="Close scene editor" :disabled="disabled" @click="emit('close')"><X :size="18" /></button>
      </div>
      <div class="modal__body">
        <template v-if="!confirming">
          <p>Saving changes the next take, not the existing video. Voice and identity instructions are added automatically.</p>
          <div class="field"><label for="prompt-narration">Spoken text</label><textarea id="prompt-narration" v-model="draft.narration" maxlength="2000" :disabled="disabled" /></div>
          <div class="field"><label for="prompt-placement">Speech placement</label><select id="prompt-placement" v-model="draft.speaker_kind" :disabled="disabled"><option value="on_camera">On camera</option><option value="voice_over">Voice-over</option><option value="silent">Silent</option></select></div>
          <div class="field"><label for="prompt-visual">Scene prompt</label><textarea id="prompt-visual" v-model="draft.visual_prompt" class="prompt-textarea" required minlength="8" maxlength="20000" :disabled="disabled" /></div>
          <div class="field"><label for="prompt-feedback">What should Gemini keep or change?</label><textarea id="prompt-feedback" v-model="draft.feedback" maxlength="4000" placeholder="Keep the character and dialogue. Move this scene outdoors and have the creator walk toward the camera…" :disabled="disabled" /></div>
          <button type="button" class="button" :disabled="disabled || !valid || draft.feedback.trim().length < 3" @click="rewrite"><Sparkles :size="14" /> {{ rewriting ? 'Gemini is rewriting…' : 'Ask Gemini to improve prompt' }}</button>
          <p v-if="summary" role="status">{{ summary }} Review the proposed changes before saving.</p>
        </template>
        <template v-else>
          <label v-if="job.continue_scenes" class="following"><input v-model="following" type="checkbox" :disabled="loadingQuote || disabled" @change="loadQuote" /> Include following scenes on the same character track</label>
          <p v-if="loadingQuote" role="status">Calculating cost…</p>
          <div v-if="quote" class="quote">
            <strong>{{ quote.test_mode ? 'Test mode · ' : '' }}${{ Number(quote.charge_usd).toFixed(2) }}</strong>
            <p>Scenes {{ quote.scene_positions.join(', ') }} · {{ quote.aspect_ratios.join(' + ') }} · {{ quote.quantity }} generated seconds.</p>
            <p>Replacing a character's first reference also replaces its dependent scenes. Only the listed scenes are included. The previous video version is kept.</p>
            <p v-if="quote.unlock_required">Confirming unlocks these approved scenes for a new take. The new render will need its own approval.</p>
            <p v-if="!quote.test_mode">This estimate includes the service markup and one take per scene/format. Quality-check retries can cost extra and remain subject to your available balance.</p>
            <p>Available balance: ${{ (quote.balance_cents / 100).toFixed(2) }}</p>
            <p v-if="quote.charge_cents > quote.balance_cents"><NuxtLink to="/billing">Top up your balance</NuxtLink> to continue.</p>
          </div>
        </template>
        <p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>
      </div>
      <div class="modal__footer">
        <button type="button" class="button" :disabled="disabled" @click="emit('close')">Cancel</button>
        <template v-if="!confirming">
          <button class="button" :disabled="disabled || !valid"><Save :size="14" /> Save</button>
          <button v-if="job.video_id" type="button" class="button button--primary" :disabled="disabled || !valid" @click="save(true)"><RotateCcw :size="14" /> Save &amp; regenerate</button>
        </template>
        <template v-else>
          <button v-if="errorMessage" type="button" class="button" :disabled="loadingQuote || disabled" @click="loadQuote">Refresh estimate</button>
          <button class="button button--primary" :disabled="!quote || disabled || loadingQuote || quote.charge_cents > quote.balance_cents"><RotateCcw :size="14" /> {{ busy ? 'Starting…' : 'Confirm regeneration' }}</button>
        </template>
      </div>
    </form>
  </div>
</template>

<style scoped>
.prompt-editor{display:flex;flex-direction:column;width:min(850px,calc(100vw - 32px));overflow:hidden}.prompt-editor .modal__header,.prompt-editor .modal__footer{flex-shrink:0}.prompt-editor .modal__body{min-height:0;overflow-y:auto}.prompt-editor .modal__footer{flex-wrap:wrap}.prompt-editor .field{margin:14px 0}.prompt-editor textarea{min-height:85px}.prompt-editor .prompt-textarea{min-height:240px}.prompt-editor p{font-size:12px;line-height:1.6;color:var(--muted-strong)}.following{display:flex;gap:8px;font-size:12px;align-items:flex-start}.quote>strong{display:block;font-size:28px;margin-top:20px}.prompt-editor .error-message{color:var(--red)}
</style>
