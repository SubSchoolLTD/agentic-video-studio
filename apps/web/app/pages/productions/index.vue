<script setup lang="ts">
import { ArrowRight, Clapperboard, Filter, Plus, Search, WandSparkles } from 'lucide-vue-next'

const { api, projectId } = useApi()
const { data } = await useAsyncData('production-list', () => api<any>(`/v1/projects/${projectId.value}/generation-jobs`), { default: () => ({ items: [] }) })
const jobs = computed(() => data.value.items || [])

function formatDate(value: string) {
  return new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value))
}
</script>

<template>
  <div>
    <UiPageHeader eyebrow="Durable workflow" title="Productions" description="Research, script, policy, storyboard, scenes, render, QA and scoring remain inspectable at every step.">
      <NuxtLink to="/ideas?create=1" class="button button--primary"><Plus :size="15" /> New production</NuxtLink>
    </UiPageHeader>
    <div class="list-toolbar"><div><Search :size="15" /><span>Search production jobs…</span></div><button><Filter :size="14" /> All states</button><span>{{ jobs.length }} jobs</span></div>
    <UiAppCard v-if="jobs.length" :padded="false" class="table-wrap">
      <table class="data-table production-table"><thead><tr><th>Production</th><th>Status</th><th>Current stage</th><th>Outputs</th><th>Cost</th><th>Created</th><th /></tr></thead><tbody><tr v-for="job in jobs" :key="job.id"><td><div class="production-title"><span><Clapperboard :size="16" /></span><div class="table-title"><strong>{{ job.title || 'Untitled production' }}</strong><small>{{ job.id }}</small></div></div></td><td><UiStatusBadge :status="job.status" /></td><td><div class="stage-cell"><strong>{{ job.current_stage?.replaceAll('_', ' ') }}</strong><UiProgressBar :value="job.progress || 0" /></div></td><td>{{ job.aspect_ratios?.join(' · ') || '—' }}</td><td>${{ Number(job.actual_cost_usd || 0).toFixed(2) }}</td><td>{{ formatDate(job.created_at) }}</td><td><NuxtLink class="icon-button" :to="`/productions/${job.id}`"><ArrowRight :size="15" /></NuxtLink></td></tr></tbody></table>
    </UiAppCard>
    <UiAppCard v-else><div class="empty-state"><div><span class="empty-state__icon"><WandSparkles :size="23" /></span><h3>No production jobs yet</h3><p>Select a researched idea or start from a manual brief. The workflow returns immediately and saves every stage.</p><NuxtLink to="/ideas?create=1" class="button button--primary">Create first production</NuxtLink></div></div></UiAppCard>
  </div>
</template>

<style scoped>
.list-toolbar{display:flex;align-items:center;gap:8px;margin-bottom:13px}.list-toolbar>div,.list-toolbar>button{display:flex;align-items:center;gap:7px;padding:8px 10px;border:1px solid var(--border);border-radius:9px;background:white;color:var(--muted);font-size:9px}.list-toolbar>span{margin-left:auto;color:var(--muted);font-size:9px}.production-title{display:flex;align-items:center;gap:9px}.production-title>span{display:grid;width:33px;height:33px;place-items:center;border-radius:9px;background:var(--primary-50);color:var(--primary-600)}.table-title small{color:var(--muted);font-size:7px}.stage-cell{display:grid;min-width:120px;gap:6px}.stage-cell strong{font-size:9px;text-transform:capitalize}.production-table td{white-space:nowrap}
</style>

