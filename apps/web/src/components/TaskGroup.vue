<script setup lang="ts">
import { nextTick, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import TaskRow from '@/components/TaskRow.vue'
import type { Card } from '@/lib/api'
import type { GroupDef } from '@/lib/cards'

const props = defineProps<{
  group: GroupDef
  cards: readonly Card[]
  collapsed: boolean
  selectedId: number | null
  draggingId: number | null
  /** The dragged card may be dropped here. */
  droppable: boolean
  /** The dragged card is over this group. */
  over: boolean
  /** Create a human task in this group. Rejects with the server's message. */
  quickAdd: (title: string) => Promise<void>
}>()

const emit = defineEmits<{
  toggle: []
  open: [id: number]
  dragstart: [event: DragEvent, card: Card]
  dragend: []
  dragover: [event: DragEvent]
  dragleave: [event: DragEvent]
  drop: [event: DragEvent]
  changed: []
}>()

const bodyId = `group-body-${props.group.id}`

// ---- quick add ----
const adding = ref(false)
const title = ref('')
const busy = ref(false)
const addError = ref<string | null>(null)
const input = ref<HTMLInputElement | null>(null)

async function startAdd(): Promise<void> {
  adding.value = true
  addError.value = null
  await nextTick()
  input.value?.focus()
}

function cancelAdd(): void {
  adding.value = false
  title.value = ''
  addError.value = null
}

async function submitAdd(): Promise<void> {
  const text = title.value.trim()
  if (!text || busy.value) return
  busy.value = true
  addError.value = null
  try {
    await props.quickAdd(text)
    cancelAdd()
  } catch (e) {
    addError.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

function onBlur(): void {
  if (!busy.value && title.value.trim() === '' && !addError.value) cancelAdd()
}
</script>

<template>
  <section
    class="group"
    :data-group="group.id"
    :data-column="group.id"
    :data-collapsed="collapsed ? 'true' : 'false'"
    :data-drop="over ? 'true' : undefined"
    :data-droppable="droppable ? 'true' : undefined"
    @dragover="emit('dragover', $event)"
    @dragleave="emit('dragleave', $event)"
    @drop="emit('drop', $event)"
  >
    <header class="group-head">
      <h2 class="group-title">
        <button
          type="button"
          class="toggle"
          :aria-expanded="collapsed ? 'false' : 'true'"
          :aria-controls="bodyId"
          data-testid="group-toggle"
          @click="emit('toggle')"
        >
          <AppIcon :name="collapsed ? 'chevron-right' : 'chevron-down'" size="sm" />
          <span class="pill"><AppIcon :name="group.icon" size="sm" />{{ group.label }}</span>
        </button>
      </h2>
      <span class="count" data-testid="count" :aria-label="`${cards.length} tasks`">{{ cards.length }}</span>
      <span v-if="group.subtitle" class="muted small subtitle">{{ group.subtitle }}</span>
    </header>

    <div v-if="!collapsed" :id="bodyId" class="group-body">
      <div role="table" class="table" :aria-label="`${group.label} tasks`">
        <div v-if="cards.length" class="row head-row" role="row">
          <div class="cell" role="columnheader">Name</div>
          <div class="cell" role="columnheader">Assignee</div>
          <div class="cell" role="columnheader">Model</div>
          <div class="cell" role="columnheader" data-col="due">Due date</div>
          <div class="cell" role="columnheader" data-col="estimate">Estimate</div>
          <div class="cell" role="columnheader" data-col="priority">Priority</div>
          <div class="cell" role="columnheader">Depends on</div>
          <div class="cell" role="columnheader">Last run</div>
        </div>
        <TaskRow
          v-for="card in cards"
          :key="card.id"
          :card="card"
          :selected="selectedId === card.id"
          :dragging="draggingId === card.id"
          @open="emit('open', $event)"
          @dragstart="(e, c) => emit('dragstart', e, c)"
          @dragend="emit('dragend')"
          @changed="emit('changed')"
        />
      </div>
      <p v-if="cards.length === 0" class="muted small empty">No tasks</p>

      <div v-if="adding" class="add-form">
        <input
          ref="input"
          v-model="title"
          class="input"
          type="text"
          autocomplete="off"
          :aria-label="`New task title (${group.label})`"
          placeholder="New task for you, then Enter"
          :disabled="busy"
          data-testid="quick-add-input"
          @keydown.enter.prevent="submitAdd"
          @keydown.esc.stop="!busy && cancelAdd()"
          @blur="onBlur"
        />
        <div class="quick-actions">
          <button type="button" class="btn primary" :disabled="busy || !title.trim()" @click="submitAdd">
            {{ busy ? 'Adding…' : 'Add task for you' }}</button
          ><button type="button" class="btn" :disabled="busy" @click="cancelAdd">Cancel</button>
        </div>
        <p v-if="addError" class="error-text small" role="alert" data-testid="quick-add-error">
          {{ addError }}
        </p>
      </div>
      <button v-else type="button" class="add-row" data-testid="quick-add" @click="startAdd">
        <AppIcon name="plus" size="sm" />Add task
      </button>
    </div>
  </section>
</template>

<style scoped>
.group {
  --pill-color: var(--text-muted);
  --pill-bg: var(--panel-raised);
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  padding: var(--gap) var(--gap) var(--gap-xs);
  border: 1px solid var(--surface-border);
  border-left: 4px solid var(--pill-color);
  border-radius: var(--radius);
  background: var(--panel);
  min-width: 0;
}

.group[data-collapsed='true'] {
  padding-bottom: var(--gap);
}

.group[data-group='running'] {
  --pill-color: var(--accent);
  --pill-bg: var(--accent-soft);
}

.group[data-group='review'] {
  --pill-color: var(--warn);
  --pill-bg: var(--warn-soft);
}

.group[data-group='queued'] {
  --pill-color: var(--series-4);
  --pill-bg: var(--series-4-soft);
}

.group[data-group='failed'] {
  --pill-color: var(--danger);
  --pill-bg: var(--danger-soft);
}

.group[data-group='done'] {
  --pill-color: var(--ok);
  --pill-bg: var(--ok-soft);
}

.group[data-drop='true'] {
  outline: 1px solid var(--accent);
  background: var(--accent-soft);
}

.group-head {
  display: flex;
  padding-bottom: var(--gap-xs);
  align-items: center;
  gap: var(--gap-sm);
  position: sticky;
  left: 0;
  width: max-content;
  max-width: 100%;
}

.group-title {
  margin: 0;
  font-size: var(--font-size);
}

.toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-sm);
  min-height: var(--touch-target);
  padding: 0 var(--gap-sm);
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  cursor: pointer;
}

.toggle:hover {
  color: var(--text);
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: var(--icon-gap);
  padding: var(--gap-xs) var(--gap-sm);
  border-radius: var(--radius-sm);
  background: var(--pill-bg);
  color: var(--pill-color);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-strong);
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.count {
  min-width: 1.6rem;
  padding: 0 var(--gap-sm);
  border-radius: var(--radius-pill);
  background: var(--pill-bg);
  color: var(--pill-color);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-strong);
  text-align: center;
}

.subtitle {
  white-space: nowrap;
}

.group-body {
  container: tasks / inline-size;
  overflow-x: auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.table {
  min-width: var(--task-list-min-width);
}
.quick-actions {
  display: flex;
  gap: var(--gap-sm);
  flex-wrap: wrap;
}
.head-row {
  display: grid;
  grid-template-columns: var(--task-grid);
  align-items: center;
  column-gap: var(--gap);
  padding: 0 var(--gap-sm);
}

.head-row {
  min-height: var(--row-min-height);
  border-bottom: 1px solid var(--panel-border);
  color: var(--text-muted);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-strong);
}

.empty {
  margin: 0;
  padding: var(--gap-sm);
}

.add-row {
  display: inline-flex;
  align-items: center;
  gap: var(--icon-gap);
  width: 100%;
  min-height: var(--row-min-height);
  padding: 0 var(--gap-sm);
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: var(--font-size-sm);
  text-align: left;
  cursor: pointer;
}

.add-row:hover {
  color: var(--text);
  background: var(--panel-raised);
}

.add-form {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  padding: var(--gap-xs) var(--gap-sm);
  max-width: var(--drawer-width);
}

.add-form p {
  margin: 0;
}
@media (min-width: 768px) {
  @container tasks (max-width: 81.99rem) {
    .table {
      min-width: var(--task-list-medium-min-width);
    }
    .head-row {
      grid-template-columns: var(--task-grid-medium);
    }
    .head-row [data-col='due'] {
      display: none;
    }
  }
  @container tasks (max-width: 67.99rem) {
    .table {
      min-width: var(--task-list-compact-min-width);
    }
    .head-row {
      grid-template-columns: var(--task-grid-compact);
    }
    .head-row [data-col='estimate'],
    .head-row [data-col='priority'] {
      display: none;
    }
  }
}
@media (max-width: 767.98px) {
  .table {
    min-width: 0;
  }
  .head-row {
    display: none;
  }
  .group-head {
    flex-wrap: wrap;
    width: auto;
  }
  .subtitle {
    display: none;
  }
}
</style>
