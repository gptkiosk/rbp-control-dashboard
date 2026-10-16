<script setup lang="ts">
import { computed } from 'vue'

// What an update is doing, step by step, and how it ended, with the log. The same layout as the MCD checkout updater.
export interface Step { name: string; state: string; detail: string }
export interface UpdateOperation {
  id: string; state: 'running' | 'staged' | 'succeeded' | 'rolled_back' | 'failed'; version: string; message: string; steps: Step[]
}
const props = defineProps<{ operation: UpdateOperation; log: string[] }>()

const STEP_TEXT: Record<string, string> = {
  fetch: 'Download the release from GitHub', verify: 'Verify the release signature', stage: 'Prepare it on this host',
  safety: 'Safety checks', snapshot: 'Back up your data', switch: 'Switch versions', health: 'Restart and check health', finish: 'Finish',
}
const running = computed(() => props.operation.state === 'running')
const title = computed(() => {
  const v = `v${props.operation.version.replace(/^v/, '')}`
  if (running.value) return `Updating to ${v}`
  if (props.operation.state === 'staged') return `${v} is staged`
  return `Update to ${v}: ${props.operation.state.replace('_', ' ')}`
})
const messageClass = computed(() => props.operation.state === 'succeeded' ? 'status' : (running.value || props.operation.state === 'staged' ? 'muted' : 'notice-warn'))
</script>
<template>
  <section class="block" aria-label="Update progress">
    <h4>{{ title }}</h4>
    <p v-if="operation.message" :class="messageClass" :role="running ? 'status' : 'alert'">{{ operation.message }}</p>
    <ol class="steps">
      <li v-for="s in operation.steps" :key="s.name" :data-state="s.state"><strong>{{ STEP_TEXT[s.name] ?? s.name }}</strong> <span class="state">{{ s.state }}</span><span v-if="s.detail" class="muted small detail">{{ s.detail }}</span></li>
    </ol>
    <details v-if="log.length">
      <summary>Log</summary>
      <pre class="notes log-window">{{ log.join('\n') }}</pre>
    </details>
  </section>
</template>
<style scoped>
h4, p { margin: 0; }
h4 { font-size: var(--font-size); font-weight: var(--font-weight-strong); }
.status { font-weight: 600; }
.small { font-size: var(--font-size-sm); }
.block { display: grid; gap: var(--gap); padding: var(--gap-lg); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--accent-soft); justify-items: start; }
.block > * { min-width: 0; max-width: 100%; }
.block p { max-width: 72ch; line-height: var(--line-height); }
.steps { list-style: decimal; display: grid; gap: var(--gap); margin: 0; padding-left: 1.5rem; line-height: var(--line-height); }
.steps li::marker { color: var(--text-muted); font-weight: var(--font-weight-strong); }
.steps .state { margin-left: var(--gap-sm); padding: 0.05rem var(--gap-sm); border-radius: var(--radius-pill); border: 1px solid var(--glass-border); font-size: var(--font-size-xs); color: var(--text-muted); text-transform: lowercase; }
.steps li[data-state='ok'] .state { color: var(--accent); border-color: var(--accent); }
.steps li[data-state='running'] .state { color: var(--text); border-color: var(--text-muted); }
.steps .detail { display: block; margin-top: var(--gap-xs); }
.steps li[data-state='failed'] { color: var(--danger, #ef4f4f); }
summary { cursor: pointer; padding: var(--gap-sm) 0; }
details { width: 100%; }
</style>
