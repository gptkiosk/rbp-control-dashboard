<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { directoryName, directoryDetail } from '@/lib/selectLabels'
import { computed, reactive, ref } from 'vue'
import TaskFields, { type TaskFieldValues } from '@/components/TaskFields.vue'
import TagPill from '@/components/TagPill.vue'
import TaskApprovalAction from '@/components/TaskApprovalAction.vue'
import ProjectPreviewAction from '@/components/ProjectPreviewAction.vue'
import QueuedTaskRouteAction from '@/components/QueuedTaskRouteAction.vue'
import TaskRetryAction from '@/components/TaskRetryAction.vue'
import ProjectPlanningRetryAction from '@/components/ProjectPlanningRetryAction.vue'
import MediaCallout from '@/components/MediaCallout.vue'
import { useProjectMedia } from '@/composables/useProjectMedia'
import AppIcon from '@/components/AppIcon.vue'
import ChipTag from '@/components/ChipTag.vue'
import ModalShell from '@/components/ModalShell.vue'
import ReportedValue from '@/components/ReportedValue.vue'
import RunLog from '@/components/RunLog.vue'
import { useNow } from '@/composables/useNow'
import { renderReport } from '@/lib/reportMarkdown'
import { usePolledJson } from '@/composables/usePolledJson'
import {
  deleteJson,
  getJson,
  patchJson,
  postJson,
  type Card,
  type CardColumn,
  type CardDetail,
  type CardsPayload,
  type CardMode,
  type CardPatch,
  type Run,
  type Workdir,
  type WorkdirsPayload,
} from '@/lib/api'
import {
  movableColumns,
  isHuman,
  isBlocked,
  idList,
  estimateForForm,
  estimateToMinutes,
  priorityLabel,
  agentLabel,
  approvalNotice,
  awaitsApproval,
  columnLabel,
  isCoordinatorAgent,
  moveCard,
  stageLabel,
  stageTone,
} from '@/lib/cards'
import {
  formatCount,
  formatDuration,
  formatSince,
  formatUsd,
  formatDueDate,
  formatEstimate,
} from '@/lib/format'

const props = defineProps<{ cardId: number }>()
const emit = defineEmits<{ close: []; changed: []; open: [id: number] }>()

const now = useNow()
const {
  data: card,
  error,
  loaded,
  refresh,
} = usePolledJson<CardDetail>(() => `/api/cards/${props.cardId}`, 3000, {
  // run_event carries only the run id; any run's note may be this card's.
  match: (e) => e.card_id === props.cardId || e.type === 'run_event' || e.type === 'bulk',
})

interface Message {
  tone: 'ok' | 'warn' | 'danger'
  text: string
}
const message = ref<Message | null>(null)
const busy = ref(false)
const moveValue = ref('')

const human = computed(() => !!card.value && isHuman(card.value))
const { media: projectMedia, link: mediaLink } = useProjectMedia(card)      // a human story about media shows what the studio will cost before it is opened
const running = computed(() => card.value?.column === 'running')
const locked = computed(() => (running.value && !human.value) || !!card.value?.project || !!card.value?.superseded)
const taskFields = ref<TaskFieldValues>({
  priority: 'normal',
  due_date: '',
  estimate: '',
  estimateUnit: 'hours',
  tags: [],
  acceptance: '',
})
const { data: allTasks } = usePolledJson<CardsPayload>('/api/cards', 5000)
const dependencyId = ref('')
const dependencyChoices = computed(() =>
  (allTasks.value?.cards ?? []).filter(
    (c) => c.id !== props.cardId && !card.value?.depends_on.includes(c.id),
  ),
)
function taskName(id: number): string {
  return allTasks.value?.cards.find((c) => c.id === id)?.title ?? `Task #${id}`
}
async function dependency(verb: 'add' | 'remove', id: number): Promise<void> {
  if (!card.value || busy.value || locked.value) return
  busy.value = true
  try {
    const path = `/api/cards/${props.cardId}/dependencies`
    if (verb === 'add') await postJson<Card>(path, { depends_on_id: id })
    else await deleteJson<Card>(`${path}/${id}`)
    dependencyId.value = ''
    message.value = {
      tone: 'ok',
      text: `Dependency ${verb === 'add' ? 'added' : 'removed'}.`,
    }
    await afterChange()
  } catch (e) {
    fail('Could not change dependency', e)
  } finally {
    busy.value = false
  }
}
const canApprove = computed(
  () =>
    !!card.value &&
    awaitsApproval(card.value) &&
    (card.value.column === 'review' || card.value.column === 'backlog'),
)
const runs = computed(() => card.value?.runs ?? [])

// ---- run selection: follows the newest run until the user picks one ----
const pickedRunId = ref<number | null>(null)
const selectedRun = computed<Run | null>(
  () => runs.value.find((r) => r.id === pickedRunId.value) ?? runs.value[0] ?? null,
)
const latestRun = computed(() => runs.value[0] ?? card.value?.last_run ?? null)
const viewingHistory = computed(() => !!latestRun.value && !!selectedRun.value && latestRun.value.id !== selectedRun.value.id)
const activeRun = computed<Run | null>(() => {
  const latest = runs.value[0] ?? card.value?.last_run ?? null
  return latest && latest.stage === 'running' ? latest : null
})
const resultHtml = computed(() => selectedRun.value?.result_text ? renderReport(selectedRun.value.result_text) : '')
const acceptanceHtml = computed(() => card.value?.acceptance ? renderReport(card.value.acceptance) : '')

const runDuration = computed(() => {
  const r = selectedRun.value
  if (!r) return null
  if (r.stage === 'running') return Math.floor(Math.max(0, now.value - r.started_at))
  return r.duration_s
})

function fail(prefix: string, e: unknown): void {
  message.value = {
    tone: 'danger',
    text: `${prefix}: ${e instanceof Error ? e.message : String(e)}`,
  }
}

async function afterChange(): Promise<void> {
  refresh()
  emit('changed')
}

// ---- moving ----
async function move(column: CardColumn): Promise<void> {
  if (!card.value || busy.value) return
  busy.value = true
  message.value = null
  try {
    const result = await moveCard(card.value.id, column)
    message.value = result.notice
      ? { tone: 'warn', text: result.notice }
      : { tone: 'ok', text: `Moved to ${columnLabel(result.card.column)}.` }
    await afterChange()
  } catch (e) {
    fail('Could not move the card', e)
  } finally {
    busy.value = false
    moveValue.value = ''
  }
}

function onMoveChange(e: Event): void {
  const value = (e.target as HTMLSelectElement).value
  if (value) void move(value as CardColumn)
}

// ---- approve / cancel / delete ----
async function approve(): Promise<void> {
  if (!card.value || busy.value) return
  busy.value = true
  message.value = null
  try {
    // Echo the nonce and route pin of the version shown, so the approval cannot be replayed or reused.
    const updated = await postJson<Card>(`/api/cards/${card.value.id}/approve`, {
      challenge: card.value.approval_challenge,
      pin: card.value.approval_pin,
    })
    message.value = {
      tone: 'ok',
      text: `Approved. The card is now in ${columnLabel(updated.column)}.`,
    }
    await afterChange()
  } catch (e) {
    fail('Could not approve', e)
  } finally {
    busy.value = false
  }
}

async function cancelRun(): Promise<void> {
  const r = activeRun.value
  if (!r || busy.value) return
  if (!window.confirm('Cancel the running agent? Work in progress is stopped.')) return
  busy.value = true
  message.value = null
  try {
    await postJson(`/api/runs/${r.id}/cancel`)
    message.value = { tone: 'ok', text: 'Cancel requested.' }
    await afterChange()
  } catch (e) {
    fail('Could not cancel the run', e)
  } finally {
    busy.value = false
  }
}

async function remove(): Promise<void> {
  if (!card.value || running.value || busy.value) return
  if (!window.confirm(card.value.closed_project ? `Delete this task? Its project is closed out. The run history of this task is removed; the project ledger keeps its handoff and incident entries.` : card.value.superseded_by ? `Delete this unneeded duplicate? Its work is carried by task #${card.value.superseded_by}. The run history of this card is removed; the project ledger keeps the record.` : `Delete "${card.value.title}" and its run history?`)) return
  busy.value = true
  message.value = null
  try {
    await deleteJson(`/api/cards/${card.value.id}`)
    emit('changed')
    emit('close')
  } catch (e) {
    fail('Could not delete the card', e)
  } finally {
    busy.value = false
  }
}

// ---- editing ----
const editing = ref(false)
const workdirs = ref<Workdir[]>([])
const form = reactive({
  title: '',
  body: '',
  mode: 'read' as CardMode,
  model: '',
  working_dir: '',
  timeoutMin: '30',
  idleTimeoutMin: '',
  maxAttempts: '1',
  retryBackoffSec: '0',
})

const workdirOptions = computed(() => {
  const paths = workdirs.value.map((w) => w.path)
  const current = form.working_dir
  return current && !paths.includes(current)
    ? [...workdirs.value, { path: current, branch: null, root: '' } as Workdir]
    : workdirs.value
})

async function startEdit(): Promise<void> {
  const c = card.value
  if (!c || running.value) return
  Object.assign(form, {
    title: c.title,
    body: c.body,
    mode: c.mode,
    model: c.model ?? '',
    working_dir: c.working_dir ?? '',
    timeoutMin: String(c.timeout_s / 60),
    idleTimeoutMin: c.idle_timeout_s ? String(c.idle_timeout_s / 60) : '',
    maxAttempts: String(c.max_attempts),
    retryBackoffSec: String(c.retry_backoff_s),
  })
  const estimate = estimateForForm(c.estimate_minutes)
  taskFields.value = {
    priority: c.priority,
    due_date: c.due_date ?? '',
    estimate: estimate.value,
    estimateUnit: estimate.unit,
    tags: [...c.tags],
    acceptance: c.acceptance ?? '',
  }
  editing.value = true
  message.value = null
  try {
    workdirs.value = (await getJson<WorkdirsPayload>('/api/workdirs')).workdirs
  } catch {
    /* the current directory stays selectable; the server validates the rest */
  }
}

async function save(): Promise<void> {
  const c = card.value
  if (!c || busy.value) return
  const patch: CardPatch = {}
  if (form.title.trim() !== c.title) patch.title = form.title.trim()
  if (form.body !== c.body) patch.body = form.body
  if (form.mode !== c.mode) patch.mode = form.mode
  const model = form.model.trim() || null
  if (model !== c.model) patch.model = model
  if (!human.value && form.working_dir !== c.working_dir) patch.working_dir = form.working_dir
  const timeout_s = Math.round(Number(form.timeoutMin) * 60)
  if (!Number.isFinite(timeout_s) || timeout_s < 30 || timeout_s > 21600) {
    message.value = {
      tone: 'danger',
      text: 'Timeout must be between 0.5 and 360 minutes.',
    }
    return
  }
  if (timeout_s !== c.timeout_s) patch.timeout_s = timeout_s
  const idle_timeout_s = form.idleTimeoutMin === '' ? null : Math.round(Number(form.idleTimeoutMin) * 60)
  if (idle_timeout_s !== null && (!Number.isFinite(idle_timeout_s) || idle_timeout_s < 1 || idle_timeout_s > 21600)) {
    message.value = { tone: 'danger', text: 'Idle timeout must be between 1 second and 360 minutes.' }; return
  }
  const max_attempts = Math.round(Number(form.maxAttempts)), retry_backoff_s = Math.round(Number(form.retryBackoffSec))
  if (!Number.isFinite(max_attempts) || max_attempts < 1 || max_attempts > 10 || !Number.isFinite(retry_backoff_s) || retry_backoff_s < 0 || retry_backoff_s > 3600) {
    message.value = { tone: 'danger', text: 'Retry policy must use 1–10 attempts and 0–3600 seconds backoff.' }; return
  }
  if (idle_timeout_s !== c.idle_timeout_s) patch.idle_timeout_s = idle_timeout_s
  if (max_attempts !== c.max_attempts) patch.max_attempts = max_attempts
  if (retry_backoff_s !== c.retry_backoff_s) patch.retry_backoff_s = retry_backoff_s
  const estimate = estimateToMinutes(taskFields.value.estimate, taskFields.value.estimateUnit)
  if (Number.isNaN(estimate) || (estimate !== null && estimate < 1)) {
    message.value = {
      tone: 'danger',
      text: 'Estimate must be at least one minute.',
    }
    return
  }
  const extra = {
    priority: taskFields.value.priority,
    due_date: taskFields.value.due_date || null,
    estimate_minutes: estimate,
    tags: taskFields.value.tags,
    acceptance: taskFields.value.acceptance.trim() || null,
  }
  for (const key of ['priority', 'due_date', 'estimate_minutes', 'tags', 'acceptance'] as const) {
    if (JSON.stringify(extra[key]) !== JSON.stringify(c[key])) Object.assign(patch, { [key]: extra[key] })
  }
  if (Object.keys(patch).length === 0) {
    editing.value = false
    return
  }
  busy.value = true
  message.value = null
  const hadApproval = !!c.approved_at
  try {
    const updated = await patchJson<Card>(`/api/cards/${c.id}`, patch)
    editing.value = false
    message.value =
      hadApproval && !updated.approved_at
        ? {
            tone: 'warn',
            text: 'Saved. This edit cleared the approval; approve the card again before it can run.',
          }
        : { tone: 'ok', text: 'Saved.' }
    await afterChange()
  } catch (e) {
    fail('Could not save', e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <ModalShell labelledby="card-detail-title" variant="drawer" @close="emit('close')">
    <div class="panel">
      <header class="head">
        <h2 id="card-detail-title" class="section-title">
          Task #{{ card?.id ?? cardId }} · {{ card?.title ?? 'Loading task…' }}
        </h2>
        <button type="button" class="btn" aria-label="Close card" data-autofocus @click="emit('close')">
          ×
        </button>
      </header>

      <p v-if="error && !card" class="error-text" role="alert">Could not load the card: {{ error }}</p>
      <p v-else-if="!loaded" class="muted" role="status">Loading…</p>

      <template v-if="card">
        <div class="chips">
          <ChipTag tone="muted">{{ columnLabel(card.column) }}</ChipTag>
          <ChipTag tone="accent">{{ human ? 'You' : agentLabel(card.agent) }}</ChipTag>
          <ChipTag v-if="card.created_by === 'hermes'" tone="muted">Created by Hermes</ChipTag>
          <ChipTag v-if="card.superseded" tone="muted">Superseded by replan</ChipTag>
          <ChipTag v-if="isCoordinatorAgent(card.agent)" tone="muted">Coordinator</ChipTag>
          <ChipTag v-if="!human" :tone="card.mode === 'edit' ? 'warn' : 'muted'">{{
            card.mode === 'edit' ? 'Edit' : 'Read'
          }}</ChipTag>
          <ChipTag v-if="awaitsApproval(card)" tone="warn">Needs approval</ChipTag>
          <ChipTag v-else-if="card.approved_at" tone="ok">Approved</ChipTag>
        </div>

        <p v-if="card.superseded" class="hint" data-testid="superseded-card">This untouched task belongs to an earlier project revision. Its scope and history are preserved in the project record; current work is in the replacement revision.</p>
        <MediaCallout v-if="card.project && !card.superseded" :media="projectMedia" :link="mediaLink" />
        <ProjectPreviewAction v-if="card.project && !card.superseded" :card="card" @changed="afterChange" />
        <TaskApprovalAction v-if="card.project && !card.superseded" :card="card" hide-media-link @changed="afterChange" />
        <QueuedTaskRouteAction v-if="card.project && !card.superseded" :card="card" @changed="afterChange" />
        <TaskRetryAction v-if="card.project && !card.superseded" :card="card" @changed="afterChange" />
        <ProjectPlanningRetryAction v-if="card.project && !card.superseded" :card="card" @changed="afterChange" />
        <div
          v-if="message"
          class="message"
          :data-tone="message.tone"
          :role="message.tone === 'danger' ? 'alert' : 'status'"
          data-testid="panel-message"
        >
          {{ message.text }}
        </div>

        <!-- Prompt, or the edit form -->
        <section v-if="!editing" class="block" aria-labelledby="prompt-h">
          <div class="block-head">
            <h3 id="prompt-h" class="sub-title">
              {{ human ? 'Description' : 'Prompt' }}
            </h3>
            <button type="button" class="btn" :disabled="locked || busy" @click="startEdit">Edit</button>
          </div>
          <pre class="log-window">{{ card.body }}</pre>
          <dl v-if="!human" class="facts">
            <div>
              <dt>Model</dt>
              <dd>{{ card.model ?? 'default' }}</dd>
            </div>
            <div>
              <dt>Working dir</dt>
              <dd class="mono">{{ card.working_dir }}</dd>
            </div>
            <div>
              <dt>Timeout</dt>
              <dd>{{ formatDuration(card.timeout_s) }}</dd>
            </div>
            <div v-if="card.agent_target">
              <dt>Agent id</dt>
              <dd>{{ card.agent_target }}</dd>
            </div>
            <div v-if="card.budget_usd != null">
              <dt>Budget</dt>
              <dd>{{ formatUsd(card.budget_usd, 2) }}</dd>
            </div>
          </dl>
          <dl class="facts">
            <div>
              <dt>Priority</dt>
              <dd>{{ priorityLabel(card.priority) }}</dd>
            </div>
            <div>
              <dt>Due date</dt>
              <dd>{{ formatDueDate(card.due_date) }}</dd>
            </div>
            <div>
              <dt>Estimate</dt>
              <dd>{{ formatEstimate(card.estimate_minutes) }}</dd>
            </div>
            <div v-if="card.assignee_type === 'human'">
              <dt>Assigned to</dt>
              <dd data-testid="assignee">{{ card.assignee_user || 'Unassigned' }}</dd>
            </div>
            <div v-if="card.kind || card.size || card.risk">
              <dt>Job envelope</dt>
              <dd data-testid="envelope">{{ [card.kind, card.size && `size ${card.size}`, card.risk && `${card.risk} risk`, card.route_tier && `${card.route_tier} route`, card.area].filter(Boolean).join(' · ') }}</dd>
            </div>
            <div v-if="card.route_reason">
              <dt>Why this route</dt>
              <dd>{{ card.route_reason }}</dd>
            </div>
          </dl>
          <div class="chips">
            <TagPill v-for="tag in card.tags" :key="tag" :tag="tag" />
          </div>
          <h3 class="sub-title">Definition of done</h3>
          <div v-if="card.acceptance" class="task-markdown" role="region" aria-label="Definition of done" tabindex="0" data-testid="card-acceptance" v-html="acceptanceHtml" />
          <p v-else class="muted small">No definition of done yet.</p>
        </section>

        <form v-else-if="!card.project" class="block edit" aria-label="Edit card" @submit.prevent="save">
          <div class="field">
            <label for="ed-title">Title</label>
            <input id="ed-title" v-model="form.title" class="input" type="text" required />
          </div>
          <div class="field">
            <label for="ed-body">{{ human ? 'Description' : 'Prompt' }}</label>
            <textarea id="ed-body" v-model="form.body" class="input" :required="!human"></textarea>
          </div>
          <TaskFields v-model="taskFields" prefix="ed" />
          <template v-if="!human">
            <fieldset class="field">
              <legend>Mode</legend>
              <div class="radios">
                <label class="radio"
                  ><input v-model="form.mode" type="radio" name="ed-mode" value="read" /> Read</label
                >
                <label class="radio"
                  ><input v-model="form.mode" type="radio" name="ed-mode" value="edit" /> Edit</label
                >
              </div>
            </fieldset>
            <div class="field">
              <label for="ed-model">Model</label>
              <input
                id="ed-model"
                v-model="form.model"
                class="input"
                type="text"
                placeholder="Agent default"
                autocomplete="off"
              />
            </div>
            <div class="field">
              <label for="ed-idle-timeout">Idle timeout (minutes, optional)</label>
              <input id="ed-idle-timeout" v-model="form.idleTimeoutMin" class="input" type="number" min="0.02" max="360" step="any" placeholder="Disabled" />
            </div>
            <div class="field">
              <label for="ed-max-attempts">Maximum attempts</label>
              <input id="ed-max-attempts" v-model="form.maxAttempts" class="input" type="number" min="1" max="10" step="1" />
            </div>
            <div class="field">
              <label for="ed-retry-backoff">Retry backoff (seconds)</label>
              <input id="ed-retry-backoff" v-model="form.retryBackoffSec" class="input" type="number" min="0" max="3600" step="1" />
            </div>
            <div class="field">
              <label for="ed-dir">Working directory</label>
              <AppSelect id="ed-dir" v-model="form.working_dir" class="input">
                <option v-for="w in workdirOptions" :key="w.path" :value="w.path" :data-label="directoryName(w.path)" :data-description="directoryDetail(w.path, w.branch)">
                  {{ w.branch ? `${w.path} (${w.branch})` : w.path }}
                </option>
              </AppSelect>
            </div>
            <div class="field">
              <label for="ed-timeout">Timeout (minutes)</label>
              <input
                id="ed-timeout"
                v-model="form.timeoutMin"
                class="input"
                type="number"
                min="0.5"
                max="360"
                step="any"
                required
              />
            </div>
          </template>
          <p v-if="!human" class="hint">
            Changing the prompt, mode, model, agent or working directory clears any approval.
          </p>
          <div class="actions">
            <button type="button" class="btn" :disabled="busy" @click="editing = false">Cancel</button>
            <button type="submit" class="btn primary" :disabled="busy">Save</button>
          </div>
        </form>

        <section class="block" aria-labelledby="dependencies-h">
          <h3 id="dependencies-h" class="sub-title has-icon"><AppIcon name="link" />Dependencies</h3>
          <p v-if="card.project" class="notice-warn">This task is managed by its reviewed project plan. <RouterLink :to="`/projects?project=${card.project.id}&view=work`">Open Projects</RouterLink> to retry this task or review its approved scope.</p>
          <p v-if="isBlocked(card)" class="warning-text" data-testid="dependency-notice">
            Blocked by {{ idList(card.blocked_by) }}.
            {{
              !human && card.column === 'queued'
                ? 'This queued agent task will start when its blockers are Done.'
                : 'Complete the blockers before starting this task.'
            }}
          </p>
          <ul v-if="card.depends_on.length" class="dependency-list">
            <li v-for="id in card.depends_on" :key="id">
              <button type="button" class="btn dependency-name" @click="emit('open', id)">
                #{{ id }} {{ taskName(id) }}</button
              ><ChipTag :tone="card.blocked_by.includes(id) ? 'warn' : 'ok'">{{
                card.blocked_by.includes(id) ? 'Blocking' : 'Done'
              }}</ChipTag
              ><button
                type="button"
                class="btn"
                :aria-label="`Remove dependency #${id}`"
                :disabled="busy || locked"
                @click="dependency('remove', id)"
              >
                ×
              </button>
            </li>
          </ul>
          <p v-else class="muted small">No dependencies.</p>
          <form class="dependency-add" @submit.prevent="dependency('add', Number(dependencyId))">
            <label for="dependency-id" class="sr-only">Add dependency</label
            ><AppSelect id="dependency-id" v-model="dependencyId" class="input" :disabled="busy || locked">
              <option value="">Choose a task…</option>
              <option v-for="c in dependencyChoices" :key="c.id" :value="c.id" :data-label="c.title" :data-description="`Task #${c.id}`">
                #{{ c.id }} {{ c.title }}
              </option></AppSelect
            ><button type="submit" class="btn" :disabled="!dependencyId || busy || locked">
              Add dependency
            </button>
          </form>
          <p v-if="card.dependents.length" class="hint">
            Needed by
            <button
              v-for="id in card.dependents"
              :key="id"
              type="button"
              class="dependent"
              @click="emit('open', id)"
            >
              #{{ id }}
            </button>
          </p>
        </section>

        <!-- Approval -->
        <section v-if="card.needs_approval" class="block approval" aria-labelledby="approval-h">
          <h3 id="approval-h" class="sub-title has-icon"><AppIcon name="approval" />Approval</h3>
          <p v-if="card.approved_at" class="ok-text">Approved {{ formatSince(card.approved_at, now) }}.</p>
          <p v-else class="muted small">{{ approvalNotice(card) }}</p>
          <ul v-if="card.approval_reasons.length" class="reasons">
            <li v-for="r in card.approval_reasons" :key="r">{{ r }}</li>
          </ul>
          <button v-if="canApprove && !card.project" type="button" class="btn primary" :disabled="busy" @click="approve">
            <AppIcon name="approval" />
            Approve
          </button>
        </section>

        <!-- Actions -->
        <section class="block" aria-label="Actions">
          <div class="actions wrap">
            <button
              v-if="!human && !card.project"
              type="button"
              class="btn primary"
              :disabled="busy || locked || card.column === 'queued'"
              @click="move('queued')"
            >
              <AppIcon name="run" />
              {{ card.column === 'failed' && card.last_run ? 'Rerun task' : 'Run' }}
            </button>
            <button v-if="activeRun" type="button" class="btn danger" :disabled="busy" @click="cancelRun">
              <AppIcon name="stop" />
              Cancel run
            </button>
            <button type="button" class="btn danger" :disabled="busy || (locked && !card.superseded_by && !card.closed_project)" :title="card.superseded_by ? `Unneeded duplicate: its work is carried by task #${card.superseded_by}` : card.closed_project ? 'This project is closed out, so this failed task can be removed' : undefined" @click="remove">
              <AppIcon name="trash" />
              Delete
            </button>
            <label class="move">
              <span>Move to…</span>
              <AppSelect :value="moveValue" class="input" :disabled="busy || locked" @change="onMoveChange">
                <option value="" disabled>Choose a column</option>
                <option
                  v-for="c in movableColumns(card)"
                  :key="c.id"
                  :value="c.id"
                  :disabled="c.id === card.column"
                >
                  {{ c.name }}
                </option>
              </AppSelect>
            </label>
          </div>
        </section>

        <!-- Runs -->
        <section v-if="!human" class="block" aria-labelledby="runs-h">
          <h3 id="runs-h" class="sub-title">Runs</h3>
          <p v-if="runs.length === 0" class="muted small">No runs yet.</p>
          <ul v-else class="runs">
            <li v-for="r in runs" :key="r.id">
              <button
                type="button"
                class="run-btn"
                :aria-pressed="selectedRun?.id === r.id ? 'true' : 'false'"
                @click="pickedRunId = r.id"
              >
                <span>Run #{{ r.id }}</span>
                <ChipTag :tone="stageTone(r.stage)">{{ stageLabel(r.stage) }}</ChipTag>
                <span class="muted small">{{ formatSince(r.started_at, now) }}</span>
              </button>
            </li>
          </ul>
        </section>

        <template v-if="selectedRun">
          <div v-if="viewingHistory && latestRun" class="history-notice" role="status" data-testid="run-history-notice">
            <p>Viewing older Run #{{ selectedRun.id }}. Latest Run #{{ latestRun.id }}: <strong>{{ stageLabel(latestRun.stage) }}</strong>.</p>
            <button type="button" class="btn" @click="pickedRunId = null">View latest run #{{ latestRun.id }}</button>
          </div>
          <section class="block" aria-labelledby="meta-h">
            <h3 id="meta-h" class="sub-title">Run #{{ selectedRun.id }}</h3>
            <dl class="meta" data-testid="run-meta">
              <div>
                <dt>Stage</dt>
                <dd>
                  <ChipTag :tone="stageTone(selectedRun.stage)">{{ stageLabel(selectedRun.stage) }}</ChipTag>
                </dd>
              </div>
              <div>
                <dt class="has-icon"><AppIcon name="model" size="sm" />Model requested</dt>
                <dd class="wrap-any"><ReportedValue :value="selectedRun.model_requested" /></dd>
              </div>
              <div>
                <dt class="has-icon"><AppIcon name="model" size="sm" />Model reported</dt>
                <dd v-if="!selectedRun.model_reported && selectedRun.model_derived" class="wrap-any" data-testid="model-derived" title="The agent did not report its model; this is the model MCD asked for.">{{ selectedRun.model_derived }} <span class="muted">(derived)</span></dd>
                <dd v-else class="wrap-any"><ReportedValue :value="selectedRun.model_reported" /></dd>
              </div>
              <div>
                <dt>Provider</dt>
                <dd><ReportedValue :value="selectedRun.provider" /></dd>
              </div>
              <div>
                <dt class="has-icon"><AppIcon name="tokens" size="sm" />Tokens in</dt>
                <dd>
                  <ReportedValue :value="selectedRun.input_tokens" :format="formatCount" />
                </dd>
              </div>
              <div>
                <dt class="has-icon"><AppIcon name="tokens" size="sm" />Tokens out</dt>
                <dd>
                  <ReportedValue :value="selectedRun.output_tokens" :format="formatCount" />
                </dd>
              </div>
              <div>
                <dt class="has-icon"><AppIcon name="cost" size="sm" />Cost (USD)</dt>
                <dd v-if="selectedRun.cost_usd == null && selectedRun.cost_derived_usd != null" data-testid="cost-derived" :title="`Not reported by the agent. Worked out by MCD from the token counts at the published API rates (${selectedRun.cost_basis}); a membership plan may cost nothing extra.`">
                  {{ formatUsd(selectedRun.cost_derived_usd) }} <span class="muted">(derived)</span>
                </dd>
                <dd v-else>
                  <ReportedValue :value="selectedRun.cost_usd" :format="formatUsd" />
                </dd>
              </div>
              <div>
                <dt class="has-icon"><AppIcon name="clock" size="sm" />Duration</dt>
                <dd>
                  <ReportedValue :value="runDuration" :format="formatDuration" />
                </dd>
              </div>
              <div>
                <dt>Exit code</dt>
                <dd><ReportedValue :value="selectedRun.exit_code" /><span
                  v-if="selectedRun.exit_code === 0 && selectedRun.error && selectedRun.stage !== 'succeeded' && selectedRun.stage !== 'running'"
                  class="small muted" data-testid="exit-code-explanation"
                > — CLI exited normally; the agent run did not succeed. See the error below.</span></dd>
              </div>
              <div>
                <dt>Session ID</dt>
                <dd class="mono wrap-any">
                  <ReportedValue :value="selectedRun.session_id" />
                </dd>
              </div>
              <div class="wide">
                <dt>Working dir</dt>
                <dd class="mono wrap-any">
                  <ReportedValue :value="selectedRun.working_dir" />
                </dd>
              </div>
              <div class="wide">
                <dt>Command</dt>
                <dd class="mono wrap-any">
                  <ReportedValue :value="selectedRun.command?.join(' ')" />
                </dd>
              </div>
              <div class="wide">
                <dt>Error</dt>
                <dd class="wrap-any">
                  <ReportedValue :value="selectedRun.error" empty="None" />
                </dd>
              </div>
            </dl>
          </section>

          <section class="block" aria-labelledby="log-h">
            <h3 id="log-h" class="sub-title">Log</h3>
            <RunLog :key="selectedRun.id" :run-id="selectedRun.id" />
          </section>

          <section class="block" aria-labelledby="result-h">
            <h3 id="result-h" class="sub-title">Result</h3>
            <div v-if="selectedRun.result_text" class="task-markdown" role="region" aria-label="Run result" tabindex="0" data-testid="run-result" v-html="resultHtml" />
            <p v-else class="muted small">
              {{ selectedRun.stage === 'running' ? 'The run has not finished yet.' : 'No result text.' }}
            </p>
          </section>
        </template>
      </template>
    </div>
  </ModalShell>
</template>

<style scoped>
.dependency-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}
.dependency-list li,
.dependency-add {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
  flex-wrap: wrap;
}
.dependency-name {
  flex: 1;
  justify-content: flex-start;
  overflow-wrap: anywhere;
  text-align: left;
}
.dependency-add .input {
  flex: 1;
  min-width: min(100%, var(--tile-min-width));
}
.dependent {
  background: transparent;
  color: var(--accent);
  border: 0;
  font: inherit;
  cursor: pointer;
}
.panel {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap);
  min-width: 0;
}

.head,
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
}

.head .section-title {
  overflow-wrap: anywhere;
}

.sub-title {
  margin: 0;
  font-size: var(--font-size);
  font-weight: var(--font-weight-strong);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
}

.block {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding-top: var(--gap);
  border-top: 1px solid var(--panel-border);
  min-width: 0;
}

.block p,
.block ul {
  margin: 0;
}

.message {
  padding: var(--gap-sm) var(--gap);
  border-radius: var(--radius);
  border: 1px solid var(--panel-border);
  overflow-wrap: anywhere;
}

.message[data-tone='ok'] {
  background: var(--ok-soft);
  border-color: var(--ok);
}

.message[data-tone='warn'] {
  background: var(--warn-soft);
  border-color: var(--warn);
}

.message[data-tone='danger'] {
  background: var(--danger-soft);
  border-color: var(--danger);
}

.facts,
.meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, var(--tile-min-width)), 1fr));
  gap: var(--gap-sm) var(--gap);
  margin: 0;
}

.facts > div,
.meta > div {
  min-width: 0;
}

.meta > .wide {
  grid-column: 1 / -1;
}

dt {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.wrap-any {
  overflow-wrap: anywhere;
}

.ok-text {
  color: var(--ok);
}

.reasons {
  padding-left: var(--gap-lg);
  color: var(--warn);
}

.actions {
  display: flex;
  gap: var(--gap-sm);
  justify-content: flex-end;
}

.actions.wrap {
  flex-wrap: wrap;
  justify-content: flex-start;
  align-items: flex-end;
}

.move {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.edit {
  gap: var(--gap);
}

.runs {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.history-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--gap-sm);
  padding: var(--gap-sm);
  border: 1px solid var(--accent);
  border-radius: var(--radius);
  background: var(--accent-soft);
}
.history-notice p { margin: 0; }

.run-btn {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  width: 100%;
  min-height: var(--touch-target);
  padding: var(--gap-xs) var(--gap-sm);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  background: var(--panel-raised);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.run-btn[aria-pressed='true'] {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.task-markdown {
  line-height: 1.65;
  overflow-wrap: anywhere;
  /* A long result scrolls inside its own bordered box; the box is focusable so the keyboard can scroll it. */
  max-height: min(36rem, 70vh);
  max-height: min(36rem, 70dvh);   /* phones: the visible height, not the height behind the browser toolbar */
  min-width: 0;
  max-width: 100%;
  overflow: auto;
  padding: var(--gap);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-sm);
  background: var(--bg);
}
.task-markdown:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.task-markdown :deep(> :first-child) { margin-top: 0; }
.task-markdown :deep(> :last-child) { margin-bottom: 0; }
.task-markdown :deep(p) { margin: .75em 0; }
.task-markdown :deep(ul),
.task-markdown :deep(ol) { margin: .75em 0; padding-left: 1.5em; }
.task-markdown :deep(ul) { list-style: disc; }
.task-markdown :deep(ol) { list-style: decimal; }
.task-markdown :deep(li) { margin: .25em 0; }
.task-markdown :deep(h1),
.task-markdown :deep(h2),
.task-markdown :deep(h3) { line-height: 1.3; margin: 1.35em 0 .55em; }
.task-markdown :deep(h1) { font-size: 1.45rem; }
.task-markdown :deep(h2) { font-size: 1.25rem; }
.task-markdown :deep(h3) { font-size: 1.1rem; }
.task-markdown :deep(a) { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
.task-markdown :deep(code) { color: var(--accent); font-size: .9em; }
.task-markdown :deep(pre) {
  overflow-x: auto;
  padding: var(--gap);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-sm);
  background: var(--panel);
}
.task-markdown :deep(pre code) { color: inherit; white-space: pre; }
.task-markdown :deep(blockquote) { margin-left: 0; padding-left: var(--gap); border-left: 3px solid var(--accent); color: var(--text-muted); }
.task-markdown :deep(table) { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
.task-markdown :deep(th),
.task-markdown :deep(td) { padding: var(--gap-sm); border: 1px solid var(--panel-border); }

</style>
