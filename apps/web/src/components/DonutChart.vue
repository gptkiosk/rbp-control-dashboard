<script setup lang="ts">
import { computed } from 'vue'

// A donut with a legend that carries the numbers, so colour is never the only signal. Plain SVG, no chart library.
const props = defineProps<{ title: string; slices: { label: string; value: number; color?: string }[]; empty?: string }>()
const COLORS = ['var(--accent)', 'var(--ok)', 'var(--warn)', 'var(--danger)', 'var(--text-muted, #8b949e)', 'var(--accent-soft)']
const R = 15.9155   // circumference 100, so a slice's dash length is its percentage
const shown = computed(() => props.slices.filter(s => s.value > 0))
const total = computed(() => shown.value.reduce((n, s) => n + s.value, 0))
const arcs = computed(() => {
  let offset = 0
  return shown.value.map((s, i) => {
    const pct = (s.value / total.value) * 100
    const arc = { ...s, color: s.color ?? COLORS[i % COLORS.length]!, pct, dash: `${pct} ${100 - pct}`, offset: -offset }
    offset += pct
    return arc
  })
})
</script>
<template>
  <section class="card donut" :aria-label="title">
    <h2 class="section-title">{{ title }}</h2>
    <p v-if="!total" class="muted small">{{ empty ?? 'Nothing to show yet.' }}</p>
    <div v-else class="body">
      <svg viewBox="0 0 42 42" role="img" :aria-label="`${title}: ${shown.map(s => `${s.label} ${s.value}`).join(', ')}`">
        <circle class="ring" cx="21" cy="21" :r="R" fill="none" stroke-width="5.5" />
        <circle v-for="a in arcs" :key="a.label" cx="21" cy="21" :r="R" fill="none" stroke-width="5.5" :stroke="a.color" :stroke-dasharray="a.dash" :stroke-dashoffset="a.offset" transform="rotate(-90 21 21)" />
        <text x="21" y="22.5" text-anchor="middle" class="total">{{ total }}</text>
      </svg>
      <ul class="legend">
        <li v-for="a in arcs" :key="a.label" :title="`${a.label}: ${a.value} (${Math.round(a.pct)}%)`"><span class="swatch" :style="{ background: a.color }" aria-hidden="true"></span><span class="name">{{ a.label }}</span><span class="num">{{ a.value }} · {{ Math.round(a.pct) }}%</span></li>
      </ul>
    </div>
  </section>
</template>
<style scoped>
.donut { gap: var(--gap-sm); }
h2 { margin: 0; font-size: var(--font-size); }
.small { font-size: var(--font-size-sm); margin: 0; }
.body { display: flex; flex-direction: row; flex-wrap: wrap; align-items: center; gap: var(--gap); }
svg { width: 8.5rem; height: 8.5rem; flex: none; }
.ring { stroke: var(--accent-soft); }
.total { font-size: 7px; font-weight: 600; fill: currentColor; font-variant-numeric: tabular-nums; }
.legend { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--gap-xs); font-size: var(--font-size-sm); flex: 1; min-width: 9rem; }
.legend li { display: flex; align-items: center; gap: var(--gap-sm); }
.swatch { width: 0.75rem; height: 0.75rem; border-radius: 2px; flex: none; }
.name { flex: 1; overflow-wrap: anywhere; }
.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
