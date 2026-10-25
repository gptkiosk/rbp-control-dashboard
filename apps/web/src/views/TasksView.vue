<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import PageHead from '@/components/PageHead.vue'
import CardDetailPanel from '@/components/CardDetailPanel.vue'
import TaskGroup from '@/components/TaskGroup.vue'
import NewCardDialog from '@/components/NewCardDialog.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import { postJson, type Card, type CardColumn, type CardsPayload } from '@/lib/api'
import {
  AGENT_IDS,
  GROUPS,
  PRIORITIES,
  agentLabel,
  canDrag,
  canMoveTo,
  emptyFilters,
  filtersActive,
  groupCards,
  matchesFilters,
  moveCard,
  type GroupDef,
} from '@/lib/cards'
import { loadPrefs, savePrefs } from '@/lib/boardPrefs'
import { navIcon } from '@/router/routes'
import { useGuideAction } from '@/composables/useGuideAction'

const route = useRoute()
const router = useRouter()
const { data, error, loaded, refresh } = usePolledJson<CardsPayload>('/api/cards', 3000, {
  match: (e) => e.type !== 'project',
})
const prefs = reactive(loadPrefs())
watch(prefs, savePrefs, { deep: true })
const cards = computed(() => data.value?.cards ?? [])
const supersededCount = computed(() => cards.value.filter((c) => c.superseded).length)
const activeCards = computed(() => cards.value.filter((c) => !c.superseded))
const filtered = computed(() => activeCards.value.filter((c) => matchesFilters(c, prefs.filters)))
const grouped = computed(() => groupCards(filtered.value))
const visibleGroups = computed(() => GROUPS.filter((g) => !prefs.hidden.includes(g.id)))
const activeFilters = computed(() => filtersActive(prefs.filters))
const tags = computed(() =>
  [...new Set([...cards.value.flatMap((c) => c.tags), ...prefs.filters.tags])].sort(),
)
const notice = ref<{ tone: 'warn' | 'danger'; text: string } | null>(null)
const showNewCard = ref(false)
useGuideAction('new', () => { showNewCard.value = true })
const selectedId = computed(() => {
  const raw = Array.isArray(route.query.card) ? route.query.card[0] : route.query.card
  const n = Number(raw)
  return Number.isInteger(n) && n > 0 ? n : null
})
function openCard(id: number): void {
  void router.push({ query: { ...route.query, card: String(id) } })
}
function closeCard(): void {
  const { card: _drop, ...rest } = route.query
  void router.replace({ query: rest })
}
function toggleGroup(id: CardColumn): void {
  prefs.collapsed = prefs.collapsed.includes(id)
    ? prefs.collapsed.filter((x) => x !== id)
    : [...prefs.collapsed, id]
}
const draggingId = ref<number | null>(null)
const overColumn = ref<CardColumn | null>(null)
const moving = ref(new Set<number>())
function canDrop(g: GroupDef): boolean {
  const card = cards.value.find((c) => c.id === draggingId.value)
  return !!card && canMoveTo(card, g.id)
}
function onDragStart(e: DragEvent, card: Card): void {
  if (!canDrag(card)) {
    e.preventDefault()
    return
  }
  draggingId.value = card.id
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(card.id))
  }
}
function onDragEnd(): void {
  draggingId.value = null
  overColumn.value = null
}
function onDragOver(e: DragEvent, g: GroupDef): void {
  if (!canDrop(g)) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  overColumn.value = g.id
}
function onDragLeave(e: DragEvent, g: GroupDef): void {
  const next = e.relatedTarget as Node | null
  if (overColumn.value === g.id && !(next && (e.currentTarget as Node).contains(next)))
    overColumn.value = null
}
async function onDrop(e: DragEvent, g: GroupDef): Promise<void> {
  if (!canDrop(g)) return
  e.preventDefault()
  const id = draggingId.value
  onDragEnd()
  if (id === null || moving.value.has(id)) return
  moving.value.add(id)
  try {
    const result = await moveCard(id, g.id)
    if (data.value)
      data.value = {
        cards: cards.value.map((c) => (c.id === id ? result.card : c)),
      }
    notice.value = result.notice ? { tone: 'warn', text: result.notice } : null
    prefs.collapsed = prefs.collapsed.filter((x) => x !== result.card.column)
  } catch (e) {
    notice.value = {
      tone: 'danger',
      text: `Could not move task: ${e instanceof Error ? e.message : String(e)}`,
    }
  } finally {
    moving.value.delete(id)
    refresh()
  }
}
function onCreated(card: Card): void {
  showNewCard.value = false
  notice.value = null
  prefs.hidden = prefs.hidden.filter((x) => x !== card.column)
  prefs.collapsed = prefs.collapsed.filter((x) => x !== card.column)
  if (data.value)
    data.value = {
      cards: [...cards.value.filter((c) => c.id !== card.id), card],
    }
  if (!matchesFilters(card, prefs.filters))
    notice.value = {
      tone: 'warn',
      text: 'Task created. Your current filters hide it.',
    }
  refresh()
}
async function quickAdd(title: string, column: CardColumn): Promise<void> {
  const created = await postJson<Card>('/api/cards', {
    title,
    assignee_type: 'human',
  })
  // The API creates in Backlog. A move failure must not silently leave a duplicate on retry.
  let card = created
  if (column !== 'backlog') {
    try {
      card = (await moveCard(created.id, column)).card
    } catch (e) {
      notice.value = {
        tone: 'danger',
        text: `Task #${created.id} was created in Backlog, but could not be moved: ${e instanceof Error ? e.message : String(e)}`,
      }
      refresh()
      return
    }
  }
  onCreated(card)
}
</script>

<template>
  <section class="page" aria-labelledby="tasks-title">
    <PageHead id="tasks-title" title="Tasks" :icon="navIcon('tasks')" sub="Your work and your agents’ work, grouped by status." help="agent-tasks">
      <button type="button" class="btn primary" @click="showNewCard = true"><AppIcon name="plus" />New task</button>
    </PageHead>
    <div id="board-controls" class="toolbar">
      <label class="search"
        ><AppIcon name="search" /><span class="sr-only">Search tasks</span
        ><input
          v-model="prefs.filters.search"
          type="search"
          class="input"
          placeholder="Search tasks, tags or #ID"
      /></label>
      <details class="controls" name="task-board-controls">
        <summary class="btn">
          <AppIcon name="filter" />Filters<span
            v-if="activeFilters"
            class="active-dot"
            aria-label="Active filters"
          ></span>
          <AppIcon name="chevron-down" class="menu-chevron" />
        </summary>
        <div class="filter-grid">
          <fieldset>
            <legend>Agent</legend>
            <label v-for="a in AGENT_IDS" :key="a" class="choice"
              ><input v-model="prefs.filters.agents" type="checkbox" :value="a" />{{ agentLabel(a) }}</label
            >
          </fieldset>
          <fieldset>
            <legend>Assignee</legend>
            <label class="choice"
              ><input v-model="prefs.filters.assignees" type="checkbox" value="human" />You (human)</label
            ><label class="choice"
              ><input v-model="prefs.filters.assignees" type="checkbox" value="agent" />Agents</label
            >
          </fieldset>
          <fieldset>
            <legend>Priority</legend>
            <label v-for="p in PRIORITIES" :key="p.id" class="choice"
              ><input v-model="prefs.filters.priorities" type="checkbox" :value="p.id" />{{ p.label }}</label
            >
          </fieldset>
          <fieldset>
            <legend>Created by</legend>
            <label class="choice"
              ><input v-model="prefs.filters.createdBy" type="checkbox" value="operator" />You</label
            ><label class="choice"
              ><input v-model="prefs.filters.createdBy" type="checkbox" value="hermes" />Hermes</label
            >
          </fieldset>
          <fieldset>
            <legend>Tags</legend>
            <p v-if="!tags.length" class="hint">No tags yet</p>
            <label v-for="t in tags" :key="t" class="choice"
              ><input v-model="prefs.filters.tags" type="checkbox" :value="t" />{{ t }}</label
            >
          </fieldset>
          <fieldset>
            <legend>Attention</legend>
            <label class="choice"
              ><input v-model="prefs.filters.blockedOnly" type="checkbox" />Blocked only</label
            ><label class="choice"
              ><input v-model="prefs.filters.overdueOnly" type="checkbox" />Overdue only</label
            >
          </fieldset>
        </div>
      </details>
      <details class="controls lanes" name="task-board-controls">
        <summary class="btn">
          <AppIcon name="tasks" />Lanes<span v-if="prefs.hidden.length"
            >({{ prefs.hidden.length }} hidden)</span
          >
          <AppIcon name="chevron-down" class="menu-chevron" />
        </summary>
        <div class="lane-options">
          <label v-for="g in GROUPS" :key="g.id" class="choice"
            ><input
              type="checkbox"
              :checked="!prefs.hidden.includes(g.id)"
              @change="
                prefs.hidden = prefs.hidden.includes(g.id)
                  ? prefs.hidden.filter((x) => x !== g.id)
                  : [...prefs.hidden, g.id]
              "
            />{{ g.name }}</label
          ><button type="button" class="btn" @click="prefs.hidden = []">Show all lanes</button>
        </div>
      </details>
      <button v-if="activeFilters" type="button" class="btn" @click="prefs.filters = emptyFilters()">
        Clear filters
      </button>
      <span class="muted small result-count" role="status"
        >{{ filtered.length }} of {{ activeCards.length }} active tasks</span
      >
    </div>
    <div
      v-if="notice"
      class="notice"
      :data-tone="notice.tone"
      :role="notice.tone === 'danger' ? 'alert' : 'status'"
      data-testid="board-notice"
    >
      <span>{{ notice.text }}</span
      ><button type="button" class="btn" aria-label="Dismiss message" @click="notice = null">×</button>
    </div>
    <p v-if="supersededCount" class="hint" data-testid="superseded-hidden">{{ supersededCount }} superseded, unstarted task{{ supersededCount === 1 ? ' is' : 's are' }} kept in project history and hidden from active work.</p>
    <p v-if="error" class="error-text" role="alert">Could not load tasks: {{ error }}</p>
    <p v-else-if="!loaded" class="muted" role="status">Loading…</p>
    <p v-if="loaded && activeFilters && !filtered.length" class="hint">No tasks match your filters.</p>
    <p v-if="!visibleGroups.length" class="hint">All lanes are hidden. Use Lanes to show them again.</p>
    <div class="board" role="group" aria-label="Task board">
      <TaskGroup
        v-for="g in visibleGroups"
        :key="g.id"
        :group="g"
        :cards="grouped[g.id]"
        :collapsed="prefs.collapsed.includes(g.id)"
        :selected-id="selectedId"
        :dragging-id="draggingId"
        :droppable="canDrop(g)"
        :over="overColumn === g.id"
        :quick-add="(title) => quickAdd(title, g.id)"
        @toggle="toggleGroup(g.id)"
        @open="openCard"
        @changed="refresh"
        @dragstart="onDragStart"
        @dragend="onDragEnd"
        @dragover="onDragOver($event, g)"
        @dragleave="onDragLeave($event, g)"
        @drop="onDrop($event, g)"
      />
    </div>
    <NewCardDialog v-if="showNewCard" @close="showNewCard = false" @created="onCreated" />
    <CardDetailPanel
      v-if="selectedId !== null"
      :key="selectedId"
      :card-id="selectedId"
      @close="closeCard"
      @changed="refresh"
      @open="openCard"
    />
  </section>
</template>

<style scoped>
.head,
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex-wrap: wrap;
}
.head {
  justify-content: space-between;
  gap: var(--gap);
}
.head h1 {
  margin-bottom: var(--gap-xs);
}
.search {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex: 1;
  min-width: min(100%, var(--tile-min-width));
}
.search .input {
  min-width: 0;
}
.toolbar {
  position: relative;
  padding: var(--gap-sm) 0;
  border-bottom: 1px solid var(--panel-border);
}
.controls summary {
  list-style: none;
  cursor: pointer;
  min-height: var(--select-height);
  background: var(--select-bg);
  border-color: var(--select-border);
}
.controls summary::-webkit-details-marker {
  display: none;
}
.controls[open] summary {
  border-color: var(--accent);
  background: var(--select-hover);
}
.menu-chevron { color: var(--accent); transition: transform var(--transition); }
.controls[open] .menu-chevron { transform: rotate(180deg); }
.filter-grid,
.lane-options {
  position: absolute;
  z-index: var(--z-overlay);
  left: 0;
  right: 0;
  top: 100%;
  padding: var(--gap);
  border: 1px solid var(--select-border);
  border-radius: var(--radius);
  background: var(--select-menu-bg);
  -webkit-backdrop-filter: blur(var(--glass-blur));
  backdrop-filter: blur(var(--glass-blur));
  box-shadow: var(--shadow);
  max-height: var(--menu-max-height);
  overflow-y: auto;
}
.filter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--menu-min-width), 1fr));
  gap: var(--gap);
}
.filter-grid fieldset {
  margin: 0;
  padding: 0;
  border: 0;
  min-width: 0;
}
.filter-grid legend {
  color: var(--accent);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-strong);
  margin-bottom: var(--gap-xs);
}
.lane-options {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm) var(--gap);
}
.choice {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-height: var(--touch-target);
  font-size: var(--font-size);
  padding: var(--gap-xs) var(--gap-sm);
  border-radius: var(--radius-sm);
  overflow-wrap: anywhere;
}
.choice:hover { background: var(--accent-soft); }
@supports not (backdrop-filter: blur(1px)) { .filter-grid, .lane-options { background: var(--panel-raised); } }
.active-dot {
  width: var(--dot-size);
  height: var(--dot-size);
  background: var(--accent);
  border-radius: var(--radius-pill);
}
.result-count {
  white-space: nowrap;
}
.board {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
  min-width: 0;
}
.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
  padding: var(--gap-sm) var(--gap);
  border: 1px solid var(--warn);
  border-radius: var(--radius);
  background: var(--warn-soft);
  overflow-wrap: anywhere;
}
.notice[data-tone='danger'] {
  border-color: var(--danger);
  background: var(--danger-soft);
}
</style>
