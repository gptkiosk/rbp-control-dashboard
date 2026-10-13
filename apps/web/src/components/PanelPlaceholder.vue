<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import type { IconName } from '@/icons/icons'

defineProps<{
  title: string
  icon?: IconName
  description: string
  phase: string
}>()
</script>

<template>
  <section class="card panel" aria-labelledby="panel-title">
    <h1 id="panel-title" class="panel-title" :class="{ 'has-icon': icon }">
      <AppIcon v-if="icon" :name="icon" size="lg" />
      {{ title }}
    </h1>
    <p class="panel-description">{{ description }}</p>
    <span class="phase-chip" data-testid="phase-chip">Coming in Phase {{ phase }}</span>
  </section>
</template>

<style scoped>
.panel {
  padding: var(--gap-lg);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--gap);
}

.panel-title {
  margin: 0;
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-strong);
}

.panel-description {
  margin: 0;
  color: var(--text-muted);
  max-width: 60ch;
}

.phase-chip {
  display: inline-block;
  padding: var(--gap-xs) var(--gap-sm);
  border-radius: var(--radius-pill);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-strong);
}
</style>
