<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'

// Housekeeping: findings the server worked out by fixed rules (no model), and fixes only the operator can approve.
// The coordinator (Hermes) may read the findings and propose a fix, which appears here for a decision.
interface Finding { id: string; kind: string; reason: string; action: string; evidence: Record<string, unknown> }
interface Outcome { id: string; status: string; reason?: string }
interface Proposal { id: number; created_by: string; summary: string; finding_ids: string[]; status: string; decided_by: string | null; result: Outcome[] | null }
interface AutoStatus { enabled: boolean; classes: string[]; window: string; last_run: number | null; last_applied: number; last_summary: string | null; in_window: boolean }
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
onMounted(load)
</script>
<template>
  <section id="housekeeping" class="card housekeeping" aria-labelledby="housekeeping-title">
    <h2 id="housekeeping-title" class="section-title">Housekeeping</h2>
    <p v-if="data?.auto" class="small" data-testid="after-hours">
      <strong>After hours:</strong>&nbsp;
      <template v-if="data.auto.enabled">cleans up {{ data.auto.classes.map(c => KIND[c] ?? c).join(', ') }} between {{ data.auto.window }}, once a day. Last run: {{ when(data.auto.last_run) }}{{ data.auto.last_summary ? ` (${data.auto.last_summary})` : '' }}.</template>
      <template v-else>off. To have the safe kinds cleaned up for you overnight, set <code>MAC_CONTROL_HOUSEKEEPING_AUTO</code> (for example <code>stale_update_helper</code>). Finished update helpers are also unloaded automatically a few minutes after an update.</template>
    </p>
    <p class="muted small">Leftovers found by fixed rules. Nothing changes until you approve it. Hermes can propose but cannot change anything itself.</p>
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
</style>
