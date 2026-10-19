<script setup lang="ts">
import NoteFold from '@/components/NoteFold.vue'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppSelect from '@/components/AppSelect.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import { ApiError, postJson } from '@/lib/api'
import { dateLabel, type CheckStatus, type OpsCollectorStatus, type Report } from '@/lib/operations'
import { SEVERITY_LABEL, ago, dailyFleetReports, duration, filterChecks, linkFor, pageLabel, sortChecks, worstSeverity } from '@/lib/opsHealth'

const props = defineProps<{ reports: Report[] }>()
const { data, error, loaded, refresh } = usePolledJson<OpsCollectorStatus>('/api/ops-collectors', 60000)
const busy = ref(false)
const actionError = ref('')
const query = ref('')
const level = ref<CheckStatus | 'all'>('all')
const clock = ref(Date.now() / 1000)
watch(data, () => { clock.value = Date.now() / 1000 })

const status = computed(() => data.value)
const checks = computed(() => sortChecks(status.value?.sources ?? []))
const visible = computed(() => filterChecks(checks.value, query.value, level.value))
const overall = computed(() => worstSeverity(status.value?.sources ?? [], status.value?.overall ?? 'warn'))
const staleCount = computed(() => (status.value?.sources ?? []).filter(s => s.stale).length)
const trend = computed(() => dailyFleetReports(props.reports, clock.value))
const trendMax = computed(() => Math.max(1, ...trend.value))
const lastChecked = computed(() => {
  const newest = Math.max(0, ...(status.value?.sources ?? []).map(s => s.checked_at ?? 0))
  const at = status.value?.last_run?.at ?? (newest || null)
  return at ? `${ago(at, clock.value)} · ${dateLabel(at)}` : 'Not checked yet'
})
// The exact report written by the last run, found by name so the link opens that file and nothing else.
const lastReport = computed(() => {
  const name = status.value?.last_run?.report
  return name ? props.reports.find(r => r.name === name) ?? null : null
})

function sinceLabel(since: number | null): string {
  return since === null ? 'Unchanged since first check' : `Unchanged for ${duration(clock.value - since)}`
}

async function runChecks() {
  busy.value = true; actionError.value = ''
  try {
    await postJson('/api/ops-collectors/refresh')
    await refresh()
  } catch (e) {
    actionError.value = e instanceof ApiError && (e.status === 401 || e.status === 403)
      ? 'Operator sign-in is required to run checks now.'
      : e instanceof Error ? e.message : 'The checks could not be run.'
  } finally {
    busy.value = false
  }
}

defineExpose({ refresh })
</script>
<template>
  <section class="card ops-health" aria-labelledby="ops-health-title">
    <header class="health-head">
      <div>
        <h2 id="ops-health-title">Fleet health</h2>
        <p class="muted">Deterministic checks with no model. Last checked {{ lastChecked }}.</p>
      </div>
      <div class="actions">
        <span class="severity" :data-severity="overall">{{ SEVERITY_LABEL[overall] }}</span>
        <button class="btn" :disabled="busy" @click="runChecks">{{ busy ? 'Checking…' : 'Refresh checks' }}</button>
      </div>
    </header>
    <p v-if="actionError" role="alert" class="notice-warn">{{ actionError }}</p>
    <p v-if="error" role="status" class="notice-warn">{{ error }}</p>
    <p v-if="!loaded" role="status" class="muted">Loading fleet health…</p>
    <template v-else-if="status">
      <p v-if="status.error" role="alert" class="notice-warn">{{ status.error }}</p>
      <NoteFold v-if="!status.enabled" label="Automatic checks are off"><p v-if="!status.enabled" class="muted">Automatic checks are off on this host. Refresh still runs the configured checks on demand.</p></NoteFold>
      <p v-if="staleCount" role="status" class="notice-warn">{{ staleCount }} {{ staleCount === 1 ? 'check has' : 'checks have' }} no recent result.</p>

      <div class="trend">
        <div class="bars" aria-hidden="true">
          <span v-for="(n, i) in trend" :key="i" class="bar" :style="{ height: `${Math.round((n / trendMax) * 100)}%` }" />
        </div>
        <NoteFold label="About this trend"><p class="muted small">Fleet health reports per day, last 7 days (oldest first): {{ trend.join(', ') }}. A report is written only when a check changes, so a quiet day shows 0.</p></NoteFold>
      </div>

      <div class="filters">
        <label>Search checks<input v-model="query" type="search" class="input" placeholder="Search by name, kind or finding" autocomplete="off" /></label>
        <label>Severity<AppSelect v-model="level" aria-label="Severity"><option value="all">All severities</option><option value="crit">Critical</option><option value="missing">Missing</option><option value="warn">Warning</option><option value="ok">OK</option></AppSelect></label>
      </div>
      <p class="muted small">Showing {{ visible.length }} of {{ checks.length }} checks.</p>

      <p v-if="!checks.length" class="muted">No checks are configured. Add sources to the host collector configuration to see them here.</p>
      <p v-else-if="!visible.length" class="muted">No checks match these filters.</p>
      <ul v-else class="check-list" aria-label="Checks">
        <li v-for="s in visible" :key="s.id" class="check" :data-severity="s.status">
          <div class="check-head">
            <strong>{{ s.id }}</strong>
            <span class="severity" :data-severity="s.status">{{ SEVERITY_LABEL[s.status] }}</span>
            <span v-if="s.stale" class="severity" data-severity="stale">No recent result</span>
          </div>
          <p>{{ s.summary || 'No summary yet' }}</p>
          <p v-if="s.evidence" class="muted small">{{ s.evidence }}</p>
          <p class="muted small">
            {{ sinceLabel(s.since) }} · Checked {{ ago(s.checked_at, clock) }}
            · <RouterLink :to="linkFor(s.kind)">Open {{ pageLabel(linkFor(s.kind)) }}</RouterLink>
          </p>
        </li>
      </ul>

      <div v-if="status.schedules.length" class="schedules">
        <h3>Schedules</h3>
        <ul>
          <li v-for="item in status.schedules" :key="item.id" class="muted small">
            {{ item.label }} · {{ item.enabled ? `next ${dateLabel(item.next_due)}` : 'off' }}<span v-if="item.last_run"> · last run {{ dateLabel(item.last_run) }}</span>
          </li>
        </ul>
      </div>

      <p class="muted small">
        <template v-if="status.archive">Historic archive: {{ status.archive.archived }} copied{{ status.archive.already ? `, ${status.archive.already} already held` : '' }}. Originals are unchanged. Last updated {{ dateLabel(status.archive.at) }}.</template>
        <template v-else>No historic archive yet.</template>
        <template v-if="lastReport"> · <RouterLink :to="{ path: '/reports', query: { report: lastReport.id } }">Open the latest fleet health report</RouterLink></template>
      </p>
    </template>
  </section>
</template>
<style scoped>
.ops-health { margin: var(--gap-lg) 0; display: grid; gap: var(--gap); }
.health-head { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: var(--gap); }
.health-head h2, .schedules h3 { font-size: var(--font-size-lg); margin: 0; }
.schedules h3 { font-size: var(--font-size-md, 1rem); margin-top: var(--gap); }
.actions, .filters, .check-head { display: flex; align-items: center; gap: var(--gap); flex-wrap: wrap; }
.filters label { display: grid; gap: var(--gap-sm); flex: 1 1 200px; color: var(--text-muted); }
.trend { display: grid; gap: var(--gap-sm); }
.bars { display: flex; align-items: flex-end; gap: 4px; height: 40px; }
.bar { flex: 1; min-height: 2px; background: var(--accent); border-radius: 2px 2px 0 0; }
.check-list { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--gap-sm); }
.check { padding: var(--gap); border: 1px solid var(--surface-border); border-left: 3px solid var(--surface-border); border-radius: var(--radius-sm); overflow-wrap: anywhere; }
.check[data-severity='crit'] { border-left-color: var(--danger); }
.check[data-severity='warn'], .check[data-severity='missing'] { border-left-color: var(--warn); }
.check[data-severity='ok'] { border-left-color: var(--ok); }
.check p { margin: var(--gap-sm) 0 0; }
.severity { display: inline-block; padding: 0 var(--gap-sm); border: 1px solid currentColor; border-radius: var(--radius-sm); font-size: var(--font-size-xs); font-weight: 600; white-space: nowrap; }
.severity[data-severity='crit'] { color: var(--danger); }
.severity[data-severity='warn'], .severity[data-severity='missing'] { color: var(--warn); }
.severity[data-severity='ok'] { color: var(--ok); }
.severity[data-severity='stale'] { color: var(--text-muted); }
.schedules ul { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--gap-sm); }
</style>
