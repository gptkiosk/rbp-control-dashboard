<script setup lang="ts">
// Explanations that matter but should not crowd the controls: one quiet line until opened. The full text stays in the page for screen readers.
withDefaults(defineProps<{ label?: string }>(), { label: 'Notes' })
</script>
<template>
  <details class="note-fold">
    <summary class="small muted">{{ label }}</summary>
    <div class="body"><slot /></div>
  </details>
</template>
<style scoped>
.note-fold { min-width: 0; }
.note-fold summary { cursor: pointer; width: fit-content; }
.note-fold summary:hover { color: var(--text); }
.body { display: grid; gap: var(--gap-xs); padding-top: var(--gap-xs); }
.body :deep(p) { margin: 0; }
.small { font-size: var(--font-size-xs); }
</style>
