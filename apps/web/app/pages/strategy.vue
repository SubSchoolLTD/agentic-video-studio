<script setup lang="ts">
import { ArrowRight, BrainCircuit, Check, GitCompare, ShieldCheck } from 'lucide-vue-next'
const { api, projectId } = useApi()
const { show } = useToast()
const showVersions = ref(false)
const activating = ref(false)
const { data, refresh } = await useAsyncData('strategy', async () => {
  const [active, versions] = await Promise.all([
    api<any>(`/v1/projects/${projectId.value}/strategy`),
    api<any>(`/v1/projects/${projectId.value}/strategy/versions`),
  ])
  return { active, versions: versions.items || [] }
}, {
  default: () => ({
    active: { strategy_version: 0, hook_mix: {}, duration_mix: {}, visual_mix: {}, exploration_rate: 0, confidence: 0, sample_size: 0, cold_start: true, evidence: 'No performance evidence has been collected yet.' },
    versions: [],
  }),
})
const active = computed(() => data.value.active)
const proposed = computed(() => data.value.versions.find((item: any) => item.status !== 'active'))
const sections = computed(() => [
  { title: 'Hook mix', values: active.value.hook_mix || {} },
  { title: 'Duration mix', values: active.value.duration_mix || {} },
  { title: 'Visual mix', values: active.value.visual_mix || {} },
])

async function activateProposal() {
  if (!proposed.value) return
  activating.value = true
  try {
    await api(`/v1/projects/${projectId.value}/strategy/${proposed.value.id}/activate`, { method: 'POST' })
    show('Strategy activated', `Version ${proposed.value.strategy_version} is now active.`, 'success')
    await refresh()
  }
  catch (error: any) { show('Could not activate strategy', error.message, 'error') }
  finally { activating.value = false }
}
</script>
<template><div><UiPageHeader eyebrow="Versioned learning" title="Strategy memory" description="Performance evidence proposes bounded changes. Protected brand, compliance, destination and budget settings never mutate silently."><button class="button" @click="showVersions = !showVersions"><GitCompare :size="15" /> {{ showVersions ? 'Hide versions' : 'Compare versions' }}</button><button class="button button--primary" :disabled="!proposed || activating" @click="activateProposal">{{ proposed ? `Activate proposed v${proposed.strategy_version}` : 'No proposal to review' }} <ArrowRight :size="14" /></button></UiPageHeader><div class="strategy-hero"><div><span class="eyebrow">Active strategy v{{ active.strategy_version }}</span><h2 v-if="active.cold_start">Cold start: collect comparable results before adapting the mix.</h2><h2 v-else>Exploit what works. Keep {{ Math.round(active.exploration_rate*100) }}% for discovery.</h2><p>{{ active.evidence }}</p></div><UiScoreRing :value="Math.round(active.confidence*100)" label="Confidence" suffix="%" size="large" /></div><UiAppCard v-if="showVersions" class="protected-card"><div class="section-heading"><div><h2>Strategy versions</h2><p>Only explicitly activated versions influence future productions.</p></div></div><div class="mix-list"><div v-for="version in data.versions" :key="version.id"><span>v{{ version.strategy_version }} · {{ version.status }} · n={{ version.sample_size || 0 }}</span><strong>{{ Math.round(Number(version.confidence || 0)*100) }}%</strong><UiProgressBar :value="Number(version.confidence || 0)" /></div></div></UiAppCard><div class="grid-three strategy-grid"><UiAppCard v-for="section in sections" :key="section.title"><div class="section-heading"><h2>{{ section.title }}</h2><BrainCircuit :size="17" /></div><div v-if="Object.keys(section.values).length" class="mix-list"><div v-for="(value,key) in section.values" :key="key"><span>{{ String(key).replaceAll('_',' ') }}</span><strong>{{ Math.round(Number(value)*100) }}%</strong><UiProgressBar :value="Number(value)" /></div></div><p v-else>No measured mix yet.</p></UiAppCard></div><UiAppCard class="protected-card"><div><ShieldCheck :size="20" /><div><strong>Protected settings</strong><span>These always require explicit human approval.</span></div></div><div class="protected-list"><span><Check :size="13" /> Legal disclosures</span><span><Check :size="13" /> Allowed claims</span><span><Check :size="13" /> Destination URLs</span><span><Check :size="13" /> Budgets</span><span><Check :size="13" /> Publishing permissions</span></div><small>Current evidence: n={{ active.sample_size }} · {{ active.cold_start ? 'cold start; no adaptive claim is shown.' : 'observation only until confidence gates pass.' }}</small></UiAppCard></div></template>
<style scoped>.strategy-hero{display:flex;align-items:center;justify-content:space-between;gap:25px;padding:25px 28px;border-radius:18px;background:linear-gradient(145deg,#23182c,#151119);color:white;box-shadow:var(--shadow)}.strategy-hero h2{max-width:700px;margin:8px 0;font-family:var(--font-display);font-size:24px;letter-spacing:-.04em}.strategy-hero p{margin:0;color:#bcb4c3;font-size:9px}.strategy-hero .eyebrow{color:var(--primary-300)}.strategy-hero :deep(.score-ring__inner),.strategy-hero :deep(.score-ring::before){background:#211729}.strategy-hero :deep(.score-ring__inner span){color:#bcb4c3}.strategy-grid{margin-top:15px}.mix-list{display:grid;gap:12px}.mix-list>div{display:grid;grid-template-columns:1fr auto;gap:5px}.mix-list span{color:var(--muted-strong);font-size:9px;text-transform:capitalize}.mix-list strong{font-size:9px}.mix-list .progress-bar{grid-column:1/-1}.protected-card{margin-top:15px}.protected-card>div:first-child{display:flex;align-items:center;gap:9px;color:var(--green)}.protected-card>div:first-child>div{display:grid;gap:2px}.protected-card strong{color:var(--ink);font-size:11px}.protected-card span,.protected-card small{color:var(--muted);font-size:8px}.protected-list{display:flex!important;flex-wrap:wrap;gap:8px!important;margin:14px 0}.protected-list span{display:flex;align-items:center;gap:5px;padding:6px 8px;border-radius:8px;background:var(--green-soft);color:var(--green)}</style>
