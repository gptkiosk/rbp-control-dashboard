<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getJson, postJson } from '@/lib/api'
import type { Project } from '@/lib/projects'
import LoadingCard from './LoadingCard.vue'
import AppSelect from './AppSelect.vue'

const props = defineProps<{ project: Project }>()
const emit = defineEmits<{ changed: []; pause: [] }>()
interface Workspace {
  project_id: number; revision: number; host: string; repository?: string | null; observed_at: number; packet?: string
  workspace: { path: string; branch: string | null; head: string | null; changed: boolean | null; state: string; snapshot: string }
  reservation: { id: string; project_id: number; label: string; stale: boolean } | null
  active_runs: { id: number; task_id: number | null; agent: string }[]
  next_tasks: { id: number; title: string; link: string }[]
  review_tasks: { id: number; title: string; link: string }[]
  handoffs: { id: number; status: string; text: string; created_at: number }[]
}
const state = ref<Workspace | null>(null), busy = ref(false), error = ref(''), message = ref('')
const summary = ref(''), location = ref(''), showPacket = ref(false)
const codingApp = ref('Codex')
let pending: { key: string; id: string } | null = null
let sequence = 0
const paths = computed(() => [...new Set([props.project.document.working_dir,
  ...(props.project.document.repository?.folder ? [`${props.project.document.working_dir}/${props.project.document.repository.folder}`] : []),
  ...Object.values(props.project.workspaces).map(w => w.path),
  ...props.project.tasks.filter(t => t.role === 'story' && t.revision === (props.project.approved_revision || props.project.revision)).map(t => t.working_dir).filter((p): p is string => !!p)])])
const packet = computed(() => (state.value?.packet || '').replace(/Project: (\/projects[^\n]*)/, `Project: ${window.location.origin}$1`))
const canReserve = computed(() => state.value?.workspace.state === 'ready' && !state.value.reservation && !state.value.active_runs.length && ['paused','draft','review','complete'].includes(props.project.state))
async function refresh() {
  const request = ++sequence
  busy.value = true; error.value = ''; message.value = ''
  try {
    const result = await getJson<Workspace>(`/api/projects/coordinator?operation=workspace&project_id=${props.project.id}&working_dir=${encodeURIComponent(location.value)}`)
    if (request === sequence) state.value = result
  } catch (e) { if (request === sequence) { state.value = null; error.value = String(e instanceof Error ? e.message : e) } }
  finally { if (request === sequence) busy.value = false }
}
watch(() => [props.project.id, props.project.revision, props.project.state], () => {
  if (!paths.value.includes(location.value)) location.value = paths.value[0] || ''
  void refresh()
}, { immediate: true })
function selectLocation() { state.value = null; summary.value = ''; void refresh() }
async function copy() {
  showPacket.value = true
  try { await navigator.clipboard.writeText(packet.value); message.value = 'Handoff copied.' }
  catch { message.value = 'Select and copy the handoff below.' }
}
async function act(action: 'reserve' | 'handoff') {
  if (!state.value || busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    const key = JSON.stringify([action, props.project.id, props.project.revision, location.value, state.value.workspace.snapshot, summary.value, state.value.reservation?.id, codingApp.value])
    if (pending?.key !== key) pending = { key, id: crypto.randomUUID() }
    await postJson(`/api/projects/${props.project.id}/workspace/${action}`, {
      revision: props.project.revision, working_dir: location.value, snapshot: state.value.workspace.snapshot,
      operation_id: pending.id, label: codingApp.value, ...(action === 'handoff' ? { summary: summary.value, reservation_id: state.value.reservation?.id || null } : {}),
    })
    pending = null; summary.value = ''; emit('changed'); await refresh()
    message.value = action === 'reserve' ? 'Reserved. Copy the handoff into your coding app.' : 'Handoff recorded as reported work. Reservation released; dispatch stays paused.'
  } catch (e) { error.value = String(e instanceof Error ? e.message : e) }
  finally { busy.value = false }
}
</script>

<template>
  <section class="card workspace-panel" aria-labelledby="workspace-title">
    <header><h2 id="workspace-title">Workspace</h2><button class="btn" :disabled="busy" @click="refresh">Refresh</button></header>
    <p class="muted">Share this location and handoff with the next agent.</p>
    <label v-if="paths.length > 1">Location<AppSelect v-model="location" :disabled="busy" aria-label="Project workspace" @change="selectLocation"><option v-for="path in paths" :key="path" :value="path">{{ path }}</option></AppSelect></label>
    <LoadingCard v-if="busy" title="Reading workspace…" detail="Checking Git state and recorded work on this host." :rows="2" />
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <template v-if="state">
      <p><strong>{{ state.host }}</strong> · {{ state.workspace.branch || 'No branch' }} · {{ state.workspace.head?.slice(0, 7) || 'No commit' }} · {{ state.workspace.changed === null ? 'State unavailable' : state.workspace.changed ? 'Uncommitted changes' : 'Clean' }}</p>
      <p class="path">{{ state.workspace.path }}</p>
      <p class="muted small">Repository: {{ state.repository || 'Not registered — confirm before a remote handoff' }}</p>
      <p class="muted small">Observed {{ new Date(state.observed_at * 1000).toLocaleString() }}. This path belongs to this host.</p>
      <p v-if="state.active_runs.length" class="notice-warn">{{ state.active_runs.length }} active app run(s) use this area. Wait before starting another writer.</p>
      <label v-if="!state.reservation">Coding app<AppSelect v-model="codingApp" editable :disabled="busy" aria-label="External coding app"><option value="Codex">Codex</option><option value="Claude Code">Claude Code</option><option value="Other">Other</option></AppSelect></label>
      <p v-if="state.reservation" class="notice-warn">Reserved for {{ state.reservation.label }}{{ state.reservation.stale ? ' · overdue: confirm the external process has stopped before releasing' : '' }}. App runs wait until its handoff is recorded.</p>
      <div class="actions"><button class="btn primary" :disabled="busy" @click="copy">Copy handoff</button><button v-if="!state.reservation" class="btn" :disabled="busy || !canReserve" @click="act('reserve')">Continue in coding app</button><button v-if="project.state === 'active'" class="btn" :disabled="busy" @click="emit('pause')">Pause dispatch</button></div>
      <p v-if="!state.reservation && project.state === 'active'" class="muted small">Pause dispatch before reserving this folder for external edits.</p>
      <p v-if="state.workspace.state !== 'ready'" class="notice-warn">No usable Git snapshot here. Select the repository location or configure its workspace before reserving it.</p>
      <details v-if="showPacket"><summary>Handoff to paste into a coding app</summary><textarea class="input" aria-label="Shared workspace handoff" readonly rows="10" :value="packet" /></details>
      <section v-if="state.review_tasks.length"><h3>Needs attention</h3><p v-for="task in state.review_tasks" :key="task.id"><RouterLink :to="task.link">#{{ task.id }} {{ task.title }}</RouterLink></p></section>
      <section v-if="state.next_tasks.length"><h3>Next ready work</h3><p v-for="task in state.next_tasks" :key="task.id"><RouterLink :to="task.link">#{{ task.id }} {{ task.title }}</RouterLink></p></section>
      <details v-if="state.handoffs.length"><summary>Last recorded work</summary><article v-for="h in state.handoffs" :key="h.id"><strong>{{ h.status }} · {{ new Date(h.created_at * 1000).toLocaleString() }}</strong><pre>{{ h.text }}</pre></article></details>
      <details><summary>Record external work &amp; release workspace</summary><p class="muted small">Confirm the external agent has stopped. Record changes, checks and next steps. This does not accept a task or resume dispatch.</p><form @submit.prevent="act('handoff')"><label>Handoff<textarea v-model="summary" class="input" rows="5" maxlength="6000" required placeholder="Changes and commit, checks/results, remaining work and next task" /></label><button class="btn" :disabled="busy || summary.trim().length < 3 || !!state.active_runs.length || (!!state.reservation && state.reservation.project_id !== project.id)">Record handoff</button></form></details>
    </template>
    <p v-if="message" role="status">{{ message }}</p>
  </section>
</template>

<style scoped>
header,.actions{display:flex;align-items:center;justify-content:space-between;gap:var(--gap);flex-wrap:wrap}h2,h3{font-size:var(--font-size-lg)}section,details{margin-top:var(--gap)}label{display:grid;gap:var(--gap-sm);margin:var(--gap) 0}.path,pre{overflow-wrap:anywhere;white-space:pre-wrap}textarea{width:100%;max-width:100%;resize:vertical}article{border-top:1px solid var(--surface-border);padding:var(--gap-sm) 0}summary{cursor:pointer}.small{font-size:var(--font-size-xs)}
</style>
