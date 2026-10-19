<script setup lang="ts">
// The header of a panel on the Settings page: title, an optional status pill, and a How-to link. The same look as the cards on Updates & installs.
defineProps<{ id: string; title: string; status?: string; tone?: 'ok' | 'warn' | 'muted'; help?: string }>()
</script>
<template>
  <header class="panel-head">
    <h2 :id="id" class="section-title">{{ title }}</h2>
    <span v-if="status" class="pill" :class="tone ?? 'muted'" data-test="status">{{ status }}</span>
    <RouterLink v-if="help" :to="`/help?topic=${help}`" class="howto small">How-to</RouterLink>
  </header>
</template>
<style scoped>
.panel-head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--gap-sm); }
.panel-head h2 { flex: 1 1 auto; min-width: 0; margin: 0; }
.pill { padding: 0 var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius-pill); font-size: var(--font-size-xs); color: var(--text-muted); white-space: nowrap; }
.pill.ok { color: var(--ok); border-color: var(--ok); background: var(--ok-soft); }
.pill.warn { color: var(--warn); border-color: var(--warn); }
.howto { white-space: nowrap; }
.small { font-size: var(--font-size-xs); }
</style>
