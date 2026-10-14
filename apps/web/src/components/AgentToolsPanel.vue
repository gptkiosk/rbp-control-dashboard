<script setup lang="ts">
import RecommendedAgentMix from '@/components/RecommendedAgentMix.vue'
import MembershipPrerequisites from './MembershipPrerequisites.vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'

type Action = 'install' | 'update' | 'remove' | 'rollback'
const ACTIONS: Action[] = ['install', 'update', 'rollback', 'remove']
const POLL_MS = 3000, NOT_STARTED_POLLS = 10, MAX_POLLS = 1000 // about 50 minutes; 30 seconds before "never started"

interface Tool {
  id: string; name: string; pinned_version: string; installed: boolean; installed_version: string | null
  installation_source?: 'native' | 'managed' | null; previous_version: string | null; installed_at: number | null; size_mb: number; commands: string[]; requires: string[]
  login: { command: string; note: string }; path: string | null
  actions: Record<Action, string[] | null> // null: not offered now; []: allowed; otherwise the reasons it is refused
}
interface Status {
  product: string; platform: string; root: string; tools: Tool[]
  runtimes: { id: string; name: string; pinned_version: string; installed_version: string | null }[]
  host: { os: string; machine: string; bits: number; disk_free_mb: number; mem_total_mb: number | null; mem_available_mb: number | null }
  system_packages: { apt_command: string | null; missing_required: string[]; missing_recommended: string[]; details: Record<string, string>; note: string }
  tx: { id: string; tool: string; action: string; phase: string } | null
  last: { tx: string | null; tool: string | null; action: string | null; outcome: string; detail: string } | null
  running: boolean; log: string[]; notes: Record<string, string | null>; catalog_checked: string
}
interface Plan {
  tool: string; name: string; action: Action; from: string | null; to: string | null; commands: string[]; plan_sha256: string
  downloads: { url: string; sha256: string; size: number }[]
  runtimes: { id: string; name: string; version: string; action: string; from: string | null }[]
  note: string | null; removes: string[]; unchanged: string[]; login: { command: string; note: string } | null
  system_packages: { apt_command: string | null; missing_required: string[]; missing_recommended: string[]; note: string }
  disk: { free_mb: number; required_mb: number; min_free_mb: number; headroom_mb: number }
  memory: { total_mb: number | null; available_mb: number | null; recommended_mb: number }
  host: { os: string; machine: string; bits: number }
  refusals: string[]; warnings: string[]
}

const VERB: Record<Action, string> = { install: 'Install', update: 'Upgrade', remove: 'Remove', rollback: 'Roll back' }
const status = ref<Status | null>(null), plan = ref<Plan | null>(null)
const confirmed = ref(false), busy = ref(false), copied = ref('')
const error = ref(''), notice = ref('')
const watching = ref<{ tool: string; action: Action; beforeTx: string | null; sawTx: boolean; polls: number } | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined

const working = computed(() => !!status.value?.tx || !!status.value?.running || !!watching.value)
const hostLine = computed(() => {
  const h = status.value?.host
  if (!h) return ''
  const mem = h.mem_total_mb ? `${(h.mem_total_mb / 1024).toFixed(1)} GB memory` : 'memory not reported'
  return `${status.value!.platform} · ${h.os} · ${h.bits}-bit · ${mem} · ${(h.disk_free_mb / 1024).toFixed(1)} GB free disk`
})
const progress = computed(() => {
  const tx = status.value?.tx
  return tx ? `${VERB[tx.action as Action] ?? tx.action} ${nameOf(tx.tool)}: ${tx.phase}.` : 'Waiting for the install helper to start…'
})
const confirmTitle = computed(() => plan.value ? `${VERB[plan.value.action]} ${plan.value.name}${plan.value.to ? ` ${plan.value.to}` : ''}` : '')
const canAct = (t: Tool, a: Action) => !busy.value && !working.value && t.actions[a] !== null && t.actions[a] !== undefined
const offered = (t: Tool) => ACTIONS.filter(a => t.actions[a] !== null && t.actions[a] !== undefined)
const reasons = (t: Tool) => ACTIONS.flatMap(a => (t.actions[a] ?? []).map(r => ({ a, r }))).filter((x, i, all) => all.findIndex(y => y.r === x.r) === i)
const stateText = (t: Tool) => !t.installed ? `Not installed. Latest verified: ${t.pinned_version}.`
  : !t.installed_version ? `Installed${t.installation_source === 'native' ? ' outside the dashboard' : ''}; version unavailable. Latest verified: ${t.pinned_version}.`
  : `Installed ${t.installed_version}${t.installation_source === 'native' ? ' (native)' : ''}. ${t.installed_version === t.pinned_version ? 'Up to date.' : `Latest verified: ${t.pinned_version}.`}${t.previous_version ? ` Previous ${t.previous_version} kept for roll back.` : ''}`

function nameOf(id: string) { return status.value?.tools.find(t => t.id === id)?.name ?? id }
function when(seconds: number | null | undefined) { return seconds ? new Date(seconds * 1000).toLocaleString() : 'an unknown time' }
function mb(n: number | null | undefined) { return n == null ? 'not reported' : n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${n} MB` }
function bytes(n: number) { return n >= 1048576 ? mb(Math.round(n / 1048576)) : `${Math.max(1, Math.round(n / 1024))} KB` }

function denied(e: unknown, fallback: string) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return 'Operator sign-in is required to see or change agent tools.'
  return e instanceof Error ? e.message : fallback
}
// A refusal carries {message, problems}; the client flattens it into the message text, so unpack it when it is JSON.
function refusal(e: unknown, fallback: string) {
  if (e instanceof ApiError && (e.status === 409 || e.status === 503)) {
    try {
      const body = JSON.parse(e.message) as { message?: string; problems?: string[] }
      return [body.message, ...(body.problems ?? [])].filter(Boolean).join(' ')
    } catch { /* plain message */ }
  }
  return denied(e, fallback)
}

async function read(): Promise<boolean> {
  try {
    status.value = await getJson<Status>('/api/agent-installs')
    error.value = ''
    return true
  } catch (e) {
    error.value = refusal(e, 'Agent tools could not be read right now.')
    return false
  }
}

async function ask(tool: Tool, action: Action) {
  busy.value = true; error.value = ''; notice.value = ''; confirmed.value = false; plan.value = null
  try {
    plan.value = await postJson<Plan>('/api/agent-installs/plan', { tool: tool.id, action })
  } catch (e) { error.value = refusal(e, 'The plan could not be made.') } finally { busy.value = false }
}
function cancel() { plan.value = null; confirmed.value = false }

async function submit() {
  const p = plan.value
  if (!p || !confirmed.value || p.refusals.length) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    await postJson('/api/agent-installs/run', { tool: p.tool, action: p.action, plan_sha256: p.plan_sha256, confirm: true })
    watching.value = { tool: p.tool, action: p.action, beforeTx: status.value?.last?.tx ?? null, sawTx: false, polls: 0 }
    plan.value = null; confirmed.value = false
    notice.value = `${VERB[p.action]} of ${p.name} started on the host. Progress is shown below.`
    timer = setTimeout(poll, POLL_MS)
  } catch (e) {
    await read()
    error.value = refusal(e, 'The helper could not be started.')
  } finally { busy.value = false }
}

async function poll() {
  const w = watching.value
  if (!w) return
  const ok = await read()
  if (!ok) return stop(error.value)
  const s = status.value!
  if (s.tx || s.running) w.sawTx = true
  if (!s.tx && !s.running && (w.sawTx || (s.last?.tx ?? null) !== w.beforeTx)) return finish()
  w.polls++
  if (!s.tx && !s.running && !w.sawTx && w.polls >= NOT_STARTED_POLLS) return stop('The install helper has not started. Nothing was changed as far as the status shows. See the helper log on the host.')
  if (w.polls >= MAX_POLLS) return stop('Still waiting after about 50 minutes. Check the helper log on the host; nothing more is started from here.')
  timer = setTimeout(poll, POLL_MS)
}
function finish() {
  const last = status.value?.last
  watching.value = null
  if (!last) return stop('The helper finished, but no outcome was recorded.')
  if (last.outcome === 'done') notice.value = last.detail
  else error.value = `Not completed (${last.outcome}): ${last.detail}`
}
function stop(message: string) { watching.value = null; error.value = message }

async function copy(text: string, label: string) {
  try { await navigator.clipboard.writeText(text); copied.value = label } catch { copied.value = '' ; notice.value = 'Copying is not available here. Select the command and copy it by hand.' }
}

onMounted(read)
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>
<template>
  <section id="agent-tools" class="card agent-tools" aria-labelledby="agent-tools-title">
    <h2 id="agent-tools-title">Agent tools</h2><p>Following the setup wizard? Install the runtimes you selected here, then use the displayed native setup or sign-in commands on this host. Installation and account configuration are separate steps.</p><div class="actions"><RouterLink to="/setup?step=2" class="btn">Return to coordinator setup</RouterLink><RouterLink to="/setup?step=4" class="btn">Return to membership setup</RouterLink></div><p class="muted small">In the wizard, choose Refresh checks after installing. An installed executable does not by itself verify provider access or enable task dispatch.</p>
    <p class="muted">Install Claude Code, Codex CLI, Grok Build, OpenClaw and Hermes on this host, for this user only. Every version is pinned and hash-checked in this release. Nothing needs sudo, nothing is installed without your confirmation, and nothing here signs in to a tool or touches a key.</p>
    <RecommendedAgentMix platform="pi" />
    <MembershipPrerequisites />
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <template v-if="status">
      <p class="muted small" data-test="host">{{ hostLine }} · installs under {{ status.root }}</p>
      <p v-if="working" class="status" role="status" data-test="progress">{{ progress }}</p>
      <details v-if="working && status.log.length" open>
        <summary>Helper log (last {{ status.log.length }} lines)</summary>
        <pre class="log">{{ status.log.join('\n') }}</pre>
      </details>

      <ul class="tools">
        <li v-for="t in status.tools" :key="t.id" class="tool" :data-tool="t.id">
          <div class="head">
            <h3>{{ t.name }}</h3>
            <span class="state" data-test="state">{{ stateText(t) }}</span>
          </div>
          <p class="muted small">About {{ mb(t.size_mb) }} on disk. Command{{ t.commands.length > 1 ? 's' : '' }}: <code>{{ t.commands.join(', ') }}</code><template v-if="t.path"> · <code>{{ t.path }}</code></template></p>
          <p v-if="status.notes[t.id]" class="muted small">{{ status.notes[t.id] }}</p>
          <div class="actions">
            <button v-for="a in offered(t)" :key="a" class="btn" :class="{ primary: a === 'install' || a === 'update' }" :disabled="!canAct(t, a) || (t.actions[a] ?? []).length > 0" :data-action="a"
              @click="ask(t, a)">{{ VERB[a] }}{{ a === 'install' || a === 'update' ? ` ${t.pinned_version}` : a === 'rollback' && t.previous_version ? ` to ${t.previous_version}` : '' }}</button>
          </div>
          <ul v-if="reasons(t).length" class="why" aria-label="Why a button is off"><li v-for="x in reasons(t)" :key="x.r" class="muted small">{{ VERB[x.a] }}: {{ x.r }}</li></ul>
          <div v-if="t.installed" class="login" :data-login="t.id">
            <p class="small"><strong>Sign in yourself.</strong> This panel never signs in. In a terminal on this host run:</p>
            <p class="cmd"><code>{{ t.login.command }}</code> <button class="btn small-btn" @click="copy(t.login.command, t.id)">{{ copied === t.id ? 'Copied' : 'Copy' }}</button></p>
            <p class="muted small">{{ t.login.note }} Put API keys in <RouterLink to="/profile#credentials-profile">Private credentials</RouterLink> (write-only); never paste a key into this page.</p>
          </div>
        </li>
      </ul>

      <section v-if="status.system_packages.apt_command" class="packages" aria-labelledby="pkg-title">
        <h3 id="pkg-title">Optional system packages</h3>
        <p class="small">Some of these make the tools faster or fuller. The dashboard never runs this command: copy it into a terminal if you want them.</p>
        <p class="cmd" data-test="apt"><code>{{ status.system_packages.apt_command }}</code> <button class="btn small-btn" @click="copy(status.system_packages.apt_command!, 'apt')">{{ copied === 'apt' ? 'Copied' : 'Copy' }}</button></p>
        <ul class="muted small"><li v-for="(why, name) in status.system_packages.details" :key="name"><strong>{{ name }}</strong>: {{ why }}</li></ul>
      </section>

      <section v-if="plan" class="confirm" aria-labelledby="agent-confirm-title" data-test="confirm">
        <h3 id="agent-confirm-title">{{ confirmTitle }}</h3>
        <dl class="facts">
          <dt>Version</dt><dd>{{ plan.from ?? 'not installed' }} → {{ plan.to ?? 'removed' }}</dd>
          <dt>Host</dt><dd>{{ plan.host.os }} · {{ plan.host.machine }} · {{ plan.host.bits }}-bit</dd>
          <dt>Free disk</dt><dd>{{ mb(plan.disk.free_mb) }} free; this needs about {{ mb(plan.disk.required_mb) }} plus {{ mb(plan.disk.headroom_mb) }} working room (minimum free: {{ mb(plan.disk.min_free_mb) }})</dd>
          <dt>Memory</dt><dd>{{ mb(plan.memory.total_mb) }} total, {{ mb(plan.memory.available_mb) }} available (4 GB or more recommended)</dd>
          <template v-if="plan.runtimes.length"><dt>Needs</dt><dd><span v-for="r in plan.runtimes" :key="r.id" class="runtime">{{ r.name }} {{ r.version }} ({{ r.action === 'present' ? 'already installed' : r.action === 'update' ? `update from ${r.from}` : 'will be installed' }})</span></dd></template>
          <template v-if="plan.removes.length"><dt>Also removes</dt><dd>{{ plan.removes.join('; ') }}</dd></template>
          <template v-if="plan.downloads.length"><dt>Downloads</dt><dd><div v-for="d in plan.downloads" :key="d.url" class="mono">{{ d.url }} · {{ bytes(d.size) }} · sha256 {{ d.sha256 }}</div></dd></template>
        </dl>
        <p v-if="plan.note" class="muted small">{{ plan.note }}</p>
        <h4>Commands, in order</h4>
        <ol class="commands"><li v-for="c in plan.commands" :key="c"><code>{{ c }}</code></li></ol>
        <p v-if="!plan.commands.length" class="muted small">No commands to show.</p>
        <ul v-if="plan.warnings.length" class="warn" aria-label="Warnings"><li v-for="w in plan.warnings" :key="w" class="notice-warn">{{ w }}</li></ul>
        <ul v-if="plan.refusals.length" class="warn" aria-label="Why this cannot run"><li v-for="r in plan.refusals" :key="r" class="notice-warn" role="alert">{{ r }}</li></ul>
        <p v-if="plan.system_packages.apt_command && plan.action !== 'remove'" class="small">Optional, run by you: <code>{{ plan.system_packages.apt_command }}</code></p>
        <p class="small"><strong>Not changed by this:</strong> {{ plan.unchanged.join('; ') }}.</p>
        <p v-if="plan.login" class="small">After it finishes, sign in yourself with <code>{{ plan.login.command }}</code>.</p>
        <label class="check"><input v-model="confirmed" type="checkbox" :disabled="plan.refusals.length > 0" />I have read this and want to continue.</label>
        <div class="actions">
          <button class="btn primary" :disabled="!confirmed || busy || plan.refusals.length > 0 || working" @click="submit">{{ VERB[plan.action] }} {{ plan.name }}</button>
          <button class="btn" :disabled="busy" @click="cancel">Cancel</button>
        </div>
      </section>

      <p v-if="status.last && !working" class="muted small" data-test="last">Last operation: {{ status.last.detail }} ({{ status.last.outcome }})</p>
      <p class="muted small">Pinned versions checked {{ status.catalog_checked }}. Roll back switches to the previous version kept on this host; Remove deletes the program but keeps your tool data (for example ~/.hermes).</p>
    </template>
  </section>
</template>
<style scoped>
.agent-tools { margin: var(--gap-lg) 0; display: grid; gap: var(--gap-sm); }
h2, h3, h4 { margin: 0; }
.small { font-size: var(--font-size-xs); margin: 0; }
.status { font-weight: 600; margin: 0; }
.tools { display: grid; gap: var(--gap); padding: 0; margin: 0; list-style: none; }
.tool, .confirm, .packages { display: grid; gap: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); padding: var(--gap); justify-items: start; }
.head { display: flex; gap: var(--gap); flex-wrap: wrap; align-items: baseline; }
.state { font-size: var(--font-size-sm); }
.actions { display: flex; gap: var(--gap); flex-wrap: wrap; align-items: center; }
.why { margin: 0; padding-left: var(--gap); }
.cmd { display: flex; gap: var(--gap-sm); align-items: center; flex-wrap: wrap; margin: 0; }
code, .mono { font-family: var(--font-mono, ui-monospace, monospace); font-size: var(--font-size-xs); overflow-wrap: anywhere; }
.facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: var(--gap-xs) var(--gap); margin: 0; font-size: var(--font-size-sm); }
.facts dt { color: var(--text-muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.runtime { display: block; }
.commands { margin: 0; padding-left: var(--gap); display: grid; gap: var(--gap-xs); }
.warn { margin: 0; padding: 0; list-style: none; display: grid; gap: var(--gap-xs); }
.log { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 14rem; overflow: auto; margin: 0; padding: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); font-size: var(--font-size-xs); }
.check { display: flex; align-items: flex-start; gap: var(--gap-sm); }
.check input { flex: none; margin-top: var(--gap-xs); accent-color: var(--accent); }
.login { display: grid; gap: var(--gap-xs); }
.small-btn { padding: 0 var(--gap-sm); }
</style>
