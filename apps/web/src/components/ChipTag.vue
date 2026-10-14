<script setup lang="ts">
withDefaults(defineProps<{ tone?: 'ok' | 'warn' | 'danger' | 'muted' | 'accent' }>(), {
  tone: 'muted',
})
</script>

<template>
  <span class="chip" :data-tone="tone"><slot /></span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--icon-gap);
  padding: var(--gap-xs) var(--gap-sm);
  border-radius: var(--radius-pill);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-strong);
  line-height: 1.2;
  white-space: nowrap;
  background: var(--panel-raised);
  color: var(--text-muted);
}

.chip[data-tone='ok'] {
  background: var(--ok-soft);
  color: var(--ok);
}

.chip[data-tone='warn'] {
  background: var(--warn-soft);
  color: var(--warn);
}

.chip[data-tone='danger'] {
  background: var(--danger-soft);
  color: var(--danger);
}

.chip[data-tone='accent'] {
  background: var(--accent-soft);
  color: var(--accent);
}
</style>
