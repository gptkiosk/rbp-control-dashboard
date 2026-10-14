<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ChipTag from '@/components/ChipTag.vue'
import TaskApprovalAction from '@/components/TaskApprovalAction.vue'
import { useNow } from '@/composables/useNow'
import type { Card } from '@/lib/api'
import { agentLabel, awaitsApproval, isManagerAgent, stageLabel, stageTone } from '@/lib/cards'
import { formatDuration } from '@/lib/format'

const props = defineProps<{ card: Card; selected?: boolean; dragging?: boolean }>()
const emit = defineEmits<{ open: [id: number]; dragstart: [event: DragEvent, card: Card]; dragend: []; changed: [] }>()

const now = useNow()

const running = computed(() => props.card.column === 'running')
const run = computed(() => props.card.last_run)

const elapsed = computed(() => {
  const r = run.value
  if (!r || r.stage !== 'running') return null
  return formatDuration(Math.floor(Math.max(0, now.value - r.started_at)))
})
</script>

<template>
  <article
    class="card-tile"
    :data-card-id="card.id"
    :data-dragging="dragging ? 'true' : undefined"
    :data-selected="selected ? 'true' : undefined"
    :draggable="!running"
    @click="emit('open', card.id)"
    @dragstart="emit('dragstart', $event, card)"
    @dragend="emit('dragend')"
  >
    <h3 class="title">
      <button type="button" class="open" :aria-label="`Open card: ${card.title}`">{{ card.title }}</button>
    </h3>
    <div class="chips">
      <ChipTag tone="accent">{{ agentLabel(card.agent) }}</ChipTag>
      <ChipTag v-if="isManagerAgent(card.agent)" tone="muted">Manager</ChipTag>
      <ChipTag :tone="card.mode === 'edit' ? 'warn' : 'muted'">{{ card.mode === 'edit' ? 'Edit' : 'Read' }}</ChipTag>
      <ChipTag v-if="awaitsApproval(card)" tone="warn">Needs approval</ChipTag>
      <ChipTag v-else-if="card.approved_at" tone="ok">Approved</ChipTag>
    </div>
    <p class="model muted small">
      <span class="sr-only">Model: </span>{{ card.model ?? 'default' }}
      <template v-if="card.agent_target"> · {{ card.agent_target }}</template>
    </p>
    <p v-if="run" class="run small">
      <ChipTag :tone="stageTone(run.stage)">{{ stageLabel(run.stage) }}</ChipTag>
      <span v-if="elapsed" class="timer" data-testid="elapsed">{{ elapsed }}</span>
      <span v-else-if="run.duration_s != null" class="muted has-icon-inline">
        <AppIcon name="clock" size="sm" />
        {{ formatDuration(run.duration_s) }}
      </span>
    </p>
    <TaskApprovalAction :card="card" @changed="emit('changed')" />
  </article>
</template>

<style scoped>
.card-tile {
  position: relative;
  background: var(--panel-raised);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  padding: var(--gap-sm) var(--gap);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  min-width: 0;
  cursor: pointer;
}

.card-tile[draggable='true'] {
  cursor: grab;
}

.card-tile:hover,
.card-tile[data-selected='true'] {
  border-color: var(--accent);
}

.card-tile[data-dragging='true'] {
  opacity: var(--drag-opacity);
}

.title {
  margin: 0;
  font-size: var(--font-size);
  font-weight: var(--font-weight-strong);
}

.open {
  all: unset;
  display: block;
  width: 100%;
  cursor: inherit;
  overflow-wrap: anywhere;
  border-radius: var(--radius-sm);
}

.open:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
}

.model,
.run {
  margin: 0;
  overflow-wrap: anywhere;
}

.run {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.timer {
  font-variant-numeric: tabular-nums;
  color: var(--accent);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
