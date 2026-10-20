<script setup lang="ts">
// Coordinator setup run by the dashboard itself: check each selected platform, preview the changes, apply them, then start a small
// validation project. The parent saves the operator's choices first (`persist`), because the server reads them from the profile.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import ManagedItem from '@/components/ManagedItem.vue'
import { getJson, postJson } from '@/lib/api'

interface Check { id: string; name: string; state: 'ready' | 'missing' | 'needs_action'; version: string | null; model: string | null; detail: string; link: string | null }
interface Change { action: 'create' | 'keep'; kind: 'agent' | 'file' | 'folder'; id: string; detail: string; path: string | null }
interface Result { id: string; outcome: 'done' | 'failed'; detail: string }
interface JobItem { id: string; label: string; state: 'pending' | 'running' | 'done' | 'failed'; detail: string }
interface Job { state: 'running' | 'done' | 'failed'; items: JobItem[]; log: string[]; started: number; finished: number | null }
interface Setup { mode: 'stable' | 'custom'; checks: Check[]; changes: Change[]; problems: string[]; base: string | null; agents: string[]; digest: string; verified: boolean; last: { at: number; results: Result[]; log?: string[] } | null; job: Job | null }

const props = defineProps<{ hermesReady: boolean; persist: () => Promise<void> }>()
const router = useRouter()
const setup = ref<Setup | null>(null), busy = ref(false), error = ref(''), notice = ref(''), confirmed = ref(false)
const pending = computed(() => setup.value?.changes.filter(c => c.action === 'create') ?? [])
const failed = computed(() => setup.value?.last?.results.filter(r => r.outcome === 'failed') ?? [])
const job = computed(() => setup.value?.job ?? null)
const working = computed(() => job.value?.state === 'running')
const finished = computed(() => job.value?.items.filter(i => i.state === 'done' || i.state === 'failed').length ?? 0)
const ITEM_MARK = { pending: '·', running: '…', done: '✓', failed: '!' } as const
let timer: ReturnType<typeof setTimeout> | undefined
const MARK = { ready: 'ok', missing: 'missing', needs_action: 'warn' } as const
const WORD = { ready: 'ready', missing: 'not installed', needs_action: 'needs action' } as const

async function run(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
async function load() { setup.value = await getJson<Setup>('/api/profile/coordinator-bootstrap/setup'); confirmed.value = false; if (working.value) follow() }
// While an apply runs on the host, read its items and log every 1.5 s until it finishes.
function follow() {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    try { setup.value = await getJson<Setup>('/api/profile/coordinator-bootstrap/setup') } catch { /* keep following; the next read may succeed */ }
    if (working.value) return follow()
    notice.value = job.value?.state === 'failed' ? 'Some changes failed. The reasons are listed below; nothing else was touched.' : 'Setup applied. Start the validation project to create the tasks that prove each platform.'
  }, 1500)
}
const check = () => run(async () => { await props.persist(); await load(); notice.value = setup.value!.verified ? 'Setup is verified. Start the validation project.' : 'Checked. Follow the steps below.' })
const applySetup = () => run(async () => {
  setup.value = await postJson<Setup>('/api/profile/coordinator-bootstrap/setup/apply', { digest: setup.value!.digest })
  confirmed.value = false
  notice.value = 'Applying setup on the host. Progress and the log are shown below.'
  follow()
})
const start = () => run(async () => {
  await props.persist()
  const r = await postJson<{ project_id: number }>('/api/profile/coordinator-bootstrap/start')
  await router.push({ path: '/projects', query: { project: String(r.project_id) } })
})
onMounted(() => void run(load))
onBeforeUnmount(() => clearTimeout(timer))
defineExpose({ check })
</script>
<template>
  <section class="setup" aria-labelledby="setup-title">
    <h3 id="setup-title">Platform check</h3>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="!setup" class="muted small" role="status">Checking the selected platforms…</p>
    <template v-if="setup">
      <ul class="items" data-test="checks">
        <ManagedItem v-for="c in setup.checks" :key="c.id" :data-platform="c.id" :name="c.name" :mark="MARK[c.state]" :word="WORD[c.state]" :version="c.version" :detail="c.detail" health-disabled>
          <RouterLink v-if="c.link && c.state !== 'ready'" :to="c.link" class="btn">Fix</RouterLink>
        </ManagedItem>
      </ul>
      <ul v-if="setup.problems.length" class="problems" role="alert"><li v-for="p in setup.problems" :key="p">{{ p }}</li></ul>

      <template v-if="setup.mode === 'stable' && setup.changes.length">
        <h3>Changes</h3>
        <ul class="changes" data-test="changes">
          <li v-for="c in setup.changes" :key="c.id" :class="c.action"><span class="tag small">{{ c.action === 'create' ? 'will create' : 'already there' }}</span><span><strong>{{ c.id }}</strong> {{ c.detail }}</span></li>
        </ul>
      </template>
      <p v-else-if="setup.mode === 'custom'" class="muted small">You configure the platforms yourself, so setup changes nothing. It only checks them.<template v-if="setup.agents.length"> OpenClaw agents found: {{ setup.agents.join(', ') }}.</template></p>

      <ul v-if="job" class="items" data-test="job">
        <ManagedItem name="Applying setup" :mark="working ? 'info' : job.state === 'done' ? 'ok' : 'warn'" :word="working ? 'working' : job.state === 'done' ? 'finished' : 'finished with errors'"
          :busy="working" :progress="`${finished} of ${job.items.length} done`" :log="job.log" log-title="Setup log" health-disabled>
          <ul class="job-items">
            <li v-for="i in job.items" :key="i.id" :class="i.state"><span class="mark" aria-hidden="true">{{ ITEM_MARK[i.state] }}</span><strong>{{ i.id }}</strong><span class="muted small">{{ i.detail || (i.state === 'running' ? 'working…' : i.state === 'pending' ? 'waiting' : '') }}</span></li>
          </ul>
        </ManagedItem>
      </ul>
      <ul v-else-if="failed.length" class="problems" data-test="failed"><li v-for="r in failed" :key="r.id"><strong>{{ r.id }}</strong>: {{ r.detail }}</li></ul>

      <label v-if="pending.length && !working" class="check"><input v-model="confirmed" type="checkbox" /> Create the {{ pending.length }} item{{ pending.length === 1 ? '' : 's' }} listed. Existing agents and files are never changed.</label>
      <div class="actions">
        <button v-if="pending.length || working" type="button" class="btn primary" data-action="apply" :disabled="busy || working || !confirmed" @click="applySetup">{{ working ? 'Applying…' : 'Apply setup' }}</button>
        <button type="button" class="btn" :class="{ primary: setup.verified }" data-action="start" :disabled="busy || !setup.verified || !hermesReady" @click="start">Start validation project</button>
        <button type="button" class="btn" :disabled="busy || working" @click="check">Check again</button>
      </div>
      <p class="muted small">Setup itself creates no tasks. The validation project does: one read-only task per ready platform, which you submit in Projects.</p>
      <p v-if="setup.verified && !hermesReady" class="muted small">Finish the Hermes items above first.</p>
    </template>
  </section>
</template>
<style scoped>
.setup { display: grid; gap: var(--gap-sm); }
h3 { margin: var(--gap-xs) 0 0; font-size: var(--font-size-base); }
.items, .changes, .problems { display: grid; gap: var(--gap-xs); padding: 0; margin: 0; list-style: none; }
.changes li { display: flex; align-items: baseline; gap: var(--gap-sm); padding: var(--gap-sm) var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); overflow-wrap: anywhere; }
.changes li.keep { color: var(--text-muted); }
.tag { flex: none; padding: 0 var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius-pill); }
.changes li.create .tag { border-color: var(--accent); color: var(--accent); }
.problems li { padding: var(--gap-sm) var(--gap); border: 1px solid var(--warn); border-radius: var(--radius); }
.job-items { display: grid; gap: var(--gap-xs); padding: 0; margin: 0; list-style: none; width: 100%; }
.job-items li { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--gap-sm); overflow-wrap: anywhere; }
.job-items .mark { width: 1rem; text-align: center; font-weight: var(--font-weight-strong); }
.job-items .done .mark { color: var(--ok); }
.job-items .failed .mark { color: var(--warn); }
.job-items .running .mark { color: var(--accent); }
.check { display: flex; gap: var(--gap-sm); align-items: center; }
.actions { display: flex; flex-wrap: wrap; gap: var(--gap-sm); }
.small { font-size: var(--font-size-xs); margin: 0; }
</style>
