<script setup lang="ts">
import {
  BarChart3,
  BadgeDollarSign,
  Blocks,
  Braces,
  CalendarDays,
  ChevronDown,
  Clapperboard,
  Compass,
  FileStack,
  Gauge,
  Library,
  Link2,
  Menu,
  LogOut,
  PanelLeftClose,
  Plus,
  RadioTower,
  Search,
  Settings,
  Sparkles,
  ShieldCheck,
  X,
} from 'lucide-vue-next'

const route = useRoute()
const { api, projectId } = useApi()
const auth = useAuth()
const mobileOpen = ref(false)
const collapsed = useState('sidebar-collapsed', () => false)
const hydrated = ref(false)

onMounted(() => { hydrated.value = true })

const baseNav = [
  { label: 'Overview', to: '/', icon: Gauge },
  { label: 'Sources', to: '/sources', icon: FileStack },
  { label: 'Research', to: '/research', icon: RadioTower, badge: '3' },
  { label: 'Ideas', to: '/ideas', icon: Sparkles, badge: '7' },
  { label: 'Calendar', to: '/calendar', icon: CalendarDays },
  { label: 'Productions', to: '/productions', icon: Clapperboard },
  { label: 'Library', to: '/library', icon: Library },
  { label: 'Publishing', to: '/publishing', icon: Compass },
  { label: 'Analytics', to: '/analytics', icon: BarChart3 },
  { label: 'Strategy', to: '/strategy', icon: Blocks },
  { label: 'Connections', to: '/connections', icon: Link2 },
  { label: 'Developer', to: '/developer', icon: Braces },
  { label: 'Project settings', to: '/settings', icon: Settings },
  { label: 'Billing & AI tokens', to: '/billing', icon: BadgeDollarSign },
]
const nav = computed(() => auth.user.value?.is_platform_admin
  ? [...baseNav, { label: 'Platform admin', to: '/admin', icon: ShieldCheck }]
  : baseNav)

const { data: projects } = await useAsyncData('shell-projects', () => api<any>('/v1/projects'), {
  default: () => ({ items: [] }),
})
const { data: health } = await useAsyncData('shell-health', () => api<any>('/v1/health'), {
  default: () => ({ status: 'unknown', environment: 'unknown', provider_mode: 'unknown' }),
})
const activeProject = computed(() => projects.value?.items?.find((item: any) => item.id === projectId.value) || projects.value?.items?.[0])
const initials = computed(() => (auth.user.value?.display_name || auth.user.value?.email || 'U').split(/\s+/).map(part => part[0]).join('').slice(0, 2).toUpperCase())
const projectInitials = computed(() => (activeProject.value?.name || 'Project').split(/\s+/).map((part: string) => part[0]).join('').slice(0, 2).toUpperCase())
const healthTitle = computed(() => health.value?.status === 'ok' ? 'Systems operational' : 'System status unknown')
const healthDetail = computed(() => {
  const provider = health.value?.provider_mode === 'live' ? 'Live providers' : health.value?.provider_mode === 'mock' ? 'Mock providers' : 'Providers unknown'
  return `${provider} · ${health.value?.environment || 'unknown'}`
})

function isActive(to: string) {
  if (to === '/') return route.path === '/'
  return route.path === to || route.path.startsWith(`${to}/`)
}

function switchProject(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (!value) return
  projectId.value = value
  const cookie = useCookie<string | null>('avs_project', { sameSite: 'lax', secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 365 })
  cookie.value = value
  void navigateTo('/')
}
</script>

<template>
  <div class="app-shell" :class="{ 'app-shell--collapsed': collapsed }" :data-hydrated="hydrated">
    <div v-if="mobileOpen" class="mobile-backdrop" @click="mobileOpen = false" />
    <aside class="sidebar" :class="{ 'sidebar--mobile-open': mobileOpen }">
      <div class="brand-lockup">
        <div class="brand-lockup__mark"><Clapperboard :size="21" /></div>
        <div class="brand-lockup__copy">
          <strong>Framewise</strong>
          <span>Agentic studio</span>
        </div>
        <button class="icon-button sidebar__mobile-close" aria-label="Close menu" @click="mobileOpen = false"><X :size="18" /></button>
      </div>

      <div class="project-switcher">
        <span class="project-switcher__avatar">{{ projectInitials }}</span>
        <span class="project-switcher__copy">
          <strong>{{ activeProject?.name || 'Create a project' }}</strong>
          <small>{{ activeProject?.status || 'Workspace' }} · {{ auth.user.value?.role || 'member' }}</small>
        </span>
        <ChevronDown :size="15" />
        <select :value="projectId" aria-label="Switch project" @change="switchProject"><option v-for="project in projects?.items || []" :key="project.id" :value="project.id">{{ project.name }}</option></select>
      </div>

      <nav class="sidebar__nav" aria-label="Project navigation">
        <NuxtLink
          v-for="item in nav"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ 'nav-link--active': isActive(item.to) }"
          :title="collapsed ? item.label : undefined"
          @click="mobileOpen = false"
        >
          <component :is="item.icon" :size="18" />
          <span class="nav-link__label">{{ item.label }}</span>
          <span v-if="item.badge" class="nav-link__badge">{{ item.badge }}</span>
        </NuxtLink>
      </nav>

      <div class="sidebar__footer">
        <div class="system-health">
          <span class="system-health__pulse" />
          <div><strong>{{ healthTitle }}</strong><span>{{ healthDetail }}</span></div>
        </div>
        <button class="sidebar-collapse" :aria-label="collapsed ? 'Expand sidebar' : 'Collapse sidebar'" @click="collapsed = !collapsed">
          <PanelLeftClose :size="17" />
          <span>Collapse</span>
        </button>
      </div>
    </aside>

    <div class="app-shell__main">
      <header class="topbar">
        <button class="icon-button topbar__menu" aria-label="Open menu" @click="mobileOpen = true"><Menu :size="20" /></button>
        <div class="topbar__search"><Search :size="17" /><span>Search productions, ideas, sources…</span><kbd>⌘ K</kbd></div>
        <div class="topbar__actions">
          <NuxtLink to="/ideas?create=1" class="button button--primary button--small"><Plus :size="16" /> New idea</NuxtLink>
          <button class="avatar-button" :title="`Sign out ${auth.user.value?.email || ''}`" aria-label="Sign out" @click="auth.logout"><span>{{ initials }}</span><LogOut :size="13" /></button>
        </div>
      </header>
      <main class="page-container">
        <slot />
      </main>
    </div>
  </div>
</template>
