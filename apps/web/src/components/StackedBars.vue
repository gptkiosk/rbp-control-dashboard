<script setup lang="ts">
import { computed } from 'vue'

// Horizontal bars split into named parts (for example open, done and failed), scaled to the longest row.
// The legend and the per-row numbers carry the meaning, so colour is never the only signal. Plain CSS.
const props = defineProps<{
  title: string
  parts: { key: string; label: string; color: string }[]
  rows: { label: string; values: Record<string, number>; hint?: string }[]
  empty?: string
}>()
const sum = (r: { values: Record<string, number> }) => props.parts.reduce((n, p) => n + (r.values[p.key] ?? 0), 0)
const max = computed(() => Math.max(1, ...props.rows.map(sum)))
const filled = computed(() => props.rows.filter(r => sum(r) > 0))
</script>
<template>
  <section class="card stacked" :aria-label="title">
    <h2 class="section-title">{{ title }}</h2>
    <p v-if="!filled.length" class="muted small">{{ empty ?? 'Nothing to show yet.' }}</p>
    <template v-else>
      <ul class="legend" aria-hidden="true"><li v-for="p in parts" :key="p.key"><span class="swatch" :style="{ background: p.color }"></span>{{ p.label }}</li></ul>
      <ul class="list">
        <li v-for="r in filled" :key="r.label" :title="r.hint">
          <div class="row"><span class="label">{{ r.label }}</span><span class="value">{{ parts.filter(p => r.values[p.key]).map(p => `${r.values[p.key]} ${p.label.toLowerCase()}`).join(' · ') }}</span></div>
          <div class="track" aria-hidden="true">
            <div v-for="p in parts" :key="p.key" class="seg" :title="`${p.label}: ${r.values[p.key] ?? 0}`" :style="{ width: `${((r.values[p.key] ?? 0) / max) * 100}%`, background: p.color }"></div>
          </div>
        </li>
      </ul>
    </template>
  </section>
</template>
<style scoped>
.stacked { gap: var(--gap-sm); }
h2 { margin: 0; font-size: var(--font-size); }
.small { font-size: var(--font-size-sm); margin: 0; }
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--gap); font-size: var(--font-size-sm); }
.legend li { display: flex; align-items: center; gap: var(--gap-xs); }
.swatch { width: 0.75rem; height: 0.75rem; border-radius: 2px; }
.list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--gap-sm); }
.row { display: flex; justify-content: space-between; gap: var(--gap); font-size: var(--font-size-sm); flex-wrap: wrap; }
.label { overflow-wrap: anywhere; min-width: 0; flex: 1 1 8rem; }
.value { font-variant-numeric: tabular-nums; color: var(--text-muted, inherit); white-space: nowrap; }
.track { display: flex; height: 0.6rem; border-radius: var(--radius-pill); background: var(--accent-soft); overflow: hidden; }
.seg { height: 100%; min-width: 0; }
.seg:not([style*="width: 0%"]) { min-width: 2px; }
</style>
