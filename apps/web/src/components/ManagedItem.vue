<script setup lang="ts">
// One installable or updatable thing, in the same card the setup checklist uses: status, version, the action buttons (default slot),
// a progress bar while it works, its log, and a health check with next steps. Presentational only: the parent owns every request.
export interface Health { ok: boolean; version?: string | null; next: string[] }
withDefaults(defineProps<{
  name: string
  mark: 'ok' | 'warn' | 'missing' | 'info'
  word: string
  tag?: string                     // a small label next to the name, such as Required or Optional
  version?: string | null          // what is installed
  latest?: string | null           // what could be installed; shown as "x → y" when it differs
  detail?: string
  busy?: boolean
  progress?: string
  log?: string[]
  logTitle?: string
  health?: Health | null
  healthBusy?: boolean
  healthDisabled?: boolean
}>(), { tag: '', version: null, latest: null, detail: '', busy: false, progress: '', log: () => [], logTitle: 'Log', health: null, healthBusy: false, healthDisabled: false })
defineEmits<{ health: [] }>()
const marks = { ok: '✓', warn: '!', missing: '✗', info: 'i' }
</script>
<template>
  <li class="item" :class="[`s-${mark}`, { working: busy }]">
    <div class="title">
      <span class="mark" aria-hidden="true">{{ marks[mark] }}</span>
      <strong>{{ name }}</strong>
      <span v-if="tag" class="tag small" data-test="tag">{{ tag }}</span>
      <span v-if="version || latest" class="ver" data-test="version">
        <template v-if="version && latest && version !== latest">{{ version }} → {{ latest }}</template>
        <template v-else>{{ version ?? latest }}</template>
      </span>
      <span class="state small" data-test="word">{{ word }}</span>
    </div>
    <p v-if="detail" class="detail small" data-test="state">{{ detail }}</p>
    <div class="actions"><slot /></div>
    <div v-if="busy" class="bar" role="progressbar" :aria-label="progress || `${name} is working`" aria-busy="true"><span /></div>
    <p v-if="progress" class="small status" role="status" data-test="progress">{{ progress }}</p>
    <details v-if="log.length" class="logbox" :open="busy">
      <summary class="small">{{ logTitle }} ({{ log.length }} lines)</summary>
      <pre class="log small" tabindex="0">{{ log.join('\n') }}</pre>
    </details>
    <div v-if="health || healthBusy" class="health" :class="health && !health.ok ? 'bad' : 'good'" data-test="health" aria-live="polite">
      <p class="small">
        <strong>Health check</strong>
        <span v-if="healthBusy" class="res">checking…</span>
        <span v-else-if="health" class="res">{{ health.ok ? '✓ passed' : '! needs attention' }}<template v-if="health.version"> · {{ health.version }}</template></span>
      </p>
      <ul v-if="health && health.next.length" class="next small"><li v-for="n in health.next" :key="n">{{ n }}</li></ul>
    </div>
    <div v-if="!healthDisabled || $slots.more" class="actions foot">
      <button v-if="!healthDisabled" type="button" class="btn small-btn" data-action="health" :disabled="healthBusy || busy" @click="$emit('health')">Check health</button>
      <slot name="more" />
    </div>
  </li>
</template>
<style scoped>
.item { display: grid; gap: var(--gap-sm); align-content: start; padding: var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--panel); min-width: 0; list-style: none; }
.item.working { border-color: var(--accent); }
.title { display: flex; align-items: center; flex-wrap: wrap; gap: var(--gap-sm); }
.title strong { flex: 1 1 auto; min-width: 0; }
.mark { display: inline-grid; place-items: center; width: 1.5rem; height: 1.5rem; border-radius: 50%; font-size: var(--font-size-sm); font-weight: var(--font-weight-strong); border: 1px solid var(--surface-border); flex: none; }
.s-ok .mark { color: var(--ok); background: var(--ok-soft); border-color: var(--ok); }
.s-missing .mark { color: var(--danger); background: var(--danger-soft); border-color: var(--danger); }
.s-warn .mark { color: var(--warn); border-color: var(--warn); }
.tag { padding: 0 var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius-pill); color: var(--text-muted); }
.ver { font-family: var(--font-mono, ui-monospace, monospace); font-size: var(--font-size-sm); padding: 0 var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius-pill); }
.state { color: var(--text-muted); white-space: nowrap; }
.small { font-size: var(--font-size-xs); margin: 0; }
.detail { color: var(--text-muted); overflow-wrap: anywhere; margin: 0; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-sm); }
.actions:empty { display: none; }
.actions .btn { width: auto; flex: none; }
.small-btn { padding: 0 var(--gap-sm); }
.status { font-weight: 600; }
.bar { height: 0.35rem; border-radius: var(--radius-pill); background: var(--surface-border); overflow: hidden; }
.bar span { display: block; height: 100%; width: 40%; border-radius: inherit; background: var(--accent); animation: slide 1.4s ease-in-out infinite; }
@keyframes slide { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
@media (prefers-reduced-motion: reduce) { .bar span { animation: none; width: 100%; opacity: 0.6; } }
.logbox summary { cursor: pointer; color: var(--text-muted); }
.log { margin: var(--gap-xs) 0 0; max-height: 12rem; overflow: auto; padding: var(--gap-xs) var(--gap-sm); background: var(--bg); border-radius: var(--radius-sm); font-family: var(--font-mono, ui-monospace, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.health { display: grid; gap: var(--gap-xs); padding: var(--gap-xs) var(--gap-sm); border-radius: var(--radius-sm); border: 1px solid var(--surface-border); }
.health.good { border-color: var(--ok); }
.health.bad { border-color: var(--warn); }
.health p { margin: 0; }
.res { margin-left: var(--gap-xs); }
.next { margin: 0; padding-left: 1.2rem; display: grid; gap: var(--gap-xs); }
.foot { padding-top: var(--gap-xs); border-top: 1px solid var(--surface-border); }
</style>
