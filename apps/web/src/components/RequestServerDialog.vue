<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { onMounted, ref } from 'vue'
import ModalShell from '@/components/ModalShell.vue'
import {
  getJson,
  postJson,
  type AgentId,
  type McpChange,
  type McpEnvNamesPayload,
  type NewMcpChangeInput,
} from '@/lib/api'
import { MCP_AGENTS } from '@/lib/mcp'

const props = defineProps<{ initialAgent?: AgentId }>()
const emit = defineEmits<{ close: []; created: [change: McpChange] }>()

const agent = ref<AgentId>(props.initialAgent ?? 'claude')
const name = ref('')
const transport = ref<'stdio' | 'http'>('stdio')
const command = ref('')
const argsText = ref('')
const url = ref('')
const note = ref('')
const envNames = ref<string[]>([])
const selectedEnv = ref<string[]>([])
const envLoaded = ref(false)
const envError = ref<string | null>(null)

const submitting = ref(false)
const submitError = ref<string | null>(null)

onMounted(async () => {
  try {
    envNames.value = (await getJson<McpEnvNamesPayload>('/api/mcp/env-names')).names
  } catch (e) {
    envError.value = e instanceof Error ? e.message : String(e)
  } finally {
    envLoaded.value = true
  }
})

/** One argument per line; blank lines are dropped and each line is trimmed. */
function splitArgs(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0)
}

async function submit(): Promise<void> {
  submitError.value = null
  const payload: NewMcpChangeInput = {
    agent: agent.value,
    action: 'add',
    name: name.value.trim(),
    transport: transport.value,
  }
  if (transport.value === 'stdio') {
    payload.command = command.value.trim()
    payload.args = splitArgs(argsText.value)
    payload.env_names = [...selectedEnv.value]
  } else {
    payload.url = url.value.trim()
  }
  if (note.value.trim()) payload.note = note.value.trim()

  submitting.value = true
  try {
    emit('created', await postJson<McpChange>('/api/mcp/changes', payload))
  } catch (e) {
    submitError.value = e instanceof Error ? e.message : String(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <ModalShell labelledby="rs-title" @close="emit('close')">
    <form class="form" @submit.prevent="submit">
      <header class="head">
        <h2 id="rs-title" class="section-title">Request a server</h2>
        <button type="button" class="btn" aria-label="Close" @click="emit('close')">×</button>
      </header>
      <p class="hint">
        This creates a request. Nothing is written to the agent's configuration until you approve it in the list of
        changes.
      </p>

      <div class="field">
        <label for="rs-agent">Agent</label>
        <AppSelect id="rs-agent" v-model="agent" class="input" data-autofocus>
          <option v-for="a in MCP_AGENTS" :key="a.id" :value="a.id">{{ a.label }}</option>
        </AppSelect>
      </div>

      <div class="field">
        <label for="rs-name">Server name</label>
        <input id="rs-name" v-model="name" class="input" type="text" required autocomplete="off" />
      </div>

      <fieldset class="field">
        <legend>Transport</legend>
        <div class="radios">
          <label class="radio"><input v-model="transport" type="radio" name="rs-transport" value="stdio" /> stdio</label>
          <label class="radio"><input v-model="transport" type="radio" name="rs-transport" value="http" /> http</label>
        </div>
      </fieldset>

      <template v-if="transport === 'stdio'">
        <div class="field">
          <label for="rs-command">Command</label>
          <input
            id="rs-command"
            v-model="command"
            class="input mono"
            type="text"
            required
            autocomplete="off"
            spellcheck="false"
          />
        </div>

        <div class="field">
          <label for="rs-args">Arguments (one per line)</label>
          <textarea id="rs-args" v-model="argsText" class="input mono" spellcheck="false"></textarea>
        </div>

        <fieldset class="field" aria-describedby="rs-env-hint">
          <legend>Environment variables</legend>
          <p v-if="!envLoaded" class="hint" role="status">Loading…</p>
          <p v-else-if="envError" class="error-text small" role="alert">Could not load variable names: {{ envError }}</p>
          <p v-else-if="envNames.length === 0" class="hint" data-testid="env-empty">
            No variables are available yet. Add KEY=value lines to <span class="mono">~/.mac-control/.env</span>, then
            reopen this dialog. Values are never shown here.
          </p>
          <div v-else class="env-list" data-testid="env-list">
            <label v-for="n in envNames" :key="n" class="check mono">
              <input v-model="selectedEnv" type="checkbox" :value="n" />
              {{ n }}
            </label>
          </div>
          <p id="rs-env-hint" class="hint">Only the names are sent. The server reads the values from its own environment file.</p>
        </fieldset>
      </template>

      <div v-else class="field">
        <label for="rs-url">URL</label>
        <input id="rs-url" v-model="url" class="input mono" type="url" required autocomplete="off" spellcheck="false" />
      </div>

      <div class="field">
        <label for="rs-note">Note (optional)</label>
        <input id="rs-note" v-model="note" class="input" type="text" autocomplete="off" />
      </div>

      <p v-if="submitError" class="error-text" role="alert" data-testid="submit-error">{{ submitError }}</p>

      <footer class="actions">
        <button type="button" class="btn" @click="emit('close')">Cancel</button>
        <button type="submit" class="btn primary" :disabled="submitting">
          {{ submitting ? 'Requesting…' : 'Request server' }}
        </button>
      </footer>
    </form>
  </ModalShell>
</template>

<style scoped>
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

.form p {
  margin: 0;
}

.env-list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  max-height: var(--output-max-height);
  overflow-y: auto;
  padding: var(--gap-sm);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
}

.check {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-height: var(--touch-target);
  overflow-wrap: anywhere;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--gap-sm);
}
</style>
