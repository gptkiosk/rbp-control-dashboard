<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getJson, postJson } from '@/lib/api'
interface Fix { action: string; label: string; inputs?: string[]; tool?: string }
interface Job { id: string; action: string; label: string; state: 'running' | 'done' | 'failed'; started: number; tail: string[]; exit?: number | null }
interface Check { id: string; label: string; status: 'ok' | 'missing' | 'warn' | 'info'; detail: string; fix: Fix | null; public_key?: string; agents?: { id: string; installed: boolean; writes_code: boolean }[]; tools?: Tool[] }
interface Tool { id: string; installed: boolean; needed_for: string; stopped?: boolean; get?: { kind: 'agent_tools' | 'command'; tool?: string; command?: string; note: string; fix?: Fix } | null }
interface Report { checks: Check[]; ready_to_build: boolean; ready_to_deliver: boolean; note: string }
const emit = defineEmits<{ changed: [] }>()
const report = ref<Report | null>(null), error = ref(''), notice = ref(''), busy = ref(false), loading = ref(true)
const name = ref(''), email = ref('')
const job = ref<Job | null>(null)
const jobRunning = computed(() => job.value?.state === 'running')
let timer: ReturnType<typeof setInterval> | undefined
const howList = (c: Check) => (c.tools ?? []).filter(t => !t.installed && t.get)
const mark: Record<Check['status'], string> = { ok: '✓', missing: '✗', warn: '!', info: 'i' }
const word: Record<Check['status'], string> = { ok: 'ready', missing: 'needs attention', warn: 'check', info: 'optional' }
async function load(network = false) {
  loading.value = true; error.value = ''
  try { report.value = await getJson<Report>(`/api/host/readiness${network ? '?network=true' : ''}`) } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { loading.value = false }
}
function watchJob() {
  clearInterval(timer)
  timer = setInterval(async () => {
    try {
      const j = (await getJson<{ job: Job | null }>('/api/host/readiness/job')).job
      job.value = j
      if (j && j.state !== 'running') {
        clearInterval(timer); timer = undefined
        await load(false)                                          // reading the report clears messages, so say what happened after it
        if (j.state === 'done') notice.value = `Finished: ${j.label}.`; else error.value = `${j.label} failed (exit ${j.exit ?? '?'}). The log is below.`
        emit('changed')
      }
    } catch { /* keep polling; a restart of the dashboard ends the job's view, not the job */ }
  }, 2500)
}
async function run(fix: Fix) {
  if (busy.value || jobRunning.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const body: Record<string, string> = { action: fix.action }
    if (fix.action === 'set_git_identity') { body.name = name.value.trim(); body.email = email.value.trim() }
    if (fix.tool) body.tool = fix.tool
    const r = await postJson<{ message: string; report: Report; job?: Job | null }>('/api/host/readiness/fix', body)
    report.value = r.report; notice.value = r.message; emit('changed')
    if (r.job && r.job.state === 'running') { job.value = r.job; watchJob() }
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
onBeforeUnmount(() => clearInterval(timer))
async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); notice.value = 'Public key copied.' } catch { notice.value = 'Select the key and copy it.' }
}
onMounted(() => void load())
</script>
<template>
  <section class="host-readiness" aria-labelledby="host-ready-title">
    <header class="head">
      <h3 id="host-ready-title">Is this machine ready to build?</h3>
      <p class="muted small">A checklist for building and delivering projects from this host. Checking changes nothing; each fix does one named thing and shows what it did. Agent sign-in is not verified here.</p>
    </header>
    <p v-if="loading && !report" role="status" class="muted">Checking this machine…</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="notice" class="message ok" role="status">{{ notice }}</p>
    <template v-if="report">
      <p class="summary" data-testid="readiness-summary">
        <span class="badge" :class="report.ready_to_build ? 'good' : 'bad'">{{ report.ready_to_build ? '✓' : '✗' }} Ready to build: {{ report.ready_to_build ? 'yes' : 'not yet' }}</span>
        <span class="badge" :class="report.ready_to_deliver ? 'good' : 'bad'">{{ report.ready_to_deliver ? '✓' : '✗' }} Ready to deliver to GitHub: {{ report.ready_to_deliver ? 'yes' : 'not yet' }}</span>
      </p>
      <section v-if="job" class="job" :class="`j-${job.state}`" aria-live="polite" aria-label="Install progress" data-testid="job">
        <p class="small"><strong>{{ job.label }}</strong> <span class="muted">{{ job.state === 'running' ? 'running…' : job.state === 'done' ? 'finished' : `failed (exit ${job.exit ?? '?'})` }}</span></p>
        <pre v-if="job.tail.length" class="log small">{{ job.tail.join('\n') }}</pre>
      </section>
      <ul class="checks">
        <li v-for="c in report.checks" :key="c.id" :data-check="c.id" :class="`s-${c.status}`">
          <div class="title">
            <span class="mark" aria-hidden="true">{{ mark[c.status] }}</span>
            <strong>{{ c.label }}</strong>
            <span class="state small">{{ word[c.status] }}</span>
          </div>
          <p class="detail small">{{ c.detail }}</p>
          <ul v-if="c.agents" class="chips" aria-label="Agents"><li v-for="a in c.agents" :key="a.id" :class="{ off: !a.installed }">{{ a.id }}{{ a.installed ? '' : ' (not installed)' }}{{ a.writes_code ? '' : ' · manager' }}</li></ul>
          <ul v-if="c.tools" class="chips" aria-label="Tools"><li v-for="t in c.tools" :key="t.id" :class="{ off: !t.installed }" :title="t.needed_for">{{ t.id }}{{ t.installed ? '' : t.stopped ? ' (stopped)' : ' (missing)' }}</li></ul>
          <ul v-if="howList(c).length" class="how" aria-label="How to get the missing tools">
            <li v-for="t in howList(c)" :key="t.id" :data-how="t.id">
              <strong>{{ t.id }}</strong>
              <span class="small muted">{{ t.get!.note }}</span>
              <RouterLink v-if="t.get!.kind === 'agent_tools'" class="btn" to="/profile#agent-tools">Open Agent tools to install {{ t.id }}</RouterLink>
              <span v-else class="cmd"><code>{{ t.get!.command }}</code><button type="button" class="btn" @click="copy(t.get!.command!)">Copy command</button></span>
              <button v-if="t.get!.fix" type="button" class="btn primary" :disabled="busy || jobRunning" @click="run(t.get!.fix!)">{{ t.get!.fix!.label }}</button>
            </li>
          </ul>
          <div v-if="c.fix && c.id === 'git_identity'" class="identity">
            <label>Name<input v-model="name" class="input" maxlength="100" autocomplete="name" /></label>
            <label>Email<input v-model="email" class="input" type="email" maxlength="254" autocomplete="email" /></label>
            <button type="button" class="btn" :disabled="busy || jobRunning || !name.trim() || !email.trim()" @click="run(c.fix)">{{ c.fix.label }}</button>
          </div>
          <div v-else-if="c.fix" class="actions"><button type="button" class="btn" :disabled="busy || jobRunning" @click="run(c.fix)">{{ c.fix.label }}</button></div>
          <div v-if="c.public_key" class="key">
            <label>Public key to add to GitHub<textarea class="input" readonly rows="3" :value="c.public_key" aria-label="GitHub public key" /></label>
            <div class="actions">
              <button type="button" class="btn" @click="copy(c.public_key!)">Copy public key</button>
              <a href="https://github.com/settings/ssh/new" target="_blank" rel="noopener noreferrer">Add it to your GitHub account</a>
              <span class="muted small">or to one repository's Deploy keys with write access</span>
            </div>
          </div>
        </li>
      </ul>
      <div class="actions footer"><button type="button" class="btn" :disabled="loading || busy || jobRunning" @click="load(false)">Recheck</button><button type="button" class="btn" :disabled="loading || busy || jobRunning" @click="load(true)">Recheck with network test</button></div>
    </template>
  </section>
</template>
<style scoped>
.host-readiness { display: grid; gap: var(--gap); padding: var(--gap-lg); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--accent-soft); }
.head { display: grid; gap: var(--gap-xs); }
.host-readiness h3, .host-readiness p { margin: 0; }
.message { padding: var(--gap-sm) var(--gap); border-radius: var(--radius-sm); border: 1px solid transparent; }
.message.error { color: var(--danger); background: var(--danger-soft); border-color: var(--danger); }
.message.ok { color: var(--ok); background: var(--ok-soft); border-color: var(--ok); }
.summary { display: flex; flex-wrap: wrap; gap: var(--gap-sm); }
.badge { padding: var(--gap-xs) var(--gap); border-radius: var(--radius-pill); font-size: var(--font-size-sm); font-weight: var(--font-weight-strong); border: 1px solid var(--surface-border); }
.badge.good { color: var(--ok); background: var(--ok-soft); border-color: var(--ok); }
.badge.bad { color: var(--warn); background: var(--warn-soft, transparent); border-color: var(--warn); }
.checks { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--gap-sm); }
.checks > li { display: grid; gap: var(--gap-sm); align-content: start; padding: var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--panel); min-width: 0; }
.title { display: flex; align-items: center; gap: var(--gap-sm); }
.title strong { flex: 1; min-width: 0; }
.mark { display: inline-grid; place-items: center; width: 1.5rem; height: 1.5rem; border-radius: 50%; font-size: var(--font-size-sm); font-weight: var(--font-weight-strong); border: 1px solid var(--surface-border); flex: none; }
.s-ok .mark { color: var(--ok); background: var(--ok-soft); border-color: var(--ok); }
.s-missing .mark { color: var(--danger); background: var(--danger-soft); border-color: var(--danger); }
.s-warn .mark { color: var(--warn); border-color: var(--warn); }
.state { color: var(--text-muted); white-space: nowrap; }
.detail { color: var(--text-muted); overflow-wrap: anywhere; }
.chips { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--gap-xs); }
.chips li { border: 1px solid var(--surface-border); border-radius: var(--radius-pill); padding: 0 var(--gap-sm); font-size: var(--font-size-sm); }
.chips li.off { opacity: 0.6; }
.job { display: grid; gap: var(--gap-xs); padding: var(--gap-sm) var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--panel); }
.job.j-failed { border-color: var(--danger); }
.job.j-done { border-color: var(--ok); }
.log { margin: 0; max-height: 11rem; overflow: auto; padding: var(--gap-xs) var(--gap-sm); background: var(--bg); border-radius: var(--radius-sm); font-family: var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.how { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--gap-sm); }
.how > li { display: grid; gap: var(--gap-xs); padding: var(--gap-sm); border: 1px dashed var(--surface-border); border-radius: var(--radius-sm); min-width: 0; }
.how .btn { justify-self: start; }
.cmd { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-sm); min-width: 0; }
.cmd code { flex: 1 1 18rem; min-width: 0; padding: var(--gap-xs) var(--gap-sm); border-radius: var(--radius-sm); background: var(--bg); border: 1px solid var(--surface-border); font-size: var(--font-size-sm); overflow-wrap: anywhere; }
.identity { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr)); gap: var(--gap-sm); align-items: end; }
.identity .btn { grid-column: 1 / -1; justify-self: start; }
.identity .input, .key .input { width: 100%; box-sizing: border-box; }
.identity label, .key label { display: grid; gap: var(--gap-xs); font-size: var(--font-size-sm); color: var(--text-muted); }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-sm) var(--gap); }
.actions .btn, .identity .btn { width: auto; flex: none; }
.footer { padding-top: var(--gap-sm); border-top: 1px solid var(--surface-border); }
.key { display: grid; gap: var(--gap-sm); }
.key textarea { font-family: var(--font-mono); font-size: var(--font-size-sm); word-break: break-all; resize: vertical; min-height: 4.5rem; max-height: 12rem; }
</style>
