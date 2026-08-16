<script setup lang="ts">
import { Check, CircleDollarSign, ImageIcon, Pause, Pencil, Play, Save, Settings2, ShieldCheck, Upload, Volume2, X } from 'lucide-vue-next'

type SettingsTab = 'general' | 'brand' | 'automation' | 'budget' | 'compliance'
const { api, apiBase, projectId } = useApi()
const { show } = useToast()
const activeTab = ref<SettingsTab>('general')
const editing = ref(false)
const saving = ref(false)
const uploadingLogo = ref(false)
const logoInput = ref<HTMLInputElement | null>(null)
const logoRightsConfirmed = ref(false)
const tabs: { key: SettingsTab, label: string }[] = [
  { key: 'general', label: 'General' },
  { key: 'brand', label: 'Brand voice' },
  { key: 'automation', label: 'Automation' },
  { key: 'budget', label: 'Budget & limits' },
  { key: 'compliance', label: 'Compliance' },
]

const { data, refresh } = await useAsyncData('settings', async () => {
  const [project, brand] = await Promise.all([
    api<any>(`/v1/projects/${projectId.value}`),
    api<any>(`/v1/projects/${projectId.value}/brand-profile`),
  ])
  return { project, brand }
})
const projectForm = reactive({ name: '', timezone: '', automation_mode: 'assisted', daily_cap: 1, weekly_cap: 3, minimum_gap_hours: 18, allowed_start: '09:00', allowed_end: '18:00', quiet_start: '', quiet_end: '', pause_all_publications: false, backlog_target: 7, research_recency_days: 30, monthly_budget: 120, readiness_manual: 70, readiness_autopublish: 88, confidence_threshold: 0.65 })
const brandForm = reactive({ description: '', primaryAudiences: '', secondaryAudiences: '', valuePropositions: '', toneTraits: '', prohibitedTone: '', allowedClaims: '', prohibitedClaims: '', requireSourceClaims: '', primaryCta: '', alternativeCtas: '', mandatoryDisclosures: '', highRiskTopics: '', trustedDomains: '' })
const logoAsset = computed(() => data.value?.brand?.visual?.logo_assets?.[0] || null)
const logoUrl = computed(() => logoAsset.value?.url ? `${apiBase}${logoAsset.value.url}` : '')

function lines(value: string) { return value.split('\n').map(item => item.trim()).filter(Boolean) }
function lineValue(value: any) { return Array.isArray(value) ? value.join('\n') : '' }
function displayLines(value: string, fallback = 'Not configured') { return lines(value).join(' · ') || fallback }
function formatAutomation(value: string) { return value.replaceAll('_', ' ') }

function hydrate() {
  if (!data.value) return
  const { project, brand } = data.value
  Object.assign(projectForm, {
    name: project.name || '', timezone: project.timezone || 'America/New_York', automation_mode: project.automation_mode || 'assisted',
    weekly_cap: project.settings?.publishing?.weekly_cap ?? 3, daily_cap: project.settings?.publishing?.daily_cap ?? 1,
    minimum_gap_hours: project.settings?.publishing?.minimum_gap_hours ?? 18,
    allowed_start: project.settings?.publishing?.allowed_time_windows?.[0]?.start || '09:00', allowed_end: project.settings?.publishing?.allowed_time_windows?.[0]?.end || '18:00',
    quiet_start: project.settings?.publishing?.blackout_periods?.[0]?.start?.slice(0, 16) || '', quiet_end: project.settings?.publishing?.blackout_periods?.[0]?.end?.slice(0, 16) || '',
    pause_all_publications: Boolean(project.settings?.publishing?.pause_all_publications), backlog_target: project.settings?.research?.backlog_target ?? 7,
    research_recency_days: project.settings?.research?.recency_days ?? 30, monthly_budget: project.settings?.budget?.monthly_usd ?? 120,
    readiness_manual: project.settings?.scoring?.readiness_manual ?? 70, readiness_autopublish: project.settings?.scoring?.readiness_autopublish ?? 88,
    confidence_threshold: project.settings?.scoring?.confidence ?? 0.65,
  })
  Object.assign(brandForm, {
    description: brand.description || brand.identity?.description || '', primaryAudiences: lineValue(brand.audiences?.primary), secondaryAudiences: lineValue(brand.audiences?.secondary),
    valuePropositions: lineValue(brand.value_propositions), toneTraits: lineValue(brand.tone?.traits), prohibitedTone: lineValue(brand.tone?.prohibited),
    allowedClaims: lineValue(brand.claims?.allowed), prohibitedClaims: lineValue(brand.claims?.prohibited), requireSourceClaims: lineValue(brand.claims?.require_source),
    primaryCta: brand.cta?.primary || '', alternativeCtas: lineValue(brand.cta?.alternatives), mandatoryDisclosures: lineValue(brand.compliance?.mandatory_disclosures),
    highRiskTopics: lineValue(brand.compliance?.high_risk_topics), trustedDomains: lineValue(brand.compliance?.trusted_domains),
  })
}

watch(data, () => { if (!editing.value) hydrate() }, { immediate: true })

function beginEdit() { hydrate(); editing.value = true }
function cancelEdit() { hydrate(); editing.value = false }

async function save() {
  saving.value = true
  try {
    await api(`/v1/projects/${projectId.value}`, { method: 'PATCH', body: { name: projectForm.name, timezone: projectForm.timezone, automation_mode: projectForm.automation_mode, settings: { research: { backlog_target: projectForm.backlog_target, recency_days: projectForm.research_recency_days }, publishing: { daily_cap: projectForm.daily_cap, weekly_cap: projectForm.weekly_cap, minimum_gap_hours: projectForm.minimum_gap_hours, allowed_time_windows: [{ weekdays: [0, 1, 2, 3, 4, 5, 6], start: projectForm.allowed_start, end: projectForm.allowed_end }], blackout_periods: projectForm.quiet_start && projectForm.quiet_end ? [{ start: new Date(projectForm.quiet_start).toISOString(), end: new Date(projectForm.quiet_end).toISOString() }] : [], pause_all_publications: projectForm.pause_all_publications }, budget: { monthly_usd: projectForm.monthly_budget }, scoring: { readiness_manual: projectForm.readiness_manual, readiness_autopublish: projectForm.readiness_autopublish, confidence: projectForm.confidence_threshold } } } })
    await api(`/v1/projects/${projectId.value}/brand-profile`, { method: 'PATCH', body: { description: brandForm.description, audiences: { primary: lines(brandForm.primaryAudiences), secondary: lines(brandForm.secondaryAudiences) }, value_propositions: lines(brandForm.valuePropositions), tone: { traits: lines(brandForm.toneTraits), prohibited: lines(brandForm.prohibitedTone) }, claims: { allowed: lines(brandForm.allowedClaims), prohibited: lines(brandForm.prohibitedClaims), require_source: lines(brandForm.requireSourceClaims) }, cta: { primary: brandForm.primaryCta, alternatives: lines(brandForm.alternativeCtas) }, compliance: { mandatory_disclosures: lines(brandForm.mandatoryDisclosures), high_risk_topics: lines(brandForm.highRiskTopics), trusted_domains: lines(brandForm.trustedDomains) }, confirmed: true } })
    await refresh()
    editing.value = false
    hydrate()
    show('Settings saved', 'A new confirmed brand-profile version was created.', 'success')
  }
  catch (error: any) { show('Could not save settings', error.message, 'error') }
  finally { saving.value = false }
}

async function uploadLogo() {
  const file = logoInput.value?.files?.[0]
  if (!file) return show('Choose a logo', 'PNG, JPEG or WebP up to 5 MB.', 'error')
  if (!logoRightsConfirmed.value) return show('Confirm logo rights', 'Only upload a logo you own or may legally use.', 'error')
  uploadingLogo.value = true
  try {
    const body = new FormData()
    body.append('image', file)
    body.append('rights_confirmed', 'true')
    await api(`/v1/projects/${projectId.value}/brand-profile/logo`, { method: 'POST', body })
    if (logoInput.value) logoInput.value.value = ''
    logoRightsConfirmed.value = false
    await refresh()
    show('Logo uploaded', 'Future renders will use this image instead of a text label.', 'success')
  }
  catch (error: any) { show('Could not upload logo', error.message, 'error') }
  finally { uploadingLogo.value = false }
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
    <UiPageHeader eyebrow="Project controls" title="Project settings" description="Review configuration safely, then enter edit mode only when you intend to change it.">
      <button class="button" @click="toggleProject"><Play v-if="data.project.status === 'paused'" :size="14" /><Pause v-else :size="14" /> {{ data.project.status === 'paused' ? 'Resume project' : 'Pause autopilot' }}</button>
      <template v-if="editing"><button class="button" @click="cancelEdit"><X :size="14" /> Cancel</button><button class="button button--primary" :disabled="saving" data-testid="save-settings" @click="save"><Save :size="14" /> {{ saving ? 'Saving…' : 'Save settings' }}</button></template>
      <button v-else class="button button--primary" data-testid="edit-settings" @click="beginEdit"><Pencil :size="14" /> Edit settings</button>
    </UiPageHeader>

    <div class="settings-grid">
      <UiAppCard class="settings-nav"><strong>Project</strong><button v-for="tab in tabs" :key="tab.key" :class="{ active: activeTab === tab.key }" :data-testid="`settings-tab-${tab.key}`" @click="activeTab = tab.key">{{ tab.label }}</button></UiAppCard>
      <div class="settings-content">
        <UiAppCard v-if="activeTab === 'general'">
          <div class="section-heading"><div><h2>General</h2><p>Shared identity and locale for every agent and adapter.</p></div><UiStatusBadge :status="data.project.status" /></div>
          <div v-if="editing" class="form-grid"><div class="field"><label for="settings-project-name">Project name</label><input id="settings-project-name" v-model="projectForm.name" /></div><div class="field"><label for="settings-timezone">Timezone</label><input id="settings-timezone" v-model="projectForm.timezone" /></div></div>
          <dl v-else class="settings-values"><div><dt>Project name</dt><dd>{{ projectForm.name }}</dd></div><div><dt>Timezone</dt><dd>{{ projectForm.timezone }}</dd></div><div><dt>Status</dt><dd>{{ data.project.status }}</dd></div><div><dt>Brand profile</dt><dd>Confirmed version {{ data.brand.version }}</dd></div></dl>
        </UiAppCard>

        <UiAppCard v-else-if="activeTab === 'brand'">
          <div class="section-heading"><div><h2>Brand voice</h2><p>Positioning, audiences, tone and calls to action.</p></div><Volume2 :size="18" /></div>
          <div v-if="editing" class="form-grid"><div class="brand-logo-editor field--full"><div class="brand-logo-preview"><img v-if="logoUrl" :src="logoUrl" alt="Current brand logo"><ImageIcon v-else :size="24" /></div><div><strong>Brand logo</strong><span>Shown without a generated label or background box. Transparent PNG or WebP works best.</span><input ref="logoInput" type="file" accept="image/png,image/jpeg,image/webp"><label class="checkbox-row"><input v-model="logoRightsConfirmed" type="checkbox"> I own this logo or have permission to use it.</label><button type="button" class="button button--small" :disabled="uploadingLogo" data-testid="upload-brand-logo" @click="uploadLogo"><Upload :size="13" /> {{ uploadingLogo ? 'Uploading…' : logoAsset ? 'Replace logo' : 'Upload logo' }}</button></div></div><div class="field field--full"><label>Brand description</label><textarea v-model="brandForm.description" /></div><div class="field"><label>Primary audiences · one per line</label><textarea v-model="brandForm.primaryAudiences" /></div><div class="field"><label>Secondary audiences · one per line</label><textarea v-model="brandForm.secondaryAudiences" /></div><div class="field field--full"><label>Value propositions · one per line</label><textarea v-model="brandForm.valuePropositions" /></div><div class="field"><label>Tone traits</label><textarea v-model="brandForm.toneTraits" /></div><div class="field"><label>Prohibited tone</label><textarea v-model="brandForm.prohibitedTone" /></div><div class="field"><label>Primary call to action</label><input v-model="brandForm.primaryCta" /></div><div class="field"><label>Alternative CTAs · one per line</label><textarea v-model="brandForm.alternativeCtas" /></div></div>
          <dl v-else class="settings-values settings-values--stacked"><div><dt>Logo</dt><dd><img v-if="logoUrl" class="brand-logo-inline" :src="logoUrl" alt="Brand logo"><span v-else>Not uploaded · no logo overlay will be rendered</span></dd></div><div><dt>Description</dt><dd>{{ brandForm.description || 'Not configured' }}</dd></div><div><dt>Primary audiences</dt><dd>{{ displayLines(brandForm.primaryAudiences) }}</dd></div><div><dt>Secondary audiences</dt><dd>{{ displayLines(brandForm.secondaryAudiences) }}</dd></div><div><dt>Value propositions</dt><dd>{{ displayLines(brandForm.valuePropositions) }}</dd></div><div><dt>Tone</dt><dd>{{ displayLines(brandForm.toneTraits) }}</dd></div><div><dt>Avoid</dt><dd>{{ displayLines(brandForm.prohibitedTone) }}</dd></div><div><dt>Primary CTA</dt><dd>{{ brandForm.primaryCta || 'Not configured' }}</dd></div></dl>
        </UiAppCard>

        <UiAppCard v-else-if="activeTab === 'automation'">
          <div class="section-heading"><div><h2>Automation</h2><p>Research backlog, publishing cadence and emergency controls.</p></div><Settings2 :size="18" /></div>
          <div v-if="editing" class="form-grid"><div class="field field--full"><label>Automation mode</label><select v-model="projectForm.automation_mode"><option value="manual">Manual</option><option value="assisted">Assisted</option><option value="auto_safe">Auto-safe</option><option value="draft_only">Draft only</option></select></div><div class="field"><label>Ready-content backlog target</label><input v-model.number="projectForm.backlog_target" type="number" min="0" /></div><div class="field"><label>Research recency, days</label><input v-model.number="projectForm.research_recency_days" type="number" min="1" max="3650" /></div><div class="field"><label>Daily publication cap</label><input v-model.number="projectForm.daily_cap" type="number" min="0" /></div><div class="field"><label>Weekly publication cap</label><input v-model.number="projectForm.weekly_cap" type="number" min="0" /></div><div class="field"><label>Minimum gap, hours</label><input v-model.number="projectForm.minimum_gap_hours" type="number" min="0" /></div><div class="field"><label>Allowed start / end</label><div class="inline-inputs"><input v-model="projectForm.allowed_start" type="time" /><input v-model="projectForm.allowed_end" type="time" /></div></div><div class="field"><label>Quiet period start</label><input v-model="projectForm.quiet_start" type="datetime-local" /></div><div class="field"><label>Quiet period end</label><input v-model="projectForm.quiet_end" type="datetime-local" /></div><label class="checkbox-row field--full"><input v-model="projectForm.pause_all_publications" type="checkbox" /> Emergency pause for every publication attempt</label></div>
          <dl v-else class="settings-values"><div><dt>Mode</dt><dd>{{ formatAutomation(projectForm.automation_mode) }}</dd></div><div><dt>Research backlog</dt><dd>{{ projectForm.backlog_target }} ready ideas</dd></div><div><dt>Research recency</dt><dd>{{ projectForm.research_recency_days }} days</dd></div><div><dt>Publication limits</dt><dd>{{ projectForm.daily_cap }}/day · {{ projectForm.weekly_cap }}/week</dd></div><div><dt>Minimum gap</dt><dd>{{ projectForm.minimum_gap_hours }} hours</dd></div><div><dt>Allowed window</dt><dd>{{ projectForm.allowed_start }}–{{ projectForm.allowed_end }}</dd></div><div><dt>Emergency publication pause</dt><dd>{{ projectForm.pause_all_publications ? 'Enabled' : 'Off' }}</dd></div></dl>
        </UiAppCard>

        <UiAppCard v-else-if="activeTab === 'budget'">
          <div class="section-heading"><div><h2>Budget & limits</h2><p>Cost and decision thresholds that every automatic action must respect.</p></div><CircleDollarSign :size="18" /></div>
          <div v-if="editing" class="form-grid"><div class="field"><label>Monthly budget, USD</label><input v-model.number="projectForm.monthly_budget" type="number" min="0" /></div><div class="field"><label>Manual-review readiness</label><input v-model.number="projectForm.readiness_manual" type="number" min="70" max="100" /></div><div class="field"><label>Auto-publish readiness</label><input v-model.number="projectForm.readiness_autopublish" type="number" min="85" max="100" /></div><div class="field"><label>Minimum evidence confidence</label><input v-model.number="projectForm.confidence_threshold" type="number" min="0.6" max="1" step="0.05" /></div></div>
          <dl v-else class="settings-values"><div><dt>Monthly provider budget</dt><dd>${{ projectForm.monthly_budget }}</dd></div><div><dt>Manual review threshold</dt><dd>{{ projectForm.readiness_manual }}/100</dd></div><div><dt>Auto-publish threshold</dt><dd>{{ projectForm.readiness_autopublish }}/100</dd></div><div><dt>Evidence confidence</dt><dd>{{ Math.round(projectForm.confidence_threshold * 100) }}%</dd></div></dl>
          <div class="protected-note"><Check :size="15" /><span>Admin model pricing controls token charges; this project budget remains the hard provider-spend guard.</span></div>
        </UiAppCard>

        <UiAppCard v-else>
          <div class="section-heading"><div><h2>Compliance</h2><p>Claims, disclosures and trusted sources applied before media generation.</p></div><ShieldCheck :size="18" /></div>
          <div v-if="editing" class="form-grid"><div class="field"><label>Allowed claims · one per line</label><textarea v-model="brandForm.allowedClaims" /></div><div class="field"><label>Prohibited claims · one per line</label><textarea v-model="brandForm.prohibitedClaims" /></div><div class="field field--full"><label>Claims requiring a source · one per line</label><textarea v-model="brandForm.requireSourceClaims" /></div><div class="field"><label>Mandatory disclosures</label><textarea v-model="brandForm.mandatoryDisclosures" /></div><div class="field"><label>High-risk topics</label><textarea v-model="brandForm.highRiskTopics" /></div><div class="field field--full"><label>Trusted domains · one per line</label><textarea v-model="brandForm.trustedDomains" /></div></div>
          <dl v-else class="settings-values settings-values--stacked"><div><dt>Allowed claims</dt><dd>{{ displayLines(brandForm.allowedClaims) }}</dd></div><div><dt>Prohibited claims</dt><dd>{{ displayLines(brandForm.prohibitedClaims) }}</dd></div><div><dt>Source-required claims</dt><dd>{{ displayLines(brandForm.requireSourceClaims) }}</dd></div><div><dt>Mandatory disclosures</dt><dd>{{ displayLines(brandForm.mandatoryDisclosures) }}</dd></div><div><dt>High-risk topics</dt><dd>{{ displayLines(brandForm.highRiskTopics) }}</dd></div><div><dt>Trusted domains</dt><dd>{{ displayLines(brandForm.trustedDomains) }}</dd></div></dl>
        </UiAppCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-grid{display:grid;grid-template-columns:190px minmax(0,1fr);gap:15px;align-items:start}.settings-nav{position:sticky;top:82px;display:grid!important;gap:4px;padding:11px!important}.settings-nav strong{padding:8px 9px;color:var(--muted);font-size:8px;text-transform:uppercase;letter-spacing:.1em}.settings-nav button{padding:9px;border:0;border-radius:8px;background:transparent;color:var(--muted-strong);font-size:10px;text-align:left}.settings-nav button:hover{background:var(--surface-soft)}.settings-nav button.active{background:var(--primary-50);color:var(--primary-700);font-weight:700}.settings-content{min-width:0}.settings-values{display:grid;margin:0}.settings-values div{display:grid;grid-template-columns:minmax(150px,.7fr) minmax(0,1.3fr);gap:18px;padding:12px 0;border-bottom:1px solid var(--border)}.settings-values div:last-child{border:0}.settings-values dt{color:var(--muted);font-size:9px}.settings-values dd{margin:0;color:var(--ink);font-size:9px;font-weight:650;text-align:right;text-transform:none}.settings-values--stacked div{grid-template-columns:150px minmax(0,1fr)}.settings-values--stacked dd{line-height:1.55;text-align:left}.brand-logo-editor{display:grid;grid-template-columns:120px minmax(0,1fr);gap:14px;padding:13px;border:1px solid var(--border);border-radius:11px;background:var(--surface-soft)}.brand-logo-preview{display:grid;height:90px;place-items:center;overflow:hidden;border:1px solid var(--border);border-radius:9px;background:white;color:var(--muted)}.brand-logo-preview img{max-width:88%;max-height:72px;object-fit:contain}.brand-logo-editor>div:last-child{display:grid;align-content:start;gap:7px}.brand-logo-editor strong{font-size:10px}.brand-logo-editor span{color:var(--muted);font-size:8px;line-height:1.45}.brand-logo-editor input[type=file]{font-size:8px}.brand-logo-editor .checkbox-row{font-size:8px}.brand-logo-editor .button{width:fit-content}.brand-logo-inline{display:block;max-width:150px;max-height:55px;object-fit:contain}.protected-note{display:flex;align-items:center;gap:7px;margin-top:15px;padding:9px;border-radius:8px;background:var(--green-soft);color:var(--green);font-size:8px}.inline-inputs{display:grid;grid-template-columns:1fr 1fr;gap:6px}@media(max-width:800px){.settings-grid{grid-template-columns:1fr}.settings-nav{position:static;grid-template-columns:repeat(2,1fr)}.settings-nav strong{grid-column:1/-1}.settings-values div,.settings-values--stacked div{grid-template-columns:1fr;gap:5px}.settings-values dd{text-align:left}.brand-logo-editor{grid-template-columns:1fr}}
</style>
