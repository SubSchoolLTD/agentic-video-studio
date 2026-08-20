<script setup lang="ts">
import { CircleHelp } from 'lucide-vue-next'

defineProps<{ text: string }>()
</script>

<template>
  <span class="setting-help" tabindex="0" :aria-label="text">
    <CircleHelp :size="13" aria-hidden="true" />
    <span role="tooltip">{{ text }}</span>
  </span>
</template>

<style scoped>
.setting-help{position:relative;display:inline-grid;margin-left:4px;vertical-align:-2px;color:var(--muted);cursor:help;outline:none}.setting-help>span{position:absolute;z-index:20;bottom:calc(100% + 8px);left:50%;width:230px;padding:9px 10px;border:1px solid var(--border);border-radius:8px;background:#211827;color:#fff;box-shadow:0 12px 30px rgb(24 15 29 / 20%);font-size:8px;font-weight:500;line-height:1.5;text-align:left;text-transform:none;transform:translate(-50%,4px);visibility:hidden;opacity:0;pointer-events:none;transition:.14s ease}.setting-help:hover>span,.setting-help:focus>span{visibility:visible;opacity:1;transform:translate(-50%,0)}
</style>
