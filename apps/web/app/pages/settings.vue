<script setup lang="ts">
import { Check, CircleDollarSign, Pause, Play, Save, ShieldCheck } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { show } = useToast()
const saving = ref(false)
const { data, refresh } = await useAsyncData('settings', async () => {
  const [project, brand] = await Promise.all([
    api<any>(`/v1/projects/${projectId.value}`),
    api<any>(`/v1/projects/${projectId.value}/brand-profile`),
  ])
  return { project, brand }
})
const projectForm = reactive({ name: '', timezone: '', automation_mode: 'assisted', weekly_cap: 3, monthly_budget: 120, readiness_manual: 70, readiness_autopublish: 88 })
const brandForm = reactive({ description: '', allowedClaims: '', prohibitedClaims: '', primaryCta: '' })

watchEffect(() => {
  if (!data.value) return
  const project = data.value.project
  const brand = data.value.brand
  projectForm.name = project.name || ''
  projectForm.timezone = project.timezone || 'America/New_York'
  projectForm.automation_mode = project.automation_mode || 'assisted'
  projectForm.weekly_cap = project.settings?.publishing?.weekly_cap || 3
  projectForm.monthly_budget = project.settings?.budget?.monthly_usd || 120
  projectForm.readiness_manual = project.settings?.scoring?.readiness_manual || 70
  projectForm.readiness_autopublish = project.settings?.scoring?.readiness_autopublish || 88
  brandForm.description = brand.description || brand.identity?.description || ''
  brandForm.allowedClaims = (brand.claims?.allowed || []).join('\n')
  brandForm.prohibitedClaims = (brand.claims?.prohibited || []).join('\n')
  brandForm.primaryCta = brand.cta?.primary || ''
})

async function save() {
  saving.value = true
  try {
    await Promise.all([
      api(`/v1/projects/${projectId.value}`, { method: 'PATCH', body: { name: projectForm.name, timezone: projectForm.timezone, automation_mode: projectForm.automation_mode, settings: { publishing: { weekly_cap: projectForm.weekly_cap }, budget: { monthly_usd: projectForm.monthly_budget }, scoring: { readiness_manual: projectForm.readiness_manual, readiness_autopublish: projectForm.readiness_autopublish, confidence: .65 } } } }),
      api(`/v1/projects/${projectId.value}/brand-profile`, { method: 'PATCH', body: { description: brandForm.description, claims: { allowed: brandForm.allowedClaims.split('\n').filter(Boolean), prohibited: brandForm.prohibitedClaims.split('\n').filter(Boolean), require_source: data.value?.brand.claims?.require_source || [] }, cta: { ...(data.value?.brand.cta || {}), primary: brandForm.primaryCta }, confirmed: true } }),
    ])
    await refresh()
    show('Settings saved', 'A new confirmed brand-profile version was created.', 'success')
  }
  catch (error: any) { show('Could not save settings', error.message, 'error') }
  finally { saving.value = false }
}

async function toggleProject() {
  const action = data.value?.project.status === 'paused' ? 'resume' : 'pause'
  try {
    await api(`/v1/projects/${projectId.value}/${action}`, { method: 'POST' })
    await refresh()
    show(action === 'pause' ? 'Autopilot paused' : 'Project resumed', 'In-flight jobs remain auditable.', 'success')
  }
  catch (error: any) { show('Could not update project', error.message, 'error') }
}
</script>

<template>
  <div v-if="data">
    <UiPageHeader eyebrow="Project controls" title="Project settings" description="Protected constraints, budget and automation thresholds require explicit human confirmation.">
      <button class="button" @click="toggleProject"><Play v-if="data.project.status === 'paused'" :size="14" /><Pause v-else :size="14" /> {{ data.project.status === 'paused' ? 'Resume project' : 'Pause autopilot' }}</button>
      <button class="button button--primary" :disabled="saving" data-testid="save-settings" @click="save"><Save :size="14" /> {{ saving ? 'Saving…' : 'Save settings' }}</button>
    </UiPageHeader>

    <div class="settings-grid">
      <UiAppCard class="settings-nav"><strong>Project</strong><span class="active">General</span><span>Brand voice</span><span>Automation</span><span>Budget & limits</span><span>Compliance</span></UiAppCard>
      <div class="stack">
        <UiAppCard>
          <div class="section-heading"><div><h2>General</h2><p>Shared context for every agent and adapter.</p></div><UiStatusBadge :status="data.project.status" /></div>
          <div class="form-grid"><div class="field"><label>Project name</label><input v-model="projectForm.name" /></div><div class="field"><label>Timezone</label><input v-model="projectForm.timezone" /></div><div class="field field--full"><label>Automation mode</label><select v-model="projectForm.automation_mode"><option value="manual">Manual</option><option value="assisted">Assisted</option><option value="auto_safe">Auto-safe</option><option value="draft_only">Draft only</option></select></div></div>
        </UiAppCard>
        <UiAppCard>
          <div class="section-heading"><div><h2>Brand and claims</h2><p>Confirmed profile v{{ data.brand.version }} is immutable; saving creates the next version.</p></div><ShieldCheck :size="18" /></div>
          <div class="form-grid"><div class="field field--full"><label>Brand description</label><textarea v-model="brandForm.description" /></div><div class="field"><label>Allowed claims</label><textarea v-model="brandForm.allowedClaims" /></div><div class="field"><label>Prohibited claims</label><textarea v-model="brandForm.prohibitedClaims" /></div><div class="field field--full"><label>Primary call to action</label><input v-model="brandForm.primaryCta" /></div></div>
        </UiAppCard>
        <UiAppCard>
          <div class="section-heading"><div><h2>Budget and decision thresholds</h2><p>Money, publication and compliance limits are protected.</p></div><CircleDollarSign :size="18" /></div>
          <div class="form-grid"><div class="field"><label>Monthly budget, USD</label><input v-model.number="projectForm.monthly_budget" type="number" min="0" /></div><div class="field"><label>Weekly publication cap</label><input v-model.number="projectForm.weekly_cap" type="number" min="0" /></div><div class="field"><label>Manual-review readiness</label><input v-model.number="projectForm.readiness_manual" type="number" min="0" max="100" /></div><div class="field"><label>Auto-publish readiness</label><input v-model.number="projectForm.readiness_autopublish" type="number" min="0" max="100" /></div></div>
          <div class="protected-note"><Check :size="15" /><span>Changes are audit-logged. The confidence gate remains independent from readiness and predicted performance.</span></div>
        </UiAppCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-grid{display:grid;grid-template-columns:190px minmax(0,1fr);gap:15px;align-items:start}.settings-nav{position:sticky;top:82px;display:grid!important;gap:4px;padding:11px!important}.settings-nav strong{padding:8px 9px;color:var(--muted);font-size:8px;text-transform:uppercase;letter-spacing:.1em}.settings-nav span{padding:9px;border-radius:8px;color:var(--muted-strong);font-size:10px}.settings-nav .active{background:var(--primary-50);color:var(--primary-700);font-weight:700}.protected-note{display:flex;align-items:center;gap:7px;margin-top:15px;padding:9px;border-radius:8px;background:var(--green-soft);color:var(--green);font-size:8px}@media(max-width:800px){.settings-grid{grid-template-columns:1fr}.settings-nav{position:static;grid-template-columns:repeat(3,1fr)}.settings-nav strong{grid-column:1/-1}}
</style>
