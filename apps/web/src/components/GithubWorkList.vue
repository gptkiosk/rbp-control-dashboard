<script setup lang="ts">
import { dateLabel, type GithubStream } from '@/lib/operations'
defineProps<{ title: string; stream: GithubStream }>()
</script>
<template>
  <section class="card work-list">
    <header><h2>{{ title }}</h2><span class="muted">{{ stream.items ? stream.items.length : '—' }} open{{ stream.limited ? '+' : '' }}</span></header>
    <p v-if="stream.error" role="status" class="notice-warn">{{ stream.error }} {{ stream.checked_at ? 'Showing the last successful result.' : '' }}</p>
    <p class="muted checked">Last successful check: {{ dateLabel(stream.checked_at) }}</p>
    <ul v-if="stream.items?.length">
      <li v-for="item in stream.items" :key="item.number">
        <a :href="item.url" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer"><span class="muted">#{{ item.number }}</span> {{ item.title }}</a>
        <small class="muted">{{ item.user }} · {{ dateLabel(item.updated_at) }}<span v-if="item.draft"> · Draft</span></small>
        <div v-if="item.labels.length" class="labels"><span v-for="label in item.labels" :key="label" class="tag">{{ label }}</span></div>
      </li>
    </ul>
    <p v-else-if="stream.items" class="muted">No open {{ title.toLowerCase() }}.</p>
    <p v-else class="muted">No result available yet.</p>
    <p v-if="stream.limited" class="muted">This list is capped at 50 items; additional items may be available on GitHub.</p>
  </section>
</template>
<style scoped>
.work-list { min-width: 0; }
header { display: flex; gap: var(--gap); align-items: baseline; justify-content: space-between; }
h2 { font-size: var(--font-size-lg); margin: 0; }
.checked { font-size: var(--font-size-xs); }
ul { list-style: none; padding: 0; margin: 0; }
li { border-top: 1px solid var(--surface-border); padding: var(--gap) 0; overflow-wrap: anywhere; }
a:hover { color: var(--accent); text-decoration: underline; }
a { display: block; line-height: 1.5; }
small { display: block; margin-top: var(--gap-xs); }
.labels { display: flex; flex-wrap: wrap; gap: var(--gap-xs); margin-top: var(--gap-sm); }
.tag { border: 1px solid var(--select-border); background: var(--accent-soft); border-radius: var(--radius-sm); padding: 2px 8px; font-size: var(--font-size-xs); }
</style>
