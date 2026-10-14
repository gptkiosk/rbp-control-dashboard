<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ChipTag from '@/components/ChipTag.vue'
import TagPill from '@/components/TagPill.vue'
import TaskApprovalAction from '@/components/TaskApprovalAction.vue'
import { useNow } from '@/composables/useNow'
import type { Card } from '@/lib/api'
import {
  agentLabel,
  canDrag,
  idList,
  isBlocked,
  isHuman,
  isOverdue,
  priorityLabel,
  stageLabel,
  stageTone,
  todayIso,
} from '@/lib/cards'
import { DASH, formatDueDate, formatDuration, formatEstimate, formatModelShort } from '@/lib/format'

const props = defineProps<{
  card: Card
  selected?: boolean
  dragging?: boolean
}>()
const emit = defineEmits<{
  open: [id: number]
  dragstart: [event: DragEvent, card: Card]
  dragend: []
  changed: []
}>()

const now = useNow()

const human = computed(() => isHuman(props.card))
const draggable = computed(() => canDrag(props.card))
const overdue = computed(() => isOverdue(props.card, todayIso()))
const blocked = computed(() => isBlocked(props.card))
const run = computed(() => props.card.last_run)
// What actually ran when there is a run, otherwise what the task asks for; a human task has no model.
const modelFull = computed(() => (human.value ? null : run.value?.model_reported || run.value?.model_requested || props.card.model || null))
const modelText = computed(() => formatModelShort(modelFull.value))
const elapsed = computed(() => {
  const r = run.value
  if (!r || r.stage !== 'running') return null
  return formatDuration(Math.floor(Math.max(0, now.value - r.started_at)))
})
</script>

<template>
  <div
    class="row task-row"
    role="row"
    :data-card-id="card.id"
    :data-dragging="dragging ? 'true' : undefined"
    :data-selected="selected ? 'true' : undefined"
    :draggable="draggable"
    @click="emit('open', card.id)"
    @dragstart="emit('dragstart', $event, card)"
    @dragend="emit('dragend')"
  >
    <div class="cell name" role="cell">
      <span class="dot" aria-hidden="true"></span>
      <button
        type="button"
        class="open"
        :aria-label="`Open task: ${card.title}`"
        @click.stop="emit('open', card.id)"
      >
        {{ card.title }}
      </button>
      <span v-if="card.created_by === 'hermes'" class="muted small" title="Created by Hermes"
        >via Hermes</span
      >
      <span v-if="card.tags.length" class="tags">
        <TagPill v-for="t in card.tags" :key="t" :tag="t" />
      </span>
      <ChipTag
        v-if="blocked"
        tone="warn"
        :title="`Blocked by ${idList(card.blocked_by)}`"
        data-testid="blocked-chip"
      >
        <AppIcon name="link" size="sm" />Blocked by
        {{ idList(card.blocked_by) }}
      </ChipTag>
    </div>

    <div class="cell" role="cell" data-col="assignee">
      <ChipTag v-if="human" tone="muted"><AppIcon name="user" size="sm" />You</ChipTag>
      <ChipTag v-else tone="accent"><AppIcon name="cpu" size="sm" />{{ agentLabel(card.agent) }}</ChipTag>
    </div>

    <div class="cell" role="cell" data-col="model">
      <span v-if="modelFull" class="model" :title="modelFull">{{ modelText }}</span>
      <span v-else class="muted" data-missing="true">{{ DASH }}</span>
    </div>

    <div class="cell" role="cell" data-col="due">
      <span
        v-if="card.due_date"
        class="due"
        :class="{ overdue, danger: overdue }"
        :data-overdue="overdue ? 'true' : undefined"
      >
        <AppIcon name="calendar" size="sm" />{{ formatDueDate(card.due_date) }}
        <span v-if="overdue" class="sr-only"> (overdue)</span>
      </span>
      <span v-else class="muted" data-missing="true">{{ DASH }}</span>
    </div>

    <div class="cell" role="cell" data-col="estimate">
      <span v-if="card.estimate_minutes != null" class="est"
        ><AppIcon name="hourglass" size="sm" />{{ formatEstimate(card.estimate_minutes) }}</span
      >
      <span v-else class="muted" data-missing="true">{{ DASH }}</span>
    </div>

    <div class="cell" role="cell" data-col="priority">
      <span class="prio" :data-priority="card.priority">
        <AppIcon name="flag" size="sm" />{{ priorityLabel(card.priority) }}
      </span>
    </div>

    <div class="cell deps" role="cell" data-col="depends">
      <template v-if="card.depends_on.length">
        <button
          v-for="id in card.depends_on"
          :key="id"
          type="button"
          class="dep-link"
          :aria-label="`Open task #${id}`"
          @click.stop="emit('open', id)"
        >
          #{{ id }}
        </button>
      </template>
      <span v-else class="muted" data-missing="true">{{ DASH }}</span>
    </div>

    <div class="cell" role="cell" data-col="run">
      <template v-if="!human && run">
        <ChipTag :tone="stageTone(run.stage)">{{ stageLabel(run.stage) }}</ChipTag>
        <span v-if="elapsed" class="timer" data-testid="elapsed">{{ elapsed }}</span>
      </template>
      <span v-else class="muted" data-missing="true">{{ DASH }}</span>
      <TaskApprovalAction :card="card" @changed="emit('changed')" />
    </div>
  </div>
</template>

<style scoped>
.row {
  display: grid;
  grid-template-columns: var(--task-grid);
  align-items: center;
  column-gap: var(--gap);
  min-height: var(--row-min-height);
  padding: 0 var(--gap-sm);
  border-bottom: 1px solid var(--panel-border);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.row:hover,
.row[data-selected='true'] {
  background: var(--panel-raised);
}

.row[draggable='true'] {
  cursor: grab;
}

.row[data-dragging='true'] {
  opacity: var(--drag-opacity);
}

.cell {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--gap-xs);
  min-width: 0;
  padding: var(--gap-xs) 0;
}

.cell.name {
  gap: var(--gap-sm);
  flex-wrap: wrap;
}

.dot {
  flex-shrink: 0;
  width: var(--dot-size);
  height: var(--dot-size);
  border-radius: var(--radius-pill);
  background: var(--pill-color);
}

.open {
  all: unset;
  cursor: inherit;
  min-width: 0;
  max-width: 100%;
  font-size: var(--font-size);
  font-weight: var(--font-weight-strong);
  overflow-wrap: anywhere;
  border-radius: var(--radius-sm);
}

.open:focus-visible,
.dep-link:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.tags {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
}

.model {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.due,
.est,
.prio {
  display: inline-flex;
  align-items: center;
  gap: var(--icon-gap);
  white-space: nowrap;
}

.due.danger {
  color: var(--danger);
  font-weight: var(--font-weight-strong);
}

.prio[data-priority='urgent'] {
  color: var(--danger);
}

.prio[data-priority='high'] {
  color: var(--warn);
}

.prio[data-priority='normal'] {
  color: var(--accent);
}

.prio[data-priority='low'] {
  color: var(--text-muted);
}

.deps {
  gap: var(--gap-sm);
}

.dep-link {
  all: unset;
  cursor: pointer;
  color: var(--accent);
  border-radius: var(--radius-sm);
}

.dep-link:hover {
  text-decoration: underline;
}

.timer {
  font-variant-numeric: tabular-nums;
  color: var(--accent);
}
@media (max-width: 767.98px) {
  .row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    padding: var(--gap-sm);
    gap: var(--gap-xs) var(--gap-sm);
  }
  .cell.name {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: var(--dot-size) minmax(0, 1fr);
    align-items: start;
  }
  .cell.name > :not(.dot):not(.open) {
    grid-column: 2;
  }
  .cell.name .dot {
    margin-top: var(--gap-sm);
  }
  .cell:not(.name)::before {
    color: var(--text-muted);
    font-size: var(--font-size-xs);
  }
  [data-col='model']::before {
    content: 'Model';
  }
  [data-col='due']::before {
    content: 'Due';
  }
  [data-col='estimate']::before {
    content: 'Est.';
  }
  [data-col='priority']::before {
    content: 'Priority';
  }
  [data-col='depends']::before {
    content: 'Depends on';
  }
  [data-col='run']::before {
    content: 'Run';
  }
}
</style>
