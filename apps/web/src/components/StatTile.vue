<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import type { IconName } from '@/icons/icons'

defineProps<{
  label: string
  icon?: IconName
  value: string
  sub?: string
  /** 0-100: draws a thin meter under the value. */
  meter?: number | null
}>()
</script>

<template>
  <article class="card tile">
    <h2 class="label" :class="{ 'has-icon': icon }">
      <AppIcon v-if="icon" :name="icon" />
      {{ label }}
    </h2>
    <p class="value">{{ value }}</p>
    <div v-if="meter != null" class="meter" aria-hidden="true">
      <div class="fill" :style="{ width: `${Math.min(100, Math.max(0, meter))}%` }"></div>
    </div>
    <p class="sub"><slot name="sub">{{ sub }}</slot></p>
  </article>
</template>

<style scoped>
.tile {
  gap: var(--gap-xs);
}

.label {
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight);
  color: var(--text-muted);
}

.value {
  margin: 0;
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-strong);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.meter {
  height: var(--meter-height);
  border-radius: var(--radius-pill);
  background: var(--panel-raised);
  overflow: hidden;
}

.fill {
  height: 100%;
  background: var(--accent);
}

.sub {
  margin: 0;
  min-height: 1.5em;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--font-size-sm);
  color: var(--text-muted);
}
</style>
