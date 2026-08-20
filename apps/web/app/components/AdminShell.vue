<script setup lang="ts">
import { ArrowLeft, BadgeDollarSign, ChartNoAxesCombined, Gift, LogOut, Menu, Settings2, ShieldCheck, Users, X } from 'lucide-vue-next'

const route = useRoute()
const auth = useAuth()
const mobileOpen = ref(false)
const hydrated = ref(false)
onMounted(() => { hydrated.value = true })
const items = [
  { label: 'Analytics', to: '/admin', icon: ChartNoAxesCombined },
  { label: 'Users & balances', to: '/admin/users', icon: Users },
  { label: 'Promo codes', to: '/admin/promos', icon: Gift },
  { label: 'Models & pricing', to: '/admin/pricing', icon: BadgeDollarSign },
  { label: 'Administrators', to: '/admin/admins', icon: ShieldCheck },
]
function active(to: string) { return to === '/admin' ? route.path === to : route.path.startsWith(to) }
</script>

<template>
  <div class="admin-shell" :data-hydrated="hydrated">
    <button class="admin-shell__mobile" aria-label="Open admin navigation" @click="mobileOpen = true"><Menu :size="20" /></button>
    <div v-if="mobileOpen" class="admin-shell__backdrop" @click="mobileOpen = false" />
    <aside :class="{ open: mobileOpen }">
      <div class="admin-shell__brand"><span><ShieldCheck :size="20" /></span><div><strong>Framewise Admin</strong><small>Platform operations</small></div><button aria-label="Close admin navigation" @click="mobileOpen = false"><X :size="18" /></button></div>
      <nav aria-label="Platform administration">
        <NuxtLink v-for="item in items" :key="item.to" :to="item.to" :class="{ active: active(item.to) }" @click="mobileOpen = false"><component :is="item.icon" :size="18" /><span>{{ item.label }}</span></NuxtLink>
      </nav>
      <div class="admin-shell__footer">
        <NuxtLink to="/app"><ArrowLeft :size="16" /> Back to studio</NuxtLink>
        <button @click="auth.logout"><LogOut :size="16" /> Sign out</button>
      </div>
    </aside>
    <section><header><div><small>PLATFORM CONTROL</small><strong>{{ auth.user.value?.email }}</strong></div><Settings2 :size="19" /></header><main><slot /></main></section>
  </div>
</template>

<style scoped>
.admin-shell{min-height:100vh;background:#f7f6f8;color:#211927;display:grid;grid-template-columns:250px 1fr}.admin-shell aside{background:#17111d;color:#fff;display:flex;flex-direction:column;min-height:100vh;position:sticky;top:0}.admin-shell__brand{display:flex;align-items:center;gap:11px;padding:22px 18px;border-bottom:1px solid #33283a}.admin-shell__brand>span{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:#8d2e9f}.admin-shell__brand div{display:grid;gap:2px}.admin-shell__brand strong{font-size:13px}.admin-shell__brand small{font-size:9px;color:#b9acbf}.admin-shell__brand button{display:none;margin-left:auto;background:none;border:0;color:#fff}.admin-shell nav{display:grid;gap:5px;padding:18px 12px}.admin-shell nav a,.admin-shell__footer a,.admin-shell__footer button{display:flex;align-items:center;gap:10px;color:#cfc4d4;text-decoration:none;border:0;background:none;padding:11px 12px;border-radius:10px;font:inherit;font-size:11px;cursor:pointer}.admin-shell nav a.active{background:#8d2e9f;color:#fff}.admin-shell__footer{margin-top:auto;padding:14px 12px;border-top:1px solid #33283a;display:grid}.admin-shell>section{min-width:0}.admin-shell header{height:68px;background:#fff;border-bottom:1px solid #e6e0e8;display:flex;align-items:center;justify-content:space-between;padding:0 28px}.admin-shell header div{display:grid}.admin-shell header small{font-size:8px;letter-spacing:.16em;color:#8d2e9f}.admin-shell header strong{font-size:11px}.admin-shell main{padding:24px 28px 48px;max-width:1500px}.admin-shell__mobile{display:none}.admin-shell__backdrop{display:none}@media(max-width:800px){.admin-shell{display:block}.admin-shell aside{position:fixed;z-index:30;width:260px;transform:translateX(-100%);transition:.2s}.admin-shell aside.open{transform:none}.admin-shell__brand button,.admin-shell__mobile{display:grid;place-items:center}.admin-shell__mobile{position:fixed;z-index:20;top:18px;left:16px;width:34px;height:34px;border:1px solid #ddd2e0;border-radius:9px;background:#fff}.admin-shell__backdrop{display:block;position:fixed;z-index:25;inset:0;background:#130c18aa}.admin-shell header{padding-left:62px}.admin-shell main{padding:20px 14px}}
</style>
