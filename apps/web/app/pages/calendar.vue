<script setup lang="ts">
import { ChevronLeft, ChevronRight, CircleAlert, Plus } from 'lucide-vue-next'
const { api, projectId } = useApi()
const router = useRouter()
const { data } = await useAsyncData('calendar', () => api<any>(`/v1/projects/${projectId.value}/calendar`), { default: () => ({ items: [], timezone: 'UTC', cadence: { daily_cap: 0, weekly_cap: 0, minimum_gap_hours: 0 } }) })

function initialWeekStart() {
  const [year = 1970, month = 1, day = 1] = zonedDateKey(new Date()).split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day, 12))
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7))
  return date
}

const weekStart = ref(initialWeekStart())
const days = computed(() => Array.from({ length: 7 }, (_, index) => {
  const date = new Date(weekStart.value)
  date.setUTCDate(date.getUTCDate() + index)
  return date
}))
const weekLabel = computed(() => {
  const formatter = new Intl.DateTimeFormat('en', { timeZone: 'UTC', month: 'short', day: 'numeric' })
  return `${formatter.format(days.value[0])}–${formatter.format(days.value[6])}`
})
const cadenceLabel = computed(() => {
  const cadence = data.value.cadence || {}
  const parts = []
  if (cadence.minimum_gap_hours) parts.push(`at least ${cadence.minimum_gap_hours} hours between posts`)
  if (cadence.daily_cap) parts.push(`maximum ${cadence.daily_cap} per day`)
  if (cadence.weekly_cap) parts.push(`maximum ${cadence.weekly_cap} per week`)
  return parts.length ? parts.join(' · ') : 'No publication cadence limits configured.'
})

function zonedDateKey(value: Date | string) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: data.value.timezone || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date)
  const part = (type: string) => parts.find(item => item.type === type)?.value || ''
  return `${part('year')}-${part('month')}-${part('day')}`
}

function calendarDateKey(date: Date) {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-${String(date.getUTCDate()).padStart(2, '0')}`
}

function scheduledAt(item: any) {
  return item.planned_publish_at || item.scheduled_at || item.planned_generation_at || item.approval_deadline || item.created_at
}

const itemsFor = (date: Date) => (data.value.items || []).filter((item: any) => zonedDateKey(scheduledAt(item)) === calendarDateKey(date))
const dayLabel = (date: Date) => new Intl.DateTimeFormat('en', { timeZone: 'UTC', weekday: 'short', day: 'numeric' }).format(date)
const timeLabel = (item: any) => new Intl.DateTimeFormat('en', { timeZone: data.value.timezone || 'UTC', hour: 'numeric', minute: '2-digit' }).format(new Date(scheduledAt(item)))
function moveWeek(offset: number) {
  const next = new Date(weekStart.value)
  next.setUTCDate(next.getUTCDate() + offset * 7)
  weekStart.value = next
}
</script>
<template><div><UiPageHeader eyebrow="Cadence" title="Calendar" description="Research, generation, approvals, publications and metric checkpoints share one timezone-aware plan."><button class="button" aria-label="Previous week" @click="moveWeek(-1)"><ChevronLeft :size="14" /></button><button class="button" @click="weekStart = initialWeekStart()">{{ weekLabel }}</button><button class="button" aria-label="Next week" @click="moveWeek(1)"><ChevronRight :size="14" /></button><button class="button button--primary" @click="router.push('/ideas')"><Plus :size="15" /> Plan content</button></UiPageHeader><div class="cadence-warning"><CircleAlert :size="16" /><div><strong>Cadence protected</strong><span>{{ cadenceLabel }}</span></div><small>{{ data.timezone }}</small></div><UiAppCard :padded="false" class="calendar-shell"><div class="calendar-grid"><section v-for="day in days" :key="calendarDateKey(day)"><header>{{ dayLabel(day) }}</header><div class="calendar-cell"><article v-for="item in itemsFor(day)" :key="item.id" :class="`calendar-item calendar-item--${item.kind}`"><span>{{ item.kind?.replaceAll('_',' ') }}</span><strong>{{ item.title || item.objective || item.window || 'Scheduled work' }}</strong><small>{{ timeLabel(item) }} · {{ item.status }}</small></article><button class="calendar-add" aria-label="Plan content for this week" @click="router.push('/ideas')"><Plus :size="14" /></button></div></section></div></UiAppCard><div class="calendar-legend"><span><i class="purple" /> Ideas</span><span><i class="blue" /> Research</span><span><i class="amber" /> Approval</span><span><i class="green" /> Publication / metrics</span></div></div></template>
<style scoped>.cadence-warning{display:flex;align-items:center;gap:9px;margin-bottom:13px;padding:10px 12px;border:1px solid #ecdcae;border-radius:10px;background:var(--amber-soft);color:#9a680a}.cadence-warning div{display:grid;flex:1;gap:1px}.cadence-warning strong{font-size:9px}.cadence-warning span,.cadence-warning small{font-size:8px}.calendar-shell{overflow-x:auto}.calendar-grid{display:grid;min-width:850px;grid-template-columns:repeat(7,1fr)}.calendar-grid>section{border-right:1px solid var(--border)}.calendar-grid>section:last-child{border:0}.calendar-grid header{padding:11px;border-bottom:1px solid var(--border);color:var(--muted);font-size:9px;font-weight:800;text-align:center;text-transform:uppercase}.calendar-cell{min-height:430px;padding:8px}.calendar-item{display:grid;gap:3px;margin-bottom:7px;padding:9px;border-left:3px solid var(--primary-500);border-radius:7px;background:var(--primary-50)}.calendar-item span{color:var(--primary-700);font-size:7px;text-transform:uppercase}.calendar-item strong{font-size:9px;line-height:1.35}.calendar-item small{color:var(--muted);font-size:7px}.calendar-item--research_run{border-color:var(--blue);background:var(--blue-soft)}.calendar-item--publication,.calendar-item--metric_checkpoint{border-color:var(--green);background:var(--green-soft)}.calendar-item--generation_job{border-color:var(--amber);background:var(--amber-soft)}.calendar-add{display:grid;width:100%;height:30px;place-items:center;border:1px dashed var(--border);border-radius:7px;background:transparent;color:var(--muted)}.calendar-legend{display:flex;flex-wrap:wrap;gap:15px;margin-top:11px;color:var(--muted);font-size:8px}.calendar-legend span{display:flex;align-items:center;gap:5px}.calendar-legend i{width:7px;height:7px;border-radius:2px;background:var(--primary-500)}.calendar-legend .blue{background:var(--blue)}.calendar-legend .amber{background:var(--amber)}.calendar-legend .green{background:var(--green)}</style>
