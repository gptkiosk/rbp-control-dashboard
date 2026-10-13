<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import AppIcon from '@/components/AppIcon.vue'
import { directoryName, directoryDetail } from '@/lib/selectLabels'
import { computed, onMounted, ref, watch } from 'vue'
import ModalShell from '@/components/ModalShell.vue'
import OpenClawTarget from '@/components/OpenClawTarget.vue'
import {
  getJson,
  postJson,
  type Agent,
  type AgentId,
  type AgentsPayload,
  type CardMode,
  type ChatThread,
  type NewChatInput,
  type Workdir,
  type WorkdirsPayload,
} from '@/lib/api'
import { isManagerAgent } from '@/lib/cards'

const emit = defineEmits<{ close: []; created: [thread: ChatThread] }>()

const agents = ref<Agent[]>([])
const workdirs = ref<Workdir[]>([])
const loading = ref(true)
const loadError = ref<string | null>(null)

const title = ref('')
const agentId = ref<AgentId | ''>('')
const model = ref('')
const mode = ref<CardMode>('read')
const workingDir = ref('')
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
})

async function submit(): Promise<void> {
  submitError.value = null
  if (!agentId.value) {
    submitError.value = 'Choose an agent.'
    return
  }
  const payload: NewChatInput = { agent: agentId.value, working_dir: workingDir.value, mode: mode.value }
  if (title.value.trim()) payload.title = title.value.trim()
  if (model.value.trim()) payload.model = model.value.trim()
  if (agentId.value === 'openclaw') payload.agent_target = target.value.trim() || 'mm-main'

  submitting.value = true
  try {
    const thread = await postJson<ChatThread>('/api/chat/threads', payload)
    emit('created', thread)
  } catch (e) {
    submitError.value = e instanceof Error ? e.message : String(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <ModalShell labelledby="new-chat-title" @close="emit('close')">
    <form class="form" @submit.prevent="submit">
      <header class="head">
        <div class="intro">
          <span class="chat-mark"><AppIcon name="chat" size="lg" /></span>
          <div>
            <h2 id="new-chat-title" class="section-title">New chat</h2>
            <p class="hint">Choose an agent and a workspace.</p>
          </div>
        </div>
        <button type="button" class="btn close" aria-label="Close" @click="emit('close')"><AppIcon name="close" /></button>
      </header>

      <p v-if="loading" class="muted" role="status">Loading agents…</p>
      <p v-if="loadError" class="error-text" role="alert">
        Could not load agents or working directories: {{ loadError }}
      </p>

      <div class="setup-grid">
        <div class="field">
          <label for="nchat-agent">Agent</label>
          <AppSelect id="nchat-agent" v-model="agentId" class="input" required data-autofocus>
            <option v-for="a in agents" :key="a.id" :value="a.id" :disabled="!a.available" :data-label="a.name" :data-description="a.available ? (a.role === 'manager' ? 'Manager' : 'Worker') : 'Not installed'">
              {{ a.name }}{{ isManagerAgent(a.id) ? ' (manager)' : ''
              }}{{ a.available ? '' : ' (not installed)' }}
            </option>
          </AppSelect>
        </div>

        <div class="field">
          <label for="nchat-model">Model</label>
          <AppSelect
            id="nchat-model" v-model="model" class="input" editable
            :placeholder="agent?.default_model ?? 'Agent default'"
          >
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
          </AppSelect>
        </div>
      </div>

      <div class="field">
        <label for="nchat-title">Title (optional)</label>
        <input id="nchat-title" v-model="title" class="input" type="text" autocomplete="off" placeholder="Name this conversation" />
      </div>

      <fieldset class="field">
        <legend>Mode</legend>
        <div class="radios mode-choices">
          <label class="mode-choice" :class="{ selected: mode === 'read' }">
            <input v-model="mode" class="sr-only" type="radio" name="nchat-mode" value="read" aria-label="Read" />
            <span><strong>Read</strong><small>Inspect and plan</small></span>
            <AppIcon v-if="mode === 'read'" name="check" />
          </label>
          <label class="mode-choice" :class="{ selected: mode === 'edit' }">
            <input v-model="mode" class="sr-only" type="radio" name="nchat-mode" value="edit" aria-label="Edit" />
            <span><strong>Edit</strong><small>Make workspace changes</small></span>
            <AppIcon v-if="mode === 'edit'" name="check" />
          </label>
        </div>
        <p v-if="agent && !agent.enforces_mode" class="hint" data-testid="advisory-note">
          Read/Edit is advisory for {{ agent.name }}. {{ agent.notes }}
        </p>
      </fieldset>

      <div class="field">
        <label for="nchat-dir">Working directory</label>
        <AppSelect id="nchat-dir" v-model="workingDir" class="input" required>
          <option v-for="w in workdirs" :key="w.path" :value="w.path" :data-label="directoryName(w.path)" :data-description="directoryDetail(w.path, w.branch)">{{ dirLabel(w) }}</option>
        </AppSelect>
        <p v-if="editOnMain" class="warning-text" role="status" data-testid="main-warning">
          Edits on main need your approval
        </p>
      </div>

      <OpenClawTarget
        v-if="agentId === 'openclaw'"
        id="nchat-target"
        v-model="target"
        :agents="agent?.subagents?.agents"
      />

      <p v-if="submitError" class="error-text" role="alert" data-testid="submit-error">{{ submitError }}</p>

      <footer class="actions">
        <button type="button" class="btn" @click="emit('close')">Cancel</button>
        <button type="submit" class="btn primary" :disabled="submitting || loading || !agentId">
          {{ submitting ? 'Creating…' : 'Start chat' }}
          <AppIcon name="chevron-right" />
        </button>
      </footer>
    </form>
  </ModalShell>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
  padding: var(--gap-lg);
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
}

.intro { display: flex; gap: var(--gap); align-items: center; min-width: 0; }
.intro .hint { margin-top: var(--gap-xs); }
.chat-mark { display: flex; align-items: center; justify-content: center; flex-shrink: 0; width: var(--dialog-icon-size); height: var(--dialog-icon-size); color: var(--accent); background: var(--accent-soft); border: 1px solid var(--select-border); border-radius: var(--radius); }
.close { width: var(--dialog-icon-size); min-width: var(--dialog-icon-size); padding: 0; }
.setup-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--gap); }
.setup-grid :deep(.select-control) { min-height: var(--dialog-control-height); }
.mode-choices { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--gap-sm); }
.mode-choice { position: relative; min-width: 0; display: flex; align-items: center; justify-content: space-between; gap: var(--gap-sm); padding: var(--gap); border: 1px solid var(--select-border); border-radius: var(--radius); background: var(--glass-bg); cursor: pointer; }
.mode-choice span { display: flex; flex-direction: column; gap: var(--gap-xs); min-width: 0; }
.mode-choice small { font-size: var(--font-size-xs); color: var(--text-muted); }
.mode-choice.selected { background: var(--select-hover); border-color: var(--accent); }
.mode-choice .icon { color: var(--accent); }
.mode-choice:hover { border-color: var(--accent); }
.mode-choice:focus-within { outline: var(--focus-ring-width) solid var(--focus-ring); outline-offset: var(--focus-ring-offset); }

.actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--gap-sm);
  padding-top: var(--gap-lg);
  border-top: 1px solid var(--glass-border);
}
.actions .btn { min-height: var(--select-height); }

@media (max-width: 600px) {
  .form { padding: var(--gap); gap: var(--gap); }
  .setup-grid { grid-template-columns: 1fr; }
  .intro { gap: var(--gap-sm); }
  .actions { padding-top: var(--gap); }
}
</style>
