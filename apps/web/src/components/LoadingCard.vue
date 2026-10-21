<script setup lang="ts">
// What the page is doing while something loads: a short sentence, a quiet animated skeleton of what is coming, and, after a few seconds,
// a note that it is still working so a slow host does not look frozen. Motion stops when the visitor prefers reduced motion.
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{ title: string; detail?: string; slowAfterMs?: number; slowText?: string; rows?: number }>(),
  { detail: '', slowAfterMs: 4000, slowText: 'Still working. This host can take a few seconds to answer.', rows: 3 })
const slow = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
onMounted(() => { timer = setTimeout(() => { slow.value = true }, props.slowAfterMs) })
onBeforeUnmount(() => clearTimeout(timer))
</script>
<template>
  <div class="card loading-card" role="status" aria-live="polite" aria-busy="true" data-testid="loading-card">
    <div class="head">
      <span class="pulse" aria-hidden="true"><i /><i /><i /></span>
      <div><strong>{{ title }}</strong><p v-if="detail" class="muted small">{{ detail }}</p></div>
    </div>
    <div class="skeleton" aria-hidden="true">
      <span class="bar wide" />
      <span v-for="n in rows" :key="n" class="bar" :style="{ width: `${92 - n * 14}%` }" />
    </div>
    <p v-if="slow" class="muted small" data-testid="loading-slow">{{ slowText }}</p>
  </div>
</template>
<style scoped>
.loading-card { display: grid; gap: var(--gap); }
.head { display: flex; align-items: center; gap: var(--gap-sm); }
.head p { margin: var(--gap-xs) 0 0; }
.pulse { display: inline-flex; gap: 0.3rem; }
.pulse i { width: 0.55rem; height: 0.55rem; border-radius: 50%; background: var(--accent); opacity: 0.35; animation: beat 1.2s ease-in-out infinite; }
.pulse i:nth-child(2) { animation-delay: 0.2s; }
.pulse i:nth-child(3) { animation-delay: 0.4s; }
@keyframes beat { 0%, 100% { opacity: 0.35; transform: scale(0.85); } 50% { opacity: 1; transform: scale(1); } }
.skeleton { display: grid; gap: var(--gap-sm); }
.bar { display: block; height: 0.8rem; border-radius: var(--radius-pill); background: linear-gradient(90deg, var(--surface-border) 0%, var(--accent-soft) 50%, var(--surface-border) 100%); background-size: 200% 100%; animation: sheen 1.6s linear infinite; }
.bar.wide { height: 1.4rem; width: 60%; }
@keyframes sheen { from { background-position: 200% 0; } to { background-position: -200% 0; } }
.small { font-size: var(--font-size-xs); }
@media (prefers-reduced-motion: reduce) { .pulse i, .bar { animation: none; } .pulse i { opacity: 0.7; } }
</style>
