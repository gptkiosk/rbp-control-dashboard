<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ManagedItem, { type Health } from '@/components/ManagedItem.vue'
import { getJson, postJson } from '@/lib/api'

interface Row { id: string; needed_for: string; installed: boolean; version: string | null; latest: string | null; outdated: boolean | null; path: string | null; formulae: string[]; stopped: boolean }
interface Job { id: string; action: string; label: string; state: 'running' | 'done' | 'failed'; tail: string[]; exit?: number | null }
interface Body {
  platform: 'mac' | 'linux'; tools: Row[]; missing: string[]; outdated: string[]; updates_checked: boolean; job: Job | null
  brew?: { installed: boolean; path: string | null; version: string | null; install_command: string; prerequisite: string }
  can_install_all: boolean; can_upgrade_all: boolean; apt_command?: string | null; note?: string
}
const BREW_ONE = ['ffmpeg', 'python3', 'docker', 'colima']                      // tools the server can install one at a time
const body = ref<Body | null>(null), error = ref(''), notice = ref(''), busy = ref(false), loading = ref(true), copied = ref('')
const job = ref<Job | null>(null)
const health = ref<Record<string, Health>>({}), healthBusy = ref(false), healthRan = ref(false)
let timer: ReturnType<typeof setInterval> | undefined
const running = computed(() => job.value?.state === 'running')
const mac = computed(() => body.value?.platform === 'mac')
const missing = computed(() => body.value?.tools.filter(t => !t.installed) ?? [])

async function load(updates = false) {
  loading.value = true
  try {
    body.value = await getJson<Body>(`/api/host/readiness/tools${updates ? '?check_updates=true' : ''}`)
    if (body.value.job) job.value = body.value.job
    if (job.value?.state === 'running') watch()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { loading.value = false }
}
function watch() {
  clearInterval(timer)
  timer = setInterval(async () => {
    try {
      const j = (await getJson<{ job: Job | null }>('/api/host/readiness/job')).job
      job.value = j
      if (j && j.state !== 'running') {
        clearInterval(timer); timer = undefined
        await load(false)                                            // reading the list clears messages, so say what happened after it
        if (j.state === 'done') { notice.value = `Finished: ${j.label}. Health check below.`; await checkHealth() } else error.value = `${j.label} failed (exit ${j.exit ?? '?'}). The log is below.`
      }
    } catch { /* keep polling; a dashboard restart ends the view of the job, not the job */ }
  }, 2500)
}
async function fix(action: string, tool?: string) {
  if (busy.value || running.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const r = await postJson<{ message: string; job?: Job | null }>('/api/host/readiness/fix', { action, ...(tool ? { tool } : {}) })
    notice.value = r.message
    if (r.job && r.job.state === 'running') { job.value = r.job; watch() }
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
async function checkHealth() {
  healthBusy.value = true
  try {
    const r = await getJson<{ checks: (Health & { id: string })[] }>('/api/host/readiness/tools/health')
    health.value = Object.fromEntries(r.checks.map(c => [c.id, c])); healthRan.value = true
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { healthBusy.value = false }
}
async function copy(text: string, label: string) {
  try { await navigator.clipboard.writeText(text); copied.value = label } catch { notice.value = 'Select the command and copy it by hand.' }
}
const allHealth = computed<Health | null>(() => {
  if (!healthRan.value) return null
  const rows = Object.entries(health.value)
  return { ok: rows.every(([, h]) => h.ok), next: rows.flatMap(([id, h]) => h.next.map(n => `${id}: ${n}`)) }
})
const summary = computed(() => {
  const b = body.value
  if (!b) return ''
  const parts = [`${missing.value.length} missing`]
  parts.push(b.updates_checked ? `${b.outdated.length} to upgrade` : 'updates not checked')
  return parts.join(' · ')
})
const markOf = (t: Row): 'ok' | 'warn' | 'missing' | 'info' => !t.installed ? 'info' : t.stopped || (health.value[t.id] && !health.value[t.id]!.ok) || t.outdated ? 'warn' : 'ok'
const wordOf = (t: Row) => !t.installed ? 'missing' : t.stopped ? 'stopped' : t.outdated ? 'upgrade available' : t.outdated === false ? 'up to date' : 'installed'
onMounted(() => void load())
onBeforeUnmount(() => clearInterval(timer))
</script>
<template>
  <section id="system-tools" class="card system-tools" aria-labelledby="system-tools-title">
    <header class="head">
      <h3 id="system-tools-title">Optional system tools</h3>
      <RouterLink to="/help?topic=system-tools" class="small">How-to</RouterLink>
    </header>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="loading && !body" class="muted" role="status">Checking this machine…</p>
    <template v-if="body">
      <ul class="items">
        <ManagedItem v-if="mac && body.brew" name="Homebrew" data-tool="brew" :mark="body.brew.installed ? 'ok' : 'missing'" :word="body.brew.installed ? 'installed' : 'needed first'" :version="body.brew.version"
          :detail="body.brew.installed ? body.brew.path ?? '' : body.brew.prerequisite" health-disabled>
          <template v-if="!body.brew.installed">
            <span class="cmd"><code data-test="brew-command">{{ body.brew.install_command }}</code><button type="button" class="btn small-btn" @click="copy(body.brew.install_command, 'brew')">{{ copied === 'brew' ? 'Copied' : 'Copy command' }}</button></span>
            <button type="button" class="btn" :disabled="loading" @click="load()">I installed it: check again</button>
          </template>
        </ManagedItem>

        <ManagedItem name="All optional tools" data-tool="all" :mark="missing.length ? 'warn' : 'ok'" :word="summary" :busy="running"
          :progress="job ? `${job.label}: ${job.state === 'running' ? 'running…' : job.state === 'done' ? 'finished' : `failed (exit ${job.exit ?? '?'})`}` : ''"
          :log="job?.tail ?? []" log-title="Install log" :health="allHealth" :health-busy="healthBusy" @health="checkHealth">
          <template v-if="mac">
            <button type="button" class="btn primary" data-action="install-all" :disabled="busy || running || !body.can_install_all" @click="fix('brew_install_all')">Install (All)</button>
            <button type="button" class="btn primary" data-action="upgrade-all" :disabled="busy || running || !body.can_upgrade_all" @click="fix('brew_upgrade_all')">Upgrade (All)</button>
            <button type="button" class="btn" :disabled="loading || running" @click="load(true)">Check for updates</button>
            <span v-if="!body.brew?.installed" class="muted small">Install Homebrew first.</span>
          </template>
          <template v-else>
            <span v-if="body.apt_command" class="cmd"><code data-test="apt">{{ body.apt_command }}</code><button type="button" class="btn small-btn" @click="copy(body.apt_command!, 'apt')">{{ copied === 'apt' ? 'Copied' : 'Copy install command' }}</button></span>
            <span v-else class="muted small">Nothing to install with apt.</span>
          </template>
          <template #more><span v-if="body.note" class="muted small">{{ body.note }}</span></template>
        </ManagedItem>

        <ManagedItem v-for="t in body.tools" :key="t.id" :data-tool="t.id" :name="t.id" :mark="markOf(t)" :word="wordOf(t)" :version="t.version" :latest="t.outdated ? t.latest : null"
          :detail="t.installed ? t.path ?? '' : `Needed for ${t.needed_for}.`" :health="health[t.id] ?? null" health-disabled>
          <button v-if="mac && !t.installed && BREW_ONE.includes(t.id) && body.brew?.installed" type="button" class="btn" :disabled="busy || running" @click="fix('brew_install', t.id)">Install {{ t.id }}</button>
          <button v-if="t.stopped" type="button" class="btn primary" :disabled="busy || running" @click="fix('colima_start')">Start Colima</button>
          <RouterLink v-if="!t.installed && (t.id === 'gh' || t.id === 'node') && !mac" to="/profile#agent-tools" class="btn">Install from Agent tools</RouterLink>
        </ManagedItem>
      </ul>
    </template>
  </section>
</template>
<style scoped>
.system-tools { display: grid; gap: var(--gap-sm); }
h3 { margin: 0; }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--gap); }
.small { font-size: var(--font-size-xs); margin: 0; }
.items { display: grid; gap: var(--gap-sm); padding: 0; margin: 0; list-style: none; }
.cmd { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-sm); min-width: 0; }
.cmd code { flex: 1 1 18rem; min-width: 0; padding: var(--gap-xs) var(--gap-sm); border-radius: var(--radius-sm); background: var(--bg); border: 1px solid var(--surface-border); font-size: var(--font-size-sm); overflow-wrap: anywhere; font-family: var(--font-mono, ui-monospace, monospace); }
.small-btn { padding: 0 var(--gap-sm); }
</style>
