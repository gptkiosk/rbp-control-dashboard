<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useLogTail } from '@/composables/useLogTail'

const props = defineProps<{ runId: number }>()

const { text, done, error } = useLogTail(() => props.runId)

/** How close to the bottom (px) still counts as "following" the log. */
const FOLLOW_SLACK_PX = 24

const scroller = ref<HTMLElement | null>(null)
const following = ref(true)

function onScroll(): void {
  const el = scroller.value
  if (!el) return
  following.value = el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_SLACK_PX
}

function toBottom(): void {
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
  following.value = true
}

watch(text, async () => {
  if (!following.value) return
  await nextTick()
  toBottom()
})
</script>

<template>
  <div class="run-log">
    <pre
      ref="scroller"
      class="log log-window"
      tabindex="0"
      aria-label="Run log"
      data-testid="run-log"
      @scroll="onScroll"
    >{{ text }}</pre>
    <p v-if="!text && !done && !error" class="muted small" role="status">Waiting for output…</p>
    <p v-else-if="!text && done" class="muted small">The log is empty.</p>
    <p v-if="error" class="error-text small" role="alert">Log unavailable: {{ error }}</p>
    <button v-if="!following" type="button" class="btn jump" @click="toBottom">Jump to latest</button>
  </div>
</template>

<style scoped>
.run-log {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  align-items: flex-start;
}

.run-log p {
  margin: 0;
}

.log {
  height: var(--log-height);
  max-height: none;
}
</style>
