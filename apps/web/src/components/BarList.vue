<script setup lang="ts">
import { computed } from 'vue'

// A labelled list of horizontal bars, scaled to the largest value. Plain CSS so it stays light on a Raspberry Pi.
const props = defineProps<{ title: string; items: { label: string; value: number; note?: string }[]; empty?: string }>()
const max = computed(() => Math.max(1, ...props.items.map(i => i.value)))
</script>
<template>
  <section class="card bars" :aria-label="title">
    <h2 class="section-title">{{ title }}</h2>
    <p v-if="!items.length || items.every(i => i.value === 0)" class="muted small">{{ empty ?? 'Nothing to show yet.' }}</p>
    <ul v-else class="list">
      <li v-for="item in items" :key="item.label">
        <div class="row"><span class="label">{{ item.label }}</span><span class="value">{{ item.value }}<span v-if="item.note" class="muted small"> {{ item.note }}</span></span></div>
        <div class="track" aria-hidden="true"><div class="fill" :style="{ width: `${(item.value / max) * 100}%` }"></div></div>
      </li>
    </ul>
  </section>
</template>
<style scoped>
.bars { gap: var(--gap-sm); }
h2 { margin: 0; font-size: var(--font-size); }
.small { font-size: var(--font-size-sm); margin: 0; }
.list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--gap-sm); }
.row { display: flex; justify-content: space-between; gap: var(--gap); font-size: var(--font-size-sm); }
.label { overflow-wrap: anywhere; }
.value { font-variant-numeric: tabular-nums; white-space: nowrap; }
.value .muted { margin-left: var(--gap-sm); }
.track { height: 0.5rem; border-radius: var(--radius-pill); background: var(--accent-soft); overflow: hidden; }
.fill { height: 100%; background: var(--accent); border-radius: var(--radius-pill); min-width: 2px; }
</style>
