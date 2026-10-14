<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppSelect from '@/components/AppSelect.vue'
import ModalShell from '@/components/ModalShell.vue'
import { ApiError, getJson, postJson, type Agent, type AgentId, type AgentsPayload, type Card, type CardMode, type Workdir, type WorkdirsPayload } from '@/lib/api'
import { dateLabel, type ReportFinding } from '@/lib/operations'
import { directoryDetail, directoryName } from '@/lib/selectLabels'

const props = defineProps<{ reportId: string; reportModified: number; finding: ReportFinding }>()
const emit = defineEmits<{ close: []; created: [task: Card] }>()

const agents = ref<Agent[]>([])
const workdirs = ref<Workdir[]>([])
const loading = ref(true)
const loadError = ref('')
const agentId = ref<AgentId | ''>('')
const model = ref('')
const mode = ref<CardMode>('read')
const workingDir = ref('')
const timeoutMin = ref('30')
const budget = ref('1.00')
const submitting = ref(false)
const submitError = ref('')
// `created: false` means a task already exists for this finding; the dialog then links to it instead of creating another.
const result = ref<{ created: boolean; task: Card } | null>(null)

const agent = computed(() => agents.value.find(a => a.id === agentId.value) ?? null)
const dir = computed(() => workdirs.value.find(w => w.path === workingDir.value) ?? null)
const modelOptions = computed(() => {
  const a = agent.value
  return a ? [...new Set([...(a.default_model ? [a.default_model] : []), ...a.suggested_models])] : []
})
const editOnMain = computed(() => mode.value === 'edit' && (dir.value?.branch === 'main' || dir.value?.branch === 'master'))
const evidenceLabel = computed(() => `${props.finding.status === 'crit' ? 'Critical' : 'Warning'} · captured ${dateLabel(props.reportModified)}`)

watch(agentId, () => { model.value = '' })

onMounted(async () => {
  try {
    const [a, w] = await Promise.all([getJson<AgentsPayload>('/api/agents'), getJson<WorkdirsPayload>('/api/workdirs')])
    agents.value = a.agents
    workdirs.value = w.workdirs
    agentId.value = a.agents.find(x => x.available)?.id ?? ''
    workingDir.value = w.workdirs[0]?.path ?? ''
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
})

async function submit(): Promise<void> {
  submitError.value = ''
  if (!agentId.value) { submitError.value = 'Choose an agent.'; return }
  const minutes = Number(timeoutMin.value)
  const timeout_s = Math.round(minutes * 60)
  if (!Number.isFinite(minutes) || timeout_s < 30 || timeout_s > 21600) { submitError.value = 'Timeout must be between 0.5 and 360 minutes.'; return }
  const body: Record<string, unknown> = {
    report_id: props.reportId, finding_id: props.finding.id, assignee_type: 'agent',
    agent: agentId.value, model: model.value.trim() || null, mode: mode.value,
    working_dir: workingDir.value, timeout_s,
  }
  if (agentId.value === 'claude') {
    const usd = Number(budget.value)
    if (!Number.isFinite(usd) || usd < 0.01 || usd > 50) { submitError.value = 'Budget must be between $0.01 and $50.'; return }
    body.budget_usd = usd
  }
  if (agentId.value === 'openclaw') body.agent_target = 'mm-main'
  submitting.value = true
  try {
    result.value = await postJson<{ created: boolean; task: Card }>(`/api/reports/${props.reportId}/findings/${props.finding.id}/draft`, body)
    if (result.value.created) emit('created', result.value.task)
  } catch (e) {
    submitError.value = e instanceof ApiError && (e.status === 401 || e.status === 403)
      ? 'Operator sign-in is required to create a task.'
      : e instanceof Error ? e.message : 'The task could not be created.'
  } finally {
    submitting.value = false
  }
}
</script>
<template>
  <ModalShell labelledby="finding-task-title" @close="emit('close')">
    <form class="form" @submit.prevent="submit">
      <header class="head">
        <h2 id="finding-task-title">Create task from finding</h2>
        <button type="button" class="btn" aria-label="Close" @click="emit('close')">×</button>
      </header>
      <p class="muted small">{{ finding.id }} · {{ evidenceLabel }}</p>
      <p class="muted small">Report <code>{{ reportId }}</code></p>
      <p><strong>{{ finding.reason }}</strong></p>
      <pre class="evidence" data-testid="finding-evidence">{{ finding.evidence || 'No evidence text in this section.' }}</pre>
      <p class="muted small">The task is created in Backlog. Nothing is queued or run until you start it.</p>

      <p v-if="loading" class="muted" role="status">Loading agents…</p>
      <p v-if="loadError" class="error-text" role="alert">Could not load agents or working directories: {{ loadError }}</p>

      <template v-if="result">
        <p v-if="result.created" role="status">Task #{{ result.task.id }} was created in Backlog.</p>
        <p v-else role="status" class="notice-warn">A task already exists for this finding.</p>
        <p><RouterLink :to="{ path: '/tasks', query: { card: String(result.task.id) } }">{{ result.created ? 'Open task' : 'Open existing task' }} #{{ result.task.id }}</RouterLink></p>
        <footer class="actions"><button type="button" class="btn" @click="emit('close')">Done</button></footer>
      </template>

      <template v-else>
        <div class="field">
          <label for="ft-agent">Agent</label>
          <AppSelect id="ft-agent" v-model="agentId" class="input" required>
            <option v-for="a in agents" :key="a.id" :value="a.id" :disabled="!a.available" :data-label="a.name" :data-description="a.available ? (a.role === 'manager' ? 'Manager' : 'Worker') : 'Not installed'">
              {{ a.name }}{{ a.available ? '' : ' (not installed)' }}
            </option>
          </AppSelect>
        </div>
        <div class="field">
          <label for="ft-model">Model</label>
          <AppSelect id="ft-model" v-model="model" class="input" editable :placeholder="agent?.default_model ?? 'Agent default'">
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
          </AppSelect>
        </div>
        <fieldset class="field">
          <legend>Mode</legend>
          <div class="radios">
            <label class="radio"><input v-model="mode" type="radio" name="ft-mode" value="read" /> Read</label>
            <label class="radio"><input v-model="mode" type="radio" name="ft-mode" value="edit" /> Edit</label>
          </div>
          <p v-if="agent && !agent.enforces_mode" class="hint" data-testid="advisory-note">Read/Edit is advisory for {{ agent.name }}. {{ agent.notes }}</p>
        </fieldset>
        <div class="field">
          <label for="ft-dir">Working directory</label>
          <AppSelect id="ft-dir" v-model="workingDir" class="input" required>
            <option v-for="w in workdirs" :key="w.path" :value="w.path" :data-label="directoryName(w.path)" :data-description="directoryDetail(w.path, w.branch)">
              {{ w.branch ? `${w.path} (${w.branch})` : w.path }}
            </option>
          </AppSelect>
          <p v-if="editOnMain" class="warning-text" role="status">Edits on main need your approval</p>
        </div>
        <div class="row">
          <div class="field">
            <label for="ft-timeout">Timeout (minutes)</label>
            <input id="ft-timeout" v-model="timeoutMin" class="input" type="number" min="0.5" max="360" step="any" required />
          </div>
          <div v-if="agentId === 'claude'" class="field">
            <label for="ft-budget">Budget (USD)</label>
            <input id="ft-budget" v-model="budget" class="input" type="number" min="0.01" max="50" step="0.01" required />
          </div>
        </div>
        <p v-if="submitError" class="error-text" role="alert">{{ submitError }}</p>
        <footer class="actions">
          <button type="button" class="btn" @click="emit('close')">Cancel</button>
          <button type="submit" class="btn primary" :disabled="submitting || loading || !agentId">{{ submitting ? 'Creating…' : 'Create task' }}</button>
        </footer>
      </template>
    </form>
  </ModalShell>
</template>
<style scoped>
.form { display: flex; flex-direction: column; gap: var(--gap); padding: var(--gap); }
.head, .actions { display: flex; align-items: center; justify-content: space-between; }
.actions { justify-content: flex-end; gap: var(--gap-sm); }
.row { display: grid; grid-template-columns: repeat(auto-fit, minmax(var(--tile-min-width), 1fr)); gap: var(--gap); }
.evidence { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 16rem; overflow-y: auto; padding: var(--gap); background: var(--bg); border: 1px solid var(--surface-border); border-radius: var(--radius-sm); font-size: var(--font-size-xs); }
</style>
