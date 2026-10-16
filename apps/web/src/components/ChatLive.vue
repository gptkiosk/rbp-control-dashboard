<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { useLogTail } from '@/composables/useLogTail'

const props = defineProps<{
  runId: number
  stopping?: boolean
}>()

const emit = defineEmits<{ stop: []; grew: []; finished: [] }>()

const { text, done, error } = useLogTail(() => props.runId)

const scroller = ref<HTMLElement | null>(null)

watch(text, async () => {
  await nextTick()
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
  emit('grew')
})

watch(done, (d) => {
  if (d) emit('finished')
})
</script>

<template>
  <section class="live" aria-label="Agent is working" data-testid="chat-live">
    <header class="live-head">
      <span class="working has-icon-inline" role="status">
        <span class="dot" aria-hidden="true"></span>
        Working…
      </span>
      <button type="button" class="btn danger" :disabled="stopping" @click="emit('stop')">
        <AppIcon name="stop" />
        {{ stopping ? 'Stopping…' : 'Stop' }}
      </button>
    </header>
    <pre ref="scroller" class="log log-window" tabindex="0" aria-label="Live output" data-testid="chat-live-log">{{ text }}</pre>
    <p v-if="!text && !done && !error" class="muted small note">Waiting for output…</p>
    <p v-if="error" class="error-text small note" role="alert">Live output unavailable: {{ error }}</p>
  </section>
</template>

<style scoped>
.live {
  align-self: flex-start;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  width: min(100%, var(--bubble-max-width));
  padding: var(--gap-sm) var(--gap);
  border: 1px dashed var(--accent);
  border-radius: var(--radius);
  background: var(--panel);
}

.live-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
}

.working {
  color: var(--accent);
  font-weight: var(--font-weight-strong);
}

.dot {
  width: var(--busy-dot-size);
  height: var(--busy-dot-size);
  border-radius: var(--radius-pill);
  background: var(--accent);
  animation: pulse var(--pulse-duration) ease-in-out infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.25;
  }
}

@media (prefers-reduced-motion: reduce) {
  .dot {
    animation: none;
  }
}

.log {
  max-height: var(--chat-log-height);
}

.note {
  margin: 0;
}
</style>
