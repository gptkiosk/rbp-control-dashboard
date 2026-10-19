<script setup lang="ts">
import ManagedItem, { type Health } from '@/components/ManagedItem.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'

type Action = 'install' | 'update' | 'remove' | 'rollback' | 'repair'
const ACTIONS: Action[] = ['install', 'update', 'repair', 'rollback', 'remove']
const POLL_MS = 3000, NOT_STARTED_POLLS = 10, MAX_POLLS = 1000 // about 50 minutes; 30 seconds before "never started"

interface Tool {
  id: string; name: string; pinned_version: string; installed: boolean; installed_version: string | null
  installation_source?: 'native' | 'managed' | null; previous_version: string | null; installed_at: number | null; size_mb: number; commands: string[]; requires: string[]
  login: { command: string; note: string }; login_command?: string; path: string | null
  actions: Record<Action, string[] | null> // null: not offered now; []: allowed; otherwise the reasons it is refused
}
interface Status {
  product: string; platform: string; root: string; tools: Tool[]
  runtimes: { id: string; name: string; pinned_version: string; installed_version: string | null }[]
  host: { os: string; machine: string; bits: number; disk_free_mb: number; mem_total_mb: number | null; mem_available_mb: number | null }
  system_packages: { apt_command: string | null; missing_required: string[]; missing_recommended: string[]; details: Record<string, string>; note: string }
  tx: { id: string; tool: string; action: Action; phase: string } | null
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

const VERB: Record<Action, string> = { install: 'Install', update: 'Upgrade', remove: 'Remove', rollback: 'Roll back', repair: 'Repair' }
const status = ref<Status | null>(null), plan = ref<Plan | null>(null)
const confirmed = ref(false), busy = ref(false), copied = ref('')
const confirmEl = ref<HTMLElement | null>(null), noticeEl = ref<HTMLElement | null>(null), errorEl = ref<HTMLElement | null>(null)
const error = ref(''), notice = ref('')
const watching = ref<{ tool: string; action: Action; beforeTx: string | null; sawTx: boolean; polls: number } | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false, authRefused = false
const updatedAt = ref('')
const health = ref<Record<string, Health>>({}), healthBusy = ref(false)
// Read-only follow-up: does each installed tool run, is it the copy a new terminal reaches, what to do next.
async function checkHealth(tool?: string) {
  healthBusy.value = true
  try {
    const r = await getJson<{ checks: (Health & { id: string })[] }>(`/api/agent-installs/health${tool ? `?tool=${encodeURIComponent(tool)}` : ''}`)
    health.value = { ...health.value, ...Object.fromEntries(r.checks.map(c => [c.id, c])) }
  } catch (e) { error.value = refusal(e, 'The health check could not run.') } finally { healthBusy.value = false }
}

const progressTool = computed(() => status.value?.tx?.tool ?? watching.value?.tool ?? null)
const logTool = computed(() => status.value?.tx?.tool ?? status.value?.last?.tool ?? null)
// Do not label a previous helper's log as output of a newly submitted install.
const showToolLog = (id: string) => logTool.value === id && (!watching.value || watching.value.sawTx || (status.value?.last?.tx ?? null) !== watching.value.beforeTx)
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
const markOf = (t: Tool): 'ok' | 'warn' | 'missing' | 'info' => !t.installed ? 'info' : health.value[t.id] && !health.value[t.id]!.ok ? 'warn' : !t.installed_version || t.installed_version !== t.pinned_version ? 'warn' : 'ok'
const wordOf = (t: Tool) => workingOn(t.id) ? 'working' : !t.installed ? 'not installed' : !t.installed_version ? 'version unknown' : t.installed_version === t.pinned_version ? 'up to date' : 'update available'
const workingOn = (id: string) => working.value && progressTool.value === id
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
    error.value = ''; authRefused = false
    updatedAt.value = new Date().toLocaleTimeString()
    return true
  } catch (e) {
    authRefused = e instanceof ApiError && (e.status === 401 || e.status === 403)
    error.value = refusal(e, 'Agent tools could not be read right now.') + (authRefused ? '' : ' Retrying automatically; the displayed status may be out of date.')
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
// The confirmation, notice and error sit below or above a long list of tools. Bring whichever just appeared into view, or the click seems to do nothing.
function reveal(el: HTMLElement | null, block: ScrollLogicalPosition) {
  el?.scrollIntoView?.({ block, behavior: 'smooth' })
  el?.focus?.({ preventScroll: true })
}
watch(plan, async (p) => { if (!p) return; await nextTick(); reveal(confirmEl.value, 'start') })
watch(error, async (e) => { if (!e) return; await nextTick(); reveal(errorEl.value, 'center') })
watch(notice, async (n) => { if (!n) return; await nextTick(); reveal(noticeEl.value, 'center') })

async function submit() {
  const p = plan.value
  if (!p || !confirmed.value || p.refusals.length) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    await postJson('/api/agent-installs/run', { tool: p.tool, action: p.action, plan_sha256: p.plan_sha256, confirm: true })
    watching.value = { tool: p.tool, action: p.action, beforeTx: status.value?.last?.tx ?? null, sawTx: false, polls: 0 }
    plan.value = null; confirmed.value = false
    notice.value = `${VERB[p.action]} of ${p.name} started on the host. Progress is shown below.`
    schedule(POLL_MS)
  } catch (e) {
    await read()
    error.value = refusal(e, 'The helper could not be started.')
  } finally { busy.value = false }
}

function schedule(delay: number) {
  if (timer) clearTimeout(timer)
  if (!disposed && !authRefused) timer = setTimeout(poll, delay)
}
async function poll() {
  if (disposed) return
  const ok = await read()
  if (disposed) return
  if (!ok) { schedule(POLL_MS); return }
  const s = status.value!
  // Resume observing helpers that were started before mounting or in another tab.
  if (!watching.value && s.tx) watching.value = { tool: s.tx.tool, action: s.tx.action, beforeTx: s.last?.tx ?? null, sawTx: true, polls: 0 }
  const w = watching.value
  if (w) {
    if (s.tx || s.running) w.sawTx = true
    if (!s.tx && !s.running && (w.sawTx || (s.last?.tx ?? null) !== w.beforeTx)) finish()
    else {
      w.polls++
      if (!s.tx && !s.running && !w.sawTx && w.polls >= NOT_STARTED_POLLS) stop('The install helper has not started. Nothing was changed as far as the status shows. See the helper log on the host.')
      else if (w.polls >= MAX_POLLS) stop('Still waiting after about 50 minutes. Check the helper log on the host; nothing more is started from here.')
    }
  }
  schedule(working.value ? POLL_MS : 15000)
}
function finish() {
  const last = status.value?.last
  watching.value = null
  if (!last) return stop('The helper finished, but no outcome was recorded.')
  void checkHealth(last.tool ?? undefined)
  if (last.outcome === 'done') notice.value = last.detail
  else error.value = `Not completed (${last.outcome}): ${last.detail}`
}
function stop(message: string) { watching.value = null; error.value = message }

async function copy(text: string, label: string) {
  try { await navigator.clipboard.writeText(text); copied.value = label } catch { copied.value = '' ; notice.value = 'Copying is not available here. Select the command and copy it by hand.' }
}

onMounted(poll)
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>
<template>
  <section id="agent-tools" class="card agent-tools" aria-labelledby="agent-tools-title">
    <header class="head">
      <h3 id="agent-tools-title">Agent tools</h3>
      <RouterLink to="/help?topic=agent-tools" class="small">How-to</RouterLink>
    </header>
    <p class="muted small">Install or upgrade the agent CLIs for this user only: pinned, hash-checked, no sudo, nothing signed in and nothing that touches a key (so nothing here signs in to a tool or touches a key).</p>
    <p v-if="error" ref="errorEl" tabindex="-1" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" ref="noticeEl" tabindex="-1" role="status">{{ notice }}</p>
    <template v-if="status">
      <p class="muted small" data-test="host">{{ hostLine }} · installs under {{ status.root }}</p>
      <p v-if="updatedAt" class="muted small" role="status">Last checked {{ updatedAt }} · {{ working ? 'refreshing every 3 seconds' : 'refreshing every 15 seconds' }}</p>

      <ul class="items">
        <ManagedItem v-for="t in status.tools" :key="t.id" :data-tool="t.id" :name="t.name" :mark="markOf(t)" :word="wordOf(t)"
          :version="t.installed_version" :latest="t.pinned_version" :detail="stateText(t)" :busy="workingOn(t.id)"
          :progress="workingOn(t.id) ? progress : ''" :log="status.log.length && showToolLog(t.id) ? status.log : []" :log-title="`${t.name} log`"
          :health="health[t.id] ?? null" :health-busy="healthBusy" :health-disabled="!t.installed" :data-output="t.id" @health="checkHealth(t.id)">
          <button v-for="a in offered(t)" :key="a" class="btn" :class="{ primary: a === 'install' || a === 'update' || a === 'repair' }" :disabled="!canAct(t, a) || (t.actions[a] ?? []).length > 0" :data-action="a"
            @click="ask(t, a)">{{ VERB[a] }}{{ a === 'install' || a === 'update' ? ` ${t.pinned_version}` : a === 'rollback' && t.previous_version ? ` to ${t.previous_version}` : '' }}</button>
          <template #more>
            <span v-if="t.installed" class="login" :data-login="t.id">
              <span class="muted small">Sign in yourself:</span> <code>{{ t.login_command || t.login.command }}</code>
              <button type="button" class="btn small-btn" @click="copy(t.login_command || t.login.command, t.id)">{{ copied === t.id ? 'Copied' : 'Copy' }}</button>
              <RouterLink to="/profile#credentials-profile" class="small" :title="t.login.note">Keys: Private credentials</RouterLink>
            </span>
            <span v-if="status.notes[t.id]" class="muted small">{{ status.notes[t.id] }}</span>
          </template>
        </ManagedItem>
      </ul>

      <section v-if="status.system_packages.apt_command" class="packages" aria-labelledby="pkg-title">
        <h4 id="pkg-title">Optional system packages</h4>
        <p class="small">The dashboard never runs this command: copy it into a terminal if you want them.</p>
        <p class="cmd" data-test="apt"><code>{{ status.system_packages.apt_command }}</code> <button class="btn small-btn" @click="copy(status.system_packages.apt_command!, 'apt')">{{ copied === 'apt' ? 'Copied' : 'Copy' }}</button></p>
        <ul class="muted small"><li v-for="(why, name) in status.system_packages.details" :key="name"><strong>{{ name }}</strong>: {{ why }}</li></ul>
      </section>

      <section v-if="plan" ref="confirmEl" tabindex="-1" class="confirm" aria-labelledby="agent-confirm-title" data-test="confirm">
        <h4 id="agent-confirm-title">{{ confirmTitle }}</h4>
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
        <p v-if="plan.login" class="small">After it finishes, sign in yourself with <code>{{ plan.login.command }}</code>. If your shell says command not found, copy the command shown on the installed tool, which starts with its full path.</p>
        <label class="check"><input v-model="confirmed" type="checkbox" :disabled="plan.refusals.length > 0" />I have read this and want to continue.</label>
        <div class="actions">
          <button class="btn primary" :disabled="!confirmed || busy || plan.refusals.length > 0 || working" @click="submit">{{ VERB[plan.action] }} {{ plan.name }}</button>
          <button class="btn" :disabled="busy" @click="cancel">Cancel</button>
        </div>
      </section>

      <ul v-if="status.tools.some(t => reasons(t).length)" class="why muted small" aria-label="Why a button is off">
        <template v-for="t in status.tools" :key="t.id"><li v-for="x in reasons(t)" :key="t.id + x.r"><strong>{{ t.name }}</strong> · {{ VERB[x.a] }}: {{ x.r }}</li></template>
      </ul>
      <p v-if="status.last && !working" class="muted small" data-test="last">Last operation: {{ status.last.detail }} ({{ status.last.outcome }})</p>
      <p class="muted small">Pinned versions checked {{ status.catalog_checked }}. Roll back switches to the version kept on this host; Remove deletes the program but keeps your tool data.</p>
    </template>
  </section>
</template>
<style scoped>
.agent-tools { display: grid; gap: var(--gap-sm); }
h3, h4 { margin: 0; }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--gap); }
.small { font-size: var(--font-size-xs); margin: 0; }
.items { display: grid; gap: var(--gap-sm); padding: 0; margin: 0; list-style: none; }
.confirm, .packages { display: grid; gap: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); padding: var(--gap); justify-items: start; }
.actions { display: flex; gap: var(--gap); flex-wrap: wrap; align-items: center; }
.why { margin: 0; padding-left: var(--gap); }
.cmd { display: flex; gap: var(--gap-sm); align-items: center; flex-wrap: wrap; margin: 0; }
.login { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--gap-xs) var(--gap-sm); }
code, .mono { font-family: var(--font-mono, ui-monospace, monospace); font-size: var(--font-size-xs); overflow-wrap: anywhere; }
.facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: var(--gap-xs) var(--gap); margin: 0; font-size: var(--font-size-sm); }
.facts dt { color: var(--text-muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.runtime { display: block; }
.commands { margin: 0; padding-left: var(--gap); display: grid; gap: var(--gap-xs); }
.warn { margin: 0; padding: 0; list-style: none; display: grid; gap: var(--gap-xs); }
.check { display: flex; align-items: flex-start; gap: var(--gap-sm); }
.check input { flex: none; margin-top: var(--gap-xs); accent-color: var(--accent); }
.small-btn { padding: 0 var(--gap-sm); }
</style>
