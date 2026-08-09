<script setup lang="ts">
const props = withDefaults(defineProps<{
  value: number
  label: string
  suffix?: string
  size?: 'small' | 'large'
}>(), {
  suffix: '',
  size: 'small',
})
const bounded = computed(() => Math.min(100, Math.max(0, props.value)))
</script>

<template>
  <div class="score-ring" :class="`score-ring--${size}`" :style="{ '--score': `${bounded * 3.6}deg` }">
    <div class="score-ring__inner">
      <strong>{{ value }}{{ suffix }}</strong>
      <span>{{ label }}</span>
    </div>
  </div>
</template>

