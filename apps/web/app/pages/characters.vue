<script setup lang="ts">
import { ImagePlus, Sparkles, Trash2, Upload, UserRound } from 'lucide-vue-next'

const { api, apiBase, projectId } = useApi()
const { show } = useToast()
const uploadFile = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const generating = ref(false)
const uploadForm = reactive({ name: '', description: '', rights_confirmed: false, adult_confirmed: false })
const generateForm = reactive({ name: '', prompt: '' })

const { data, refresh } = await useAsyncData('character-library', () => api<any>(`/v1/projects/${projectId.value}/characters`), {
  default: () => ({ items: [] }),
})
const characters = computed(() => data.value?.items || [])

let poll: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  poll = setInterval(() => {
    if (characters.value.some((item: any) => ['queued', 'generating'].includes(item.status))) void refresh()
  }, 2500)
})
onBeforeUnmount(() => { if (poll) clearInterval(poll) })

function characterUrl(item: any) {
  return item.reference_url ? `${apiBase}${item.reference_url}` : ''
}

async function uploadCharacter() {
  const file = uploadFile.value?.files?.[0]
  if (!file) return show('Choose an image', 'JPEG, PNG or WebP up to 10 MB.', 'error')
  uploading.value = true
  try {
    const body = new FormData()
    body.append('image', file)
    body.append('name', uploadForm.name)
    body.append('description', uploadForm.description)
    body.append('rights_confirmed', String(uploadForm.rights_confirmed))
    body.append('adult_confirmed', String(uploadForm.adult_confirmed))
    await api(`/v1/projects/${projectId.value}/characters/upload`, { method: 'POST', body })
    Object.assign(uploadForm, { name: '', description: '', rights_confirmed: false, adult_confirmed: false })
    if (uploadFile.value) uploadFile.value.value = ''
    await refresh()
    show('Character saved', 'The identity reference can now be reused across UGC productions.', 'success')
  }
  catch (error: any) { show('Could not upload character', error.message, 'error') }
  finally { uploading.value = false }
}

async function generateCharacter() {
  generating.value = true
  try {
    await api(`/v1/projects/${projectId.value}/characters/generate`, { method: 'POST', body: generateForm })
    Object.assign(generateForm, { name: '', prompt: '' })
    await refresh()
    show('Character generation started', 'Gemini Image is creating an original adult creator reference.', 'success')
  }
  catch (error: any) { show('Could not generate character', error.message, 'error') }
  finally { generating.value = false }
}

async function archiveCharacter(item: any) {
  await api(`/v1/characters/${item.id}`, { method: 'DELETE' })
  await refresh()
  show('Character archived', item.name, 'success')
}
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Reusable identity references" title="Characters" description="Upload an adult creator you may legally use, or generate an original synthetic creator with Gemini Image." />

    <div class="character-create-grid">
      <UiAppCard>
        <div class="section-heading"><div><h2>Upload a creator</h2><p>Used as the identity image for Veo image-to-video scenes</p></div><Upload :size="18" /></div>
        <form class="character-form" data-testid="character-upload-form" @submit.prevent="uploadCharacter">
          <label>Name<input v-model="uploadForm.name" required minlength="2" placeholder="Maya · study creator"></label>
          <label>Description<textarea v-model="uploadForm.description" required minlength="3" placeholder="Adult creator, calm delivery, casual neutral clothes"></textarea></label>
          <label>Reference image<input ref="uploadFile" type="file" accept="image/jpeg,image/png,image/webp" required></label>
          <label class="check-row"><input v-model="uploadForm.rights_confirmed" type="checkbox" required> I own this image or have explicit permission to use it for AI video.</label>
          <label class="check-row"><input v-model="uploadForm.adult_confirmed" type="checkbox" required> Every identifiable person is an adult.</label>
          <button class="button button--primary" :disabled="uploading"><ImagePlus :size="14" /> {{ uploading ? 'Uploading…' : 'Save character' }}</button>
        </form>
      </UiAppCard>

      <UiAppCard>
        <div class="section-heading"><div><h2>Generate a creator</h2><p>Creates an original, non-celebrity identity reference</p></div><Sparkles :size="18" /></div>
        <form class="character-form" data-testid="character-generate-form" @submit.prevent="generateCharacter">
          <label>Name<input v-model="generateForm.name" required minlength="2" placeholder="Friendly product mentor"></label>
          <label>Creator brief<textarea v-model="generateForm.prompt" required minlength="8" placeholder="Adult woman in her early thirties, warm and credible, everyday home office, muted purple accent"></textarea></label>
          <div class="generation-note"><UserRound :size="16" /><span>The result is synthetic and safe to reuse. One generation costs the current Character price configured by the platform administrator.</span></div>
          <button class="button button--primary" data-testid="generate-character" :disabled="generating"><Sparkles :size="14" /> {{ generating ? 'Starting…' : 'Generate character' }}</button>
        </form>
      </UiAppCard>
    </div>

    <div class="section-heading library-heading"><div><h2>Character library</h2><p>{{ characters.length }} reusable identities in this project</p></div></div>
    <div v-if="characters.length" class="character-grid">
      <UiAppCard v-for="item in characters" :key="item.id" :padded="false" class="character-card">
        <div class="character-preview">
          <img v-if="characterUrl(item)" :src="characterUrl(item)" :alt="item.name">
          <span v-else><UserRound :size="34" /></span>
        </div>
        <div class="character-body"><div class="character-body__heading"><strong>{{ item.name }}</strong><UiStatusBadge :status="item.status" /></div><p>{{ item.description }}</p><small>{{ item.source_type === 'ai_generated' ? `Synthetic · ${item.model_id}` : 'Uploaded · rights confirmed' }}</small><button class="icon-button icon-button--plain" aria-label="Archive character" @click="archiveCharacter(item)"><Trash2 :size="14" /></button></div>
      </UiAppCard>
    </div>
    <UiAppCard v-else><div class="empty-state"><div><span class="empty-state__icon"><UserRound :size="23" /></span><h3>No characters yet</h3><p>Create one above, then select it when using a UGC generation mode.</p></div></div></UiAppCard>
  </div>
</template>

<style scoped>
.character-create-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.character-form{display:grid;gap:11px}.character-form label{display:grid;gap:5px;color:var(--muted);font-size:8px;font-weight:800;text-transform:uppercase}.character-form input:not([type=checkbox]),.character-form textarea{padding:9px;border:1px solid var(--border-strong);border-radius:9px;background:white}.character-form textarea{min-height:88px;resize:vertical}.character-form .check-row{display:flex;align-items:flex-start;gap:8px;color:var(--muted-strong);font-weight:600;line-height:1.45;text-transform:none}.generation-note{display:flex;align-items:flex-start;gap:8px;padding:10px;border-radius:9px;background:var(--primary-50);color:var(--primary-700);font-size:8px;line-height:1.5}.library-heading{margin:22px 0 11px}.character-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.character-card{overflow:hidden;background:white}.character-preview{display:grid;height:235px;place-items:center;background:var(--surface-soft);color:var(--muted)}.character-preview img{display:block;width:100%;height:100%;object-fit:cover}.character-body{position:relative;display:grid;gap:7px;padding:13px 14px 14px;background:white;color:var(--ink)}.character-body__heading{display:flex;align-items:center;gap:7px;padding-right:30px}.character-body strong{font-size:11px}.character-body p{min-height:34px;margin:0;color:var(--muted-strong);font-size:8px;line-height:1.5}.character-body small{color:var(--primary-700);font-size:7px}.character-body .icon-button{position:absolute;top:8px;right:8px}@media(max-width:1000px){.character-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:720px){.character-create-grid,.character-grid{grid-template-columns:1fr}}
</style>
