<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { directoryName, directoryDetail } from '@/lib/selectLabels'
import { computed, onMounted, ref, watch } from 'vue'
import TaskFields, { type TaskFieldValues } from '@/components/TaskFields.vue'
import { estimateToMinutes } from '@/lib/cards'
import ModalShell from '@/components/ModalShell.vue'
import OpenClawTarget from '@/components/OpenClawTarget.vue'
import {
  getJson,
  postJson,
  type Agent,
  type AssigneeType,
  type CardsPayload,
  type AgentId,
  type AgentsPayload,
  type Card,
  type CardMode,
  type NewCardInput,
  type Workdir,
  type WorkdirsPayload,
} from '@/lib/api'

const emit = defineEmits<{ close: []; created: [card: Card] }>()

const agents = ref<Agent[]>([])
const workdirs = ref<Workdir[]>([])
const loading = ref(true)
const loadError = ref<string | null>(null)

const assignee = ref<AssigneeType>('agent')
const taskFields = ref<TaskFieldValues>({
  priority: 'normal',
  due_date: '',
  estimate: '',
  estimateUnit: 'hours',
  tags: [],
  acceptance: '',
})
const dependencyCards = ref<Card[]>([])
const dependsOn = ref<number[]>([])
const title = ref('')
const body = ref('')
const agentId = ref<AgentId | ''>('')
const model = ref('')
const mode = ref<CardMode>('read')
const workingDir = ref('')
const timeoutMin = ref('30')
const budget = ref('1.00')
const target = ref('mm-main')

const submitting = ref(false)
const submitError = ref<string | null>(null)

const agent = computed(() => agents.value.find((a) => a.id === agentId.value) ?? null)
const dir = computed(() => workdirs.value.find((w) => w.path === workingDir.value) ?? null)
const modelOptions = computed(() => {
  const a = agent.value
  if (!a) return []
  return [...new Set([...(a.default_model ? [a.default_model] : []), ...a.suggested_models])]
})
const editOnMain = computed(
  () => mode.value === 'edit' && (dir.value?.branch === 'main' || dir.value?.branch === 'master'),
)

function dirLabel(w: Workdir): string {
  return w.branch ? `${w.path} (${w.branch})` : w.path
}

watch(agentId, () => {
  model.value = ''
})

onMounted(async () => {
  try {
    const [a, w] = await Promise.all([
      getJson<AgentsPayload>('/api/agents'),
      getJson<WorkdirsPayload>('/api/workdirs'),
    ])
    agents.value = a.agents
    workdirs.value = w.workdirs
    agentId.value = a.agents.find((x) => x.available)?.id ?? ''
    workingDir.value = w.workdirs[0]?.path ?? ''
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
  try {
    dependencyCards.value = (await getJson<CardsPayload>('/api/cards')).cards
  } catch {
    /* Dependencies can be added after creation. */
  }
})

async function submit(): Promise<void> {
  submitError.value = null
  if (assignee.value === 'agent' && !agentId.value) {
    submitError.value = 'Choose an agent.'
    return
  }
  const minutes = Number(timeoutMin.value)
  const timeout_s = Math.round(minutes * 60)
  if (assignee.value === 'agent' && (!Number.isFinite(minutes) || timeout_s < 30 || timeout_s > 21600)) {
    submitError.value = 'Timeout must be between 0.5 and 360 minutes.'
    return
  }
  const estimate_minutes = estimateToMinutes(taskFields.value.estimate, taskFields.value.estimateUnit)
  if (Number.isNaN(estimate_minutes) || (estimate_minutes !== null && estimate_minutes < 1)) {
    submitError.value = 'Estimate must be at least one minute.'
    return
  }
  const payload: NewCardInput = {
    title: title.value.trim(),
    body: body.value,
    assignee_type: assignee.value,
    priority: taskFields.value.priority,
    due_date: taskFields.value.due_date || null,
    estimate_minutes,
    tags: taskFields.value.tags,
    acceptance: taskFields.value.acceptance.trim() || null,
    depends_on: dependsOn.value,
  }
  if (assignee.value === 'agent') {
    Object.assign(payload, {
      agent: agentId.value,
      working_dir: workingDir.value,
      mode: mode.value,
      model: model.value.trim() || null,
      timeout_s,
    })
  }
  if (assignee.value === 'agent' && agentId.value === 'claude') {
    const usd = Number(budget.value)
    if (!Number.isFinite(usd) || usd < 0.01 || usd > 50) {
      submitError.value = 'Budget must be between $0.01 and $50.'
      return
    }
    payload.budget_usd = usd
  }
  if (assignee.value === 'agent' && agentId.value === 'openclaw')
    payload.agent_target = target.value.trim() || 'mm-main'

  submitting.value = true
  try {
    const card = await postJson<Card>('/api/cards', payload)
    emit('created', card)
  } catch (e) {
    submitError.value = e instanceof Error ? e.message : String(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <ModalShell labelledby="new-card-title" @close="emit('close')">
    <form class="form" @submit.prevent="submit">
      <header class="head">
        <h2 id="new-card-title" class="section-title">New task</h2>
        <button type="button" class="btn" aria-label="Close" @click="emit('close')">×</button>
      </header>

      <p v-if="loading" class="muted" role="status">Loading agents…</p>
      <p v-if="loadError" class="error-text" role="alert">
        Could not load agents or working directories: {{ loadError }}
      </p>

      <div class="field">
        <label for="nc-title">Title</label>
        <input id="nc-title" v-model="title" class="input" type="text" required data-autofocus />
      </div>

      <div class="field">
        <label for="nc-assignee">Assignee</label
        ><AppSelect id="nc-assignee" v-model="assignee" class="input">
          <option value="agent">Agent</option>
          <option value="human">You (human)</option>
        </AppSelect>
      </div>
      <div class="field">
        <label for="nc-body">{{ assignee === 'human' ? 'Description' : 'Prompt' }}</label>
        <textarea id="nc-body" v-model="body" class="input" :required="assignee === 'agent'"></textarea>
      </div>
      <TaskFields v-model="taskFields" prefix="nc" />
      <fieldset v-if="dependencyCards.length" class="field dependency-list">
        <legend>Depends on</legend>
        <label v-for="c in dependencyCards" :key="c.id" class="radio"
          ><input v-model="dependsOn" type="checkbox" :value="c.id" />#{{ c.id }} {{ c.title }}</label
        >
      </fieldset>
      <template v-if="assignee === 'agent'">
        <div class="field">
          <label for="nc-agent">Agent</label>
          <AppSelect id="nc-agent" v-model="agentId" class="input" required>
            <option v-for="a in agents" :key="a.id" :value="a.id" :disabled="!a.available" :data-label="a.name" :data-description="a.available ? (a.role === 'manager' ? 'Manager' : 'Worker') : 'Not installed'">
              {{ a.name }}{{ a.available ? '' : ' (not installed)' }}
            </option>
          </AppSelect>
        </div>

        <div class="field">
          <label for="nc-model">Model</label>
          <AppSelect
            id="nc-model" v-model="model" class="input" editable
            :placeholder="agent?.default_model ?? 'Agent default'"
          >
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
          </AppSelect>
        </div>

        <fieldset class="field">
          <legend>Mode</legend>
          <div class="radios">
            <label class="radio"
              ><input v-model="mode" type="radio" name="nc-mode" value="read" /> Read</label
            >
            <label class="radio"
              ><input v-model="mode" type="radio" name="nc-mode" value="edit" /> Edit</label
            >
          </div>
          <p v-if="agent && !agent.enforces_mode" class="hint" data-testid="advisory-note">
            Read/Edit is advisory for {{ agent.name }}. {{ agent.notes }}
          </p>
        </fieldset>

        <div class="field">
          <label for="nc-dir">Working directory</label>
          <AppSelect id="nc-dir" v-model="workingDir" class="input" required>
            <option v-for="w in workdirs" :key="w.path" :value="w.path" :data-label="directoryName(w.path)" :data-description="directoryDetail(w.path, w.branch)">
              {{ dirLabel(w) }}
            </option>
          </AppSelect>
          <p v-if="editOnMain" class="warning-text" role="status" data-testid="main-warning">
            Edits on main need your approval
          </p>
        </div>

        <div class="row">
          <div class="field">
            <label for="nc-timeout">Timeout (minutes)</label>
            <input
              id="nc-timeout"
              v-model="timeoutMin"
              class="input"
              type="number"
              min="0.5"
              max="360"
              step="any"
              required
            />
          </div>
          <div v-if="agentId === 'claude'" class="field">
            <label for="nc-budget">Budget (USD)</label>
            <input
              id="nc-budget"
              v-model="budget"
              class="input"
              type="number"
              min="0.01"
              max="50"
              step="0.01"
              required
            />
          </div>
          <OpenClawTarget
            v-if="agentId === 'openclaw'"
            id="nc-target"
            v-model="target"
            :agents="agent?.subagents?.agents"
          />
        </div>
      </template>
      <p v-if="submitError" class="error-text" role="alert" data-testid="submit-error">
        {{ submitError }}
      </p>

      <footer class="actions">
        <button type="button" class="btn" @click="emit('close')">Cancel</button>
        <button
          type="submit"
          class="btn primary"
          :disabled="submitting || (assignee === 'agent' && (loading || !agentId))"
        >
          {{ submitting ? 'Creating…' : 'Create task' }}
        </button>
      </footer>
    </form>
  </ModalShell>
</template>

<style scoped>
.dependency-list {
  max-height: var(--menu-max-height);
  overflow-y: auto;
}

.form {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap);
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--tile-min-width), 1fr));
  gap: var(--gap);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--gap-sm);
}
</style>
