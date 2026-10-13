<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ChipTag from '@/components/ChipTag.vue'
import ReportedValue from '@/components/ReportedValue.vue'
import RequestServerDialog from '@/components/RequestServerDialog.vue'
import AgentAccessPanel from '@/components/AgentAccessPanel.vue'
import { useNow } from '@/composables/useNow'
import { usePolledJson } from '@/composables/usePolledJson'
import {
  getJson,
  postJson,
  type AgentId,
  type McpChange,
  type McpChangesPayload,
  type McpServer,
  type McpServersPayload,
} from '@/lib/api'
import { formatSince } from '@/lib/format'
import {
  changeStatusLabel,
  changeTone,
  describeChange,
  isAccountConnector,
  mcpAgentLabel,
  serverStatusTone,
  specTarget,
} from '@/lib/mcp'
import { navIcon } from '@/router/routes'

const now = useNow()

// ---- servers: loaded once, then only when asked (a refresh health-checks every server and is slow) ----
const servers = ref<McpServersPayload | null>(null)
const serversError = ref<string | null>(null)
const serversLoading = ref(true)
const refreshing = ref(false)
let serversSeq = 0
let unmounted = false

async function loadServers(refresh: boolean): Promise<void> {
  const mine = ++serversSeq
  if (refresh) refreshing.value = true
  try {
    const result = await getJson<McpServersPayload>(`/api/mcp/servers?refresh=${refresh ? 'true' : 'false'}`)
    if (mine !== serversSeq || unmounted) return
    servers.value = result
    serversError.value = null
  } catch (e) {
    if (mine !== serversSeq || unmounted) return
    serversError.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (mine === serversSeq) {
      serversLoading.value = false
      refreshing.value = false
    }
  }
}

onMounted(() => void loadServers(false))
onBeforeUnmount(() => {
  unmounted = true
})

// ---- changes ----
const { data: changesData, error: changesError, loaded: changesLoaded, refresh: refreshChanges } =
  usePolledJson<McpChangesPayload>('/api/mcp/changes', 5000)

const changes = computed(() => changesData.value?.changes ?? [])
const pendingCount = computed(() => changes.value.filter((c) => c.status === 'pending').length)

interface Notice {
  tone: 'ok' | 'warn' | 'danger'
  text: string
}
const notice = ref<Notice | null>(null)

function failMessage(prefix: string, e: unknown): void {
  notice.value = { tone: 'danger', text: `${prefix}: ${e instanceof Error ? e.message : String(e)}` }
}

// ---- remove request ----
const requesting = ref(new Set<string>())

function removeKey(agent: AgentId, name: string): string {
  return `${agent}:${name}`
}

async function requestRemove(agent: AgentId, server: McpServer): Promise<void> {
  const key = removeKey(agent, server.name)
  if (requesting.value.has(key)) return
  requesting.value.add(key)
  notice.value = null
  try {
    await postJson<McpChange>('/api/mcp/changes', { agent, action: 'remove', name: server.name })
    notice.value = {
      tone: 'ok',
      text: `Requested removal of "${server.name}" from ${mcpAgentLabel(agent)}. Review it under Changes; nothing has been removed yet.`,
    }
    refreshChanges()
  } catch (e) {
    failMessage(`Could not request removal of "${server.name}"`, e)
  } finally {
    requesting.value.delete(key)
  }
}

// ---- request dialog ----
const showRequest = ref(false)

function onRequested(change: McpChange): void {
  showRequest.value = false
  notice.value = {
    tone: 'ok',
    text: `Requested ${change.action === 'add' ? 'adding' : 'removing'} "${change.name}" for ${mcpAgentLabel(change.agent)}. Approve it under Changes to apply it.`,
  }
  refreshChanges()
}

// ---- approve / reject ----
const deciding = ref<number | null>(null)

function adopt(updated: McpChange): void {
  const d = changesData.value
  if (d) changesData.value = { changes: d.changes.map((c) => (c.id === updated.id ? updated : c)) }
}

async function approve(c: McpChange): Promise<void> {
  if (deciding.value !== null) return
  if (!window.confirm(describeChange(c))) return
  deciding.value = c.id
  notice.value = null
  try {
    const updated = await postJson<McpChange>(`/api/mcp/changes/${c.id}/approve`)
    adopt(updated)
    if (updated.status === 'applied') {
      notice.value = { tone: 'ok', text: `Applied: ${updated.action} "${updated.name}" for ${mcpAgentLabel(updated.agent)}.` }
      void loadServers(false)
    } else if (updated.status === 'failed') {
      notice.value = { tone: 'danger', text: `The change to ${mcpAgentLabel(updated.agent)} failed. See its output below.` }
    }
  } catch (e) {
    failMessage('Could not approve', e)
  } finally {
    deciding.value = null
    refreshChanges()
  }
}

async function reject(c: McpChange): Promise<void> {
  if (deciding.value !== null) return
  deciding.value = c.id
  notice.value = null
  try {
    adopt(await postJson<McpChange>(`/api/mcp/changes/${c.id}/reject`))
  } catch (e) {
    failMessage('Could not reject', e)
  } finally {
    deciding.value = null
    refreshChanges()
  }
}
</script>

<template>
  <section class="page" aria-labelledby="mcp-title">
    <header class="head">
      <h1 id="mcp-title" class="page-title has-icon"><AppIcon :name="navIcon('mcp')" size="lg" />MCP</h1>
      <div class="head-actions">
        <button type="button" class="btn" :disabled="refreshing" :aria-busy="refreshing" @click="loadServers(true)">
          <AppIcon name="refresh" :class="{ spin: refreshing }" />
          {{ refreshing ? 'Checking servers…' : 'Refresh' }}
        </button>
        <button type="button" class="btn primary" @click="showRequest = true">
          <AppIcon name="plus" />
          Request a server
        </button>
      </div>
    </header>

    <AgentAccessPanel />
    <p class="rule has-icon" data-testid="mcp-note">
      <AppIcon name="approval" />
      Changes are requests. Nothing is written to an agent's configuration until you approve it.
    </p>

    <div
      v-if="notice"
      class="notice"
      :data-tone="notice.tone"
      :role="notice.tone === 'danger' ? 'alert' : 'status'"
      data-testid="mcp-notice"
    >
      <span>{{ notice.text }}</span>
      <button type="button" class="dismiss" aria-label="Dismiss message" @click="notice = null">×</button>
    </div>

    <p v-if="serversError" class="error-text" role="alert">Could not load servers: {{ serversError }}</p>
    <p v-else-if="serversLoading" class="muted" role="status">Loading servers…</p>
    <p v-if="refreshing" class="muted small" role="status">
      Checking every server. This can take several seconds.
    </p>

    <section
      v-for="a in servers?.agents ?? []"
      :key="a.agent"
      class="card"
      :data-agent="a.agent"
      :aria-labelledby="`mcp-${a.agent}`"
    >
      <header class="agent-head">
        <h2 :id="`mcp-${a.agent}`" class="section-title">{{ mcpAgentLabel(a.agent) }}</h2>
        <span class="muted small">
          {{ a.servers.length }} {{ a.servers.length === 1 ? 'server' : 'servers' }}
          <template v-if="a.checked_at != null"> · checked {{ formatSince(a.checked_at, now) }}</template>
        </span>
      </header>

      <p v-if="a.error" class="error-text" role="alert" data-testid="agent-error">{{ a.error }}</p>

      <p v-if="a.servers.length === 0 && !a.error" class="muted small">No MCP servers configured.</p>
      <div v-else-if="a.servers.length" class="table-scroll">
        <table class="data-table servers">
          <caption class="sr-only">MCP servers for {{ mcpAgentLabel(a.agent) }}</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Transport</th>
              <th scope="col">Target</th>
              <th scope="col">Status</th>
              <th scope="col">Source</th>
              <th scope="col"><span class="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in a.servers" :key="s.name" :data-server="s.name">
              <td class="name" data-label="Name">{{ s.name }}</td>
              <td data-label="Transport"><ReportedValue :value="s.transport" /></td>
              <td class="target" data-label="Target"><div>
                <span class="mono">{{ s.target }}</span>
                <details v-if="s.env_names?.length" class="env">
                  <summary class="muted small">{{ s.env_names.length }} environment
                    {{ s.env_names.length === 1 ? 'variable' : 'variables' }}</summary>
                  <p class="mono small env-names">{{ s.env_names.join(', ') }}</p>
                </details>
              </div></td>
              <td data-label="Status">
                <ChipTag v-if="s.status" :tone="serverStatusTone(s.status)">{{ s.status }}</ChipTag>
                <ReportedValue v-else :value="null" />
              </td>
              <td data-label="Source">{{ s.source }}</td>
              <td class="act">
                <button
                  v-if="s.removable"
                  type="button"
                  class="btn danger"
                  :disabled="requesting.has(removeKey(a.agent, s.name))"
                  :aria-label="`Remove ${s.name} from ${mcpAgentLabel(a.agent)}`"
                  @click="requestRemove(a.agent, s)"
                >
                  <AppIcon name="trash" />
                  Remove
                </button>
                <span v-else-if="isAccountConnector(s)" class="muted small">Managed in claude.ai</span>
                <span v-else class="muted small">Not removable here</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="card" aria-labelledby="changes-title">
      <header class="agent-head">
        <h2 id="changes-title" class="section-title">Changes</h2>
        <ChipTag v-if="pendingCount" tone="warn">{{ pendingCount }} pending</ChipTag>
      </header>

      <p v-if="changesError && !changesData" class="error-text" role="alert">Could not load changes: {{ changesError }}</p>
      <p v-else-if="!changesLoaded" class="muted" role="status">Loading…</p>
      <p v-else-if="changes.length === 0" class="muted small" data-testid="no-changes">No change requests yet.</p>

      <ul v-if="changes.length" class="changes">
        <li v-for="c in changes" :key="c.id" class="change" :data-change-id="c.id" :data-status="c.status">
          <div class="change-head">
            <ChipTag tone="muted">{{ mcpAgentLabel(c.agent) }}</ChipTag>
            <ChipTag :tone="c.action === 'remove' ? 'danger' : 'accent'">{{ c.action === 'add' ? 'Add' : 'Remove' }}</ChipTag>
            <span class="change-name">{{ c.name }}</span>
            <ChipTag :tone="changeTone(c.status)" data-testid="change-status">{{ changeStatusLabel(c.status) }}</ChipTag>
          </div>

          <p v-if="c.action === 'add'" class="spec mono" data-testid="change-spec">
            <span v-if="c.spec.transport" class="muted">{{ c.spec.transport }}</span>
            {{ specTarget(c.spec) ?? 'no command or URL' }}
          </p>
          <p v-if="c.spec.env_names?.length" class="small muted" data-testid="change-env">
            Environment variables (names only): <span class="mono">{{ c.spec.env_names.join(', ') }}</span>
          </p>
          <p v-if="c.note" class="small note">{{ c.note }}</p>

          <p class="small muted times">
            <span>Requested {{ formatSince(c.created_at, now) }}</span>
            <span v-if="c.decided_at != null">Decided {{ formatSince(c.decided_at, now) }}</span>
          </p>

          <div v-if="c.status === 'pending'" class="decide">
            <button type="button" class="btn primary" :disabled="deciding !== null" @click="approve(c)">
              <AppIcon name="check" />
              Approve
            </button>
            <button type="button" class="btn danger" :disabled="deciding !== null" @click="reject(c)">
              <AppIcon name="close" />
              Reject
            </button>
          </div>

          <details v-if="c.output" class="output" :open="c.status === 'failed'">
            <summary class="small">Output</summary>
            <pre class="mono out" data-testid="change-output">{{ c.output }}</pre>
          </details>
        </li>
      </ul>
    </section>

    <RequestServerDialog v-if="showRequest" @close="showRequest = false" @created="onRequested" />
  </section>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--gap);
}

.head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.rule {
  margin: 0;
  padding: var(--gap-sm) var(--gap);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  background: var(--panel);
  color: var(--text-muted);
}

.notice {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap);
  padding: var(--gap-sm) var(--gap);
  border-radius: var(--radius);
  border: 1px solid var(--panel-border);
  overflow-wrap: anywhere;
}

.notice[data-tone='ok'] {
  background: var(--ok-soft);
  border-color: var(--ok);
}

.notice[data-tone='warn'] {
  background: var(--warn-soft);
  border-color: var(--warn);
}

.notice[data-tone='danger'] {
  background: var(--danger-soft);
  border-color: var(--danger);
}

.dismiss {
  all: unset;
  cursor: pointer;
  min-width: var(--touch-target);
  min-height: var(--touch-target);
  margin: calc(-1 * var(--gap-sm)) calc(-1 * var(--gap)) calc(-1 * var(--gap-sm)) 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius);
}

.dismiss:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus-ring);
  outline-offset: calc(-1 * var(--focus-ring-width));
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }
}

.agent-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.name {
  font-weight: var(--font-weight-strong);
  overflow-wrap: anywhere;
}

.target {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.env {
  margin-top: var(--gap-xs);
}

.env-names {
  margin: var(--gap-xs) 0 0;
}

.act {
  white-space: nowrap;
}

/* On a phone each server becomes a small labelled block instead of a cramped table row. */
@media (max-width: 767.98px) {
  .servers thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }

  .servers,
  .servers tbody,
  .servers tr,
  .servers td {
    display: block;
    width: 100%;
  }

  .servers tr {
    padding: var(--gap-sm) 0;
    border-bottom: 1px solid var(--panel-border);
  }

  .servers td {
    display: grid;
    grid-template-columns: 6.5rem minmax(0, 1fr);
    gap: var(--gap-sm);
    padding: var(--gap-xs) 0;
    border: 0;
  }

  .servers td::before {
    content: attr(data-label);
    color: var(--text-muted);
    font-weight: var(--font-weight-strong);
  }

  .servers td.act {
    display: block;
  }

  .servers td.act::before {
    content: none;
  }
}

.changes {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  margin: 0;
  padding: 0;
  list-style: none;
}

.change {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  min-width: 0;
  padding: var(--gap);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  background: var(--bg);
}

.change[data-status='pending'] {
  border-color: var(--warn);
}

.change p {
  margin: 0;
}

.change-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

.change-name {
  font-weight: var(--font-weight-strong);
  overflow-wrap: anywhere;
}

.spec {
  overflow-wrap: anywhere;
}

.note {
  overflow-wrap: anywhere;
}

.times {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs) var(--gap);
}

.decide {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.out {
  max-height: var(--output-max-height);
  margin: var(--gap-sm) 0 0;
  padding: var(--gap-sm);
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
}
</style>
