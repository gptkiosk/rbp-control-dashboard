<script setup lang="ts">
import NoteFold from '@/components/NoteFold.vue'
import PanelHead from '@/components/PanelHead.vue'
import { computed, onMounted, ref } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'
import { formatBytes } from '@/lib/format'

// Housekeeping: findings the server worked out by fixed rules (no model), and fixes only the operator can approve.
// The coordinator (Hermes) may read the findings and propose a fix, which appears here for a decision.
interface Finding { id: string; kind: string; reason: string; action: string; evidence: Record<string, unknown> }
interface Outcome { id: string; status: string; reason?: string }
interface Proposal { id: number; created_by: string; summary: string; finding_ids: string[]; status: string; decided_by: string | null; result: Outcome[] | null }
interface AutoStatus { enabled: boolean; classes: string[]; window: string; last_run: number | null; last_applied: number; last_summary: string | null; in_window: boolean }
interface MediaStorage { projects: { project_id: number; title: string; references_bytes: number; candidates_bytes: number; media_bytes: number }[]; total_media_bytes: number; total_candidates_bytes: number; disk: { free_bytes: number; total_bytes: number } | null }
interface Overview { findings: Finding[]; proposals: Proposal[]; retention: { keep_newest_backups: number; backup_min_age_days: number }; auto?: AutoStatus }

const data = ref<Overview | null>(null)
const selected = ref<string[]>([]), confirmed = ref(false), busy = ref(false)
const error = ref(''), notice = ref('')

const pending = computed(() => (data.value?.proposals ?? []).filter(p => p.status === 'pending'))
const decided = computed(() => (data.value?.proposals ?? []).filter(p => p.status !== 'pending').slice(0, 5))
const KIND: Record<string, string> = { stale_approval_wait: 'Stale approval wait', old_update_backup: 'Old update backup', stale_update_helper: 'Finished update helper still loaded' }
const when = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleString() : 'never')

function message(e: unknown, fallback: string) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return 'Operator sign-in is required.'
  return e instanceof Error ? e.message : fallback
}
async function load() {
  try { data.value = await getJson<Overview>('/api/maintenance'); error.value = ''; selected.value = selected.value.filter(id => data.value!.findings.some(f => f.id === id)) }
  catch (e) { error.value = message(e, 'Housekeeping could not be read.') }
}
async function run(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch (e) { error.value = message(e, 'That did not complete.') } finally { busy.value = false }
}
function summarize(outcomes: Outcome[]) {
  const done = outcomes.filter(o => o.status === 'applied').length, skipped = outcomes.length - done
  return `${done} resolved${skipped ? `, ${skipped} skipped because they changed` : ''}.`
}
const apply = () => run(async () => {
  if (!confirmed.value || !selected.value.length) return
  const r = await postJson<{ outcomes: Outcome[] }>('/api/maintenance/apply', { finding_ids: selected.value, confirm: true })
  notice.value = summarize(r.outcomes); selected.value = []; confirmed.value = false; await load()
})
const decide = (p: Proposal, approve: boolean) => run(async () => {
  const r = await postJson<Proposal>(`/api/maintenance/proposals/${p.id}/${approve ? 'approve' : 'reject'}`)
  notice.value = approve ? summarize(r.result ?? []) : 'Proposal rejected. Nothing was changed.'; await load()
})
// Project media space, read separately so a problem reading folders never hides the findings above.
const storage = ref<MediaStorage | null>(null)
async function loadStorage() { try { storage.value = await getJson<MediaStorage>('/api/media/storage') } catch { storage.value = null } }
const diskUsed = computed(() => storage.value?.disk ? 1 - storage.value.disk.free_bytes / storage.value.disk.total_bytes : null)
onMounted(() => { void load(); void loadStorage() })
</script>
<template>
  <section id="housekeeping" class="card housekeeping" aria-labelledby="housekeeping-title">
    <PanelHead id="housekeeping-title" title="Housekeeping" :status="data?.auto ? (data.auto.enabled ? 'After hours: on' : 'After hours: off') : undefined" :tone="data?.auto?.enabled ? 'ok' : 'muted'" help="maintenance" />
    <NoteFold v-if="data?.auto" label="After hours cleanup"><p v-if="data?.auto" class="small" data-testid="after-hours">
      <strong>After hours:</strong>&nbsp;
      <template v-if="data.auto.enabled">cleans up {{ data.auto.classes.map(c => KIND[c] ?? c).join(', ') }} between {{ data.auto.window }}, once a day. Last run: {{ when(data.auto.last_run) }}{{ data.auto.last_summary ? ` (${data.auto.last_summary})` : '' }}.</template>
      <template v-else>off. To have the safe kinds cleaned up for you overnight, set <code>MAC_CONTROL_HOUSEKEEPING_AUTO</code> (for example <code>stale_update_helper</code>). Finished update helpers are also unloaded automatically a few minutes after an update.</template>
    </p></NoteFold>
    <p class="muted small">Rule-based findings. You approve every change; Hermes can only propose.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" class="note" role="status">{{ notice }}</p>

    <div class="actions"><button class="btn" :disabled="busy" @click="run(load)">Scan now</button></div>

    <section v-if="pending.length" class="block" aria-label="Proposals waiting for you">
      <h3>Proposed by Hermes, waiting for you</h3>
      <article v-for="p in pending" :key="p.id" class="proposal">
        <p>{{ p.summary }}</p>
        <p class="muted small">{{ p.finding_ids.length }} {{ p.finding_ids.length === 1 ? 'finding' : 'findings' }} frozen when it was proposed. Each is checked again before anything changes.</p>
        <div class="actions">
          <button class="btn primary" :disabled="busy" @click="decide(p, true)">Approve and apply</button>
          <button class="btn" :disabled="busy" @click="decide(p, false)">Reject</button>
        </div>
      </article>
    </section>

    <section v-if="storage" class="block storage" aria-label="Project media storage" data-testid="media-storage">
      <h3>Project media storage</h3>
      <p class="small">Project media uses {{ formatBytes(storage.total_media_bytes) }}, of which generated takes are {{ formatBytes(storage.total_candidates_bytes) }}.<template v-if="storage.disk"> Disk: {{ formatBytes(storage.disk.free_bytes) }} free of {{ formatBytes(storage.disk.total_bytes) }}.</template></p>
      <div v-if="diskUsed !== null" class="bar" :class="{ low: diskUsed > 0.9 }" role="meter" :aria-valuenow="Math.round(diskUsed * 100)" aria-valuemin="0" aria-valuemax="100" aria-label="Disk space used"><span :style="{ width: `${Math.round(diskUsed * 100)}%` }" /></div>
      <ul v-if="storage.projects.length" class="largest">
        <li v-for="p in storage.projects.slice(0, 5)" :key="p.project_id"><span>{{ p.title || `Project ${p.project_id}` }}</span><span class="muted">{{ formatBytes(p.media_bytes) }}<template v-if="p.candidates_bytes"> · takes {{ formatBytes(p.candidates_bytes) }}</template></span><RouterLink :to="`/projects?project=${p.project_id}&view=media`">Open media studio</RouterLink></li>
      </ul>
      <p v-else class="muted small">No project has media yet.</p>
      <p class="muted small">Generated takes you have already decided can be cleared in each project's Media studio; published files and reference art are kept.</p>
    </section>

    <section class="block" aria-label="Findings">
      <h3>Findings</h3>
      <p v-if="data && !data.findings.length" class="muted">Nothing to tidy. Old update backups are kept as the newest {{ data.retention.keep_newest_backups }} and anything younger than {{ data.retention.backup_min_age_days }} days.</p>
      <ul v-else-if="data" class="findings">
        <li v-for="f in data.findings" :key="f.id">
          <label class="check"><input v-model="selected" type="checkbox" :value="f.id" :data-testid="`finding-${f.id}`" /><span><strong>{{ KIND[f.kind] ?? f.kind }}</strong><br />{{ f.reason }}<br /><span class="muted small">{{ f.action }}</span></span></label>
        </li>
      </ul>
      <template v-if="data?.findings.length">
        <label class="check"><input v-model="confirmed" type="checkbox" />I have read these and want to resolve the {{ selected.length }} selected.</label>
        <div class="actions"><button class="btn primary" :disabled="busy || !confirmed || !selected.length" @click="apply">Resolve selected</button></div>
      </template>
    </section>

    <details v-if="decided.length" class="history">
      <summary>Recent decisions ({{ decided.length }})</summary>
      <ul class="findings"><li v-for="p in decided" :key="p.id">{{ p.status }} · {{ p.summary }}<span v-if="p.decided_by" class="muted small"> · by {{ p.decided_by }}</span></li></ul>
    </details>
  </section>
</template>
<style scoped>
.housekeeping { margin: var(--gap-lg) 0; display: grid; gap: var(--gap); }
h2, h3, p { margin: 0; }
h3 { font-size: var(--font-size); font-weight: var(--font-weight-strong); }
.lead, .block p, .note { max-width: 72ch; line-height: var(--line-height); }
.small { font-size: var(--font-size-sm); }
.actions { display: flex; gap: var(--gap); flex-wrap: wrap; align-items: center; }
.block { display: grid; gap: var(--gap); padding: var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--accent-soft); justify-items: start; }
.block > * { min-width: 0; max-width: 100%; }
.findings { display: grid; gap: var(--gap); margin: 0; padding: 0; list-style: none; }
.proposal { display: grid; gap: var(--gap-sm); }
.check { display: flex; align-items: flex-start; gap: var(--gap-sm); line-height: var(--line-height); }
.check input { flex: none; margin-top: 0.3rem; accent-color: var(--accent); }
summary { cursor: pointer; padding: var(--gap-xs) 0; }
.storage .bar { height: 0.4rem; border-radius: var(--radius-pill); background: var(--surface-border); overflow: hidden; }
.storage .bar span { display: block; height: 100%; background: var(--accent); }
.storage .bar.low span { background: var(--warn); }
.largest { display: grid; gap: var(--gap-xs); padding: 0; margin: 0; list-style: none; }
.largest li { display: flex; flex-wrap: wrap; gap: var(--gap-sm); align-items: baseline; }
.largest li a { margin-left: auto; }
</style>
