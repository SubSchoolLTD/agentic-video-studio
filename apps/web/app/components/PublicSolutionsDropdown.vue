<script setup lang="ts">
import { ChevronDown } from 'lucide-vue-next'

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const items = [
  { to: '/solutions/studios-media-teams', title: 'Studios & media teams', text: 'Always-on campaigns for films, series and media properties.' },
  { to: '/solutions/creators-experts', title: 'Creators & experts', text: 'Turn expertise into a useful, consistent video channel.' },
  { to: '/solutions/small-businesses', title: 'Small businesses', text: 'Keep marketing visible without building a content department.' },
  { to: '/solutions/education-teams', title: 'Education teams', text: 'Transform learning material into short-form educational video.' },
]

function closeOnOutsideClick(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', closeOnOutsideClick))
onBeforeUnmount(() => document.removeEventListener('click', closeOnOutsideClick))
</script>

<template>
  <div ref="root" class="solutions-dropdown">
    <button type="button" aria-label="Solutions menu" :aria-expanded="open" @click="open = !open">
      Solutions <ChevronDown :size="13" :class="{ rotated: open }" />
    </button>
    <div v-if="open" class="solutions-dropdown__panel" role="menu">
      <span>Solutions by audience</span>
      <NuxtLink v-for="item in items" :key="item.to" :to="item.to" role="menuitem" @click="open = false">
        <strong>{{ item.title }}</strong>
        <small>{{ item.text }}</small>
      </NuxtLink>
    </div>
  </div>
</template>

<style scoped>
.solutions-dropdown{position:relative}.solutions-dropdown>button{display:flex;align-items:center;gap:5px;border:0;background:transparent;color:#5d5762;font:inherit;font-size:inherit;font-weight:inherit;cursor:pointer}.solutions-dropdown>button:hover,.solutions-dropdown>button[aria-expanded=true]{color:#78258b}.solutions-dropdown svg{transition:transform .18s}.solutions-dropdown svg.rotated{transform:rotate(180deg)}.solutions-dropdown__panel{position:absolute;z-index:120;top:calc(100% + 22px);left:50%;display:grid;width:390px;padding:10px;border:1px solid #e6dfe8;border-radius:15px;background:#fff;box-shadow:0 24px 65px rgb(42 24 47/16%);transform:translateX(-50%)}.solutions-dropdown__panel::before{position:absolute;top:-7px;left:50%;width:12px;height:12px;border-top:1px solid #e6dfe8;border-left:1px solid #e6dfe8;background:#fff;content:'';transform:translateX(-50%) rotate(45deg)}.solutions-dropdown__panel>span{padding:8px 10px 7px;color:#958b99;font-size:8px;font-weight:900;text-transform:uppercase;letter-spacing:.15em}.solutions-dropdown__panel>a{display:grid;gap:3px;padding:11px 12px;border-radius:9px;color:#211927;text-decoration:none}.solutions-dropdown__panel>a:hover{background:#f8f1fa}.solutions-dropdown__panel strong{font-size:11px}.solutions-dropdown__panel small{color:#756d79;font-size:9px;font-weight:500;line-height:1.45}
</style>
