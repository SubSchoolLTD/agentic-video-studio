<script setup lang="ts">
import { CheckCircle2, CircleAlert, Info, X } from 'lucide-vue-next'

const { messages, dismiss } = useToast()
const icons = { success: CheckCircle2, error: CircleAlert, info: Info }
</script>

<template>
  <div class="toast-host" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="toast in messages" :key="toast.id" class="toast" :class="`toast--${toast.tone}`">
        <component :is="icons[toast.tone]" :size="19" />
        <div class="toast__copy">
          <strong>{{ toast.title }}</strong>
          <span v-if="toast.message">{{ toast.message }}</span>
        </div>
        <button class="icon-button icon-button--plain" aria-label="Dismiss notification" @click="dismiss(toast.id)">
          <X :size="16" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

