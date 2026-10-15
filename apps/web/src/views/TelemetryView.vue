<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import AppSelect from '@/components/AppSelect.vue'
import BarList from '@/components/BarList.vue'
import DonutChart from '@/components/DonutChart.vue'
import StackedBars from '@/components/StackedBars.vue'
import CoordinatorScorecard from '@/components/CoordinatorScorecard.vue'
import ModelProfiles from '@/components/ModelProfiles.vue'
import StatTile from '@/components/StatTile.vue'
import { ApiError, getJson } from '@/lib/api'
import { FILTERS, minutes, money, percent, seconds, type FilterKey, type Telemetry } from '@/lib/telemetry'

const data = ref<Telemetry | null>(null)
const error = ref(''), loading = ref(false)
const days = ref('30')
const filters = ref<Record<FilterKey, string>>({ job: '', property: '', kind: '', risk: '', size: '', tier: '', assignee: '', agent: '', model: '' })
const LABELS: Record<FilterKey, string> = { job: 'Job', property: 'Property', kind: 'Kind', risk: 'Risk', size: 'Size', tier: 'Route', assignee: 'Assigned to', agent: 'Agent', model: 'Model' }

async function load() {
  loading.value = true; error.value = ''
  try {
    const q = new URLSearchParams({ days: days.value })
    for (const key of FILTERS) if (filters.value[key]) q.set(key, filters.value[key])
    data.value = await getJson<Telemetry>(`/api/telemetry?${q.toString()}`)
  } catch (e) {
    error.value = e instanceof ApiError && (e.status === 401 || e.status === 403) ? 'Operator sign-in is required.' : (e instanceof Error ? e.message : 'Telemetry could not be read.')
  } finally { loading.value = false }
}
function reset() { for (const key of FILTERS) filters.value[key] = ''; void load() }
const active = computed(() => FILTERS.some(k => filters.value[k]))
const t = computed(() => data.value?.tiles)
const OUTCOME = [{ key: 'open', label: 'Open', color: 'var(--accent)' }, { key: 'done', label: 'Done', color: 'var(--ok)' }, { key: 'failed', label: 'Failed', color: 'var(--danger)' }]
const RUNS = [{ key: 'ok', label: 'Succeeded', color: 'var(--ok)' }, { key: 'bad', label: 'Did not succeed', color: 'var(--danger)' }]
const DONE = [{ key: 'done', label: 'Done', color: 'var(--ok)' }, { key: 'rest', label: 'Not done', color: 'var(--accent)' }]
const STATUS_COLOR: Record<string, string> = { backlog: 'var(--text-muted, #8b949e)', queued: 'var(--accent)', running: 'var(--warn)', review: '#a371f7', done: 'var(--ok)', failed: 'var(--danger)' }
const when = (ts: number) => new Date(ts * 1000).toLocaleString()
onMounted(load)
</script>
<template>
  <section class="page" aria-labelledby="telemetry-title">
    <h1 id="telemetry-title" class="page-title has-icon"><AppIcon name="activity" size="lg" />Jobs &amp; telemetry</h1>
    <p class="muted lead">How work is going across jobs and stories: who it is assigned to (a person or an agent), the agent and model that ran it, time, and cost. A job is one approved plan revision.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>

    <form class="card filters" aria-label="Filters" @submit.prevent="load">
      <label>Period<AppSelect v-model="days" aria-label="Period" @update:model-value="load"><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="365">Last year</option></AppSelect></label>
      <label v-for="key in FILTERS" :key="key">{{ LABELS[key] }}<AppSelect v-model="filters[key]" :aria-label="LABELS[key]" @update:model-value="load"><option value="">All</option><option v-for="o in data?.options[key] ?? []" :key="o" :value="o">{{ o }}</option></AppSelect></label>
      <button v-if="active" type="button" class="btn" @click="reset">Clear filters</button>
    </form>

    <template v-if="data && t">
      <div class="tiles">
        <StatTile label="Unassigned" :value="String(t.unassigned)" sub="open, nobody or no agent" />
        <StatTile label="In progress" :value="String(t.in_progress)" sub="queued or running" />
        <StatTile label="Waiting for you" :value="String(t.waiting_for_you)" sub="needs a decision" />
        <StatTile :label="`Completed, ${t.completed_days} days`" :value="String(t.completed)" />
        <StatTile label="Estimates missing" :value="String(t.estimates_missing)" sub="open work without one" />
        <StatTile label="Failed" :value="String(t.failed)" />
      </div>
      <p class="muted small totals">Reported cost {{ money(data.totals.cost_usd) }} · API-equivalent {{ money(data.totals.api_equivalent_usd) }} · {{ data.totals.tokens.toLocaleString() }} tokens · {{ data.totals.unpriced_runs }} unpriced {{ data.totals.unpriced_runs === 1 ? 'run' : 'runs' }}. {{ data.note }}</p>

      <div class="grid">
        <DonutChart title="Workload by status" :slices="data.by_status.map(s => ({ label: s.column, value: s.count, color: STATUS_COLOR[s.column] }))" />
        <DonutChart title="Work by route" :slices="data.by_tier.map(x => ({ label: x.tier, value: x.count }))" />
        <StackedBars title="Work by property" :parts="OUTCOME" :rows="data.by_property.map(p => ({ label: p.property, values: { open: p.open, done: p.done, failed: p.failed }, hint: `first pass ${percent(p.first_pass_rate)}, median ${minutes(p.median_minutes)}` }))" empty="No work yet." />
        <StackedBars title="Work by assignee" :parts="OUTCOME" :rows="data.by_assignee.map(a => ({ label: `${a.name} (${a.type})`, values: { open: a.open, done: a.done, failed: a.failed } }))" />
        <StackedBars title="Jobs" :parts="OUTCOME" :rows="data.jobs.map(j => ({ label: `${j.job} ${j.title}`, values: { open: j.open, done: j.done, failed: j.failed }, hint: `${j.job}: estimate ${minutes(j.estimate_minutes)}, actual ${minutes(j.actual_minutes)}, cost ${money(j.cost_usd)}` }))" empty="No approved plans yet. Stories made from a plan appear here, one row per plan revision." />
        <StackedBars title="Runs by model" :parts="RUNS" :rows="data.models.map(m => ({ label: `${m.agent} · ${m.model}`, values: { ok: m.succeeded, bad: m.runs - m.succeeded }, hint: `${percent(m.success_rate)} success, median ${seconds(m.median_seconds)}, cost ${money(m.cost_usd)}, API-equivalent ${money(m.api_equivalent_usd)}` }))" empty="No runs in this period." />
        <StackedBars title="Work by kind" :parts="DONE" :rows="data.by_kind.map(k => ({ label: k.kind, values: { done: k.done, rest: k.stories - k.done }, hint: `median ${minutes(k.median_minutes)}, first pass ${percent(k.first_pass_rate)}` }))" />
        <BarList title="Completed per week" :items="data.velocity.map(v => ({ label: v.week, value: v.done }))" empty="No completed work in the last eight weeks." />
        <BarList title="Median time per kind (minutes)" :items="data.by_kind.filter(k => k.median_minutes != null).map(k => ({ label: k.kind, value: Math.round(k.median_minutes!) }))" empty="No finished work with a recorded time." />
      </div>

      <details class="card detail" aria-label="Jobs table">
        <summary>Jobs: the numbers</summary>
        <p v-if="!data.jobs.length" class="muted small">No approved plans yet. Stories made from a plan appear here, one row per plan revision.</p>
        <div v-else class="table-scroll"><table class="data-table">
          <caption class="sr-only">Jobs</caption>
          <thead><tr><th>Job</th><th>Plan</th><th class="num">Stories</th><th class="num">Done</th><th class="num">Open</th><th class="num">Failed</th><th class="num">Estimate</th><th class="num">Actual</th><th class="num">Cost</th><th class="num">API-equivalent</th></tr></thead>
          <tbody><tr v-for="j in data.jobs" :key="j.job"><td>{{ j.job }}</td><td>{{ j.title }}</td><td class="num">{{ j.stories }}</td><td class="num">{{ j.done }}</td><td class="num">{{ j.open }}</td><td class="num">{{ j.failed }}</td><td class="num">{{ minutes(j.estimate_minutes) }}</td><td class="num">{{ minutes(j.actual_minutes) }}</td><td class="num">{{ money(j.cost_usd) }}</td><td class="num">{{ money(j.api_equivalent_usd) }}</td></tr></tbody>
        </table></div>
      </details>

      <details class="card detail" aria-label="Agents and models table">
        <summary>Agents and models: the numbers</summary>
        <p class="muted small">The model that actually served each run, which can differ from the one requested after a fallback.</p>
        <p v-if="!data.models.length" class="muted small">No runs in this period.</p>
        <div v-else class="table-scroll"><table class="data-table">
          <caption class="sr-only">Agents and models</caption>
          <thead><tr><th>Agent</th><th>Model</th><th>Route</th><th class="num">Runs</th><th class="num">Success</th><th class="num">Median time</th><th class="num">Tokens</th><th class="num">Cost</th><th class="num">API-equivalent</th><th class="num">Served instead of requested</th></tr></thead>
          <tbody><tr v-for="m in data.models" :key="`${m.agent}|${m.model}|${m.tier}`"><td>{{ m.agent }}</td><td>{{ m.model }}</td><td>{{ m.tier }}</td><td class="num">{{ m.runs }}</td><td class="num">{{ percent(m.success_rate) }}</td><td class="num">{{ seconds(m.median_seconds) }}</td><td class="num">{{ m.tokens.toLocaleString() }}</td><td class="num">{{ money(m.cost_usd) }}</td><td class="num">{{ money(m.api_equivalent_usd) }}</td><td class="num">{{ m.served_instead_of_requested }}</td></tr></tbody>
        </table></div>
      </details>

      <details class="card detail" aria-label="Kinds of work table">
        <summary>Kinds of work: the numbers</summary>
        <p v-if="!data.by_kind.length" class="muted small">No work yet.</p>
        <div v-else class="table-scroll"><table class="data-table">
          <caption class="sr-only">By kind of work</caption>
          <thead><tr><th>Kind</th><th class="num">Work</th><th class="num">Done</th><th class="num">Median time</th><th class="num">First pass</th><th class="num">Actual over estimate</th></tr></thead>
          <tbody><tr v-for="k in data.by_kind" :key="k.kind"><td>{{ k.kind }}</td><td class="num">{{ k.stories }}</td><td class="num">{{ k.done }}</td><td class="num">{{ minutes(k.median_minutes) }}</td><td class="num">{{ percent(k.first_pass_rate) }}</td><td class="num">{{ k.median_actual_over_estimate == null ? '–' : `×${k.median_actual_over_estimate}` }}</td></tr></tbody>
        </table></div>
      </details>

      <section class="card" aria-label="Latest activity">
        <h2 class="section-title">Latest activity</h2>
        <p v-if="!data.activity.length" class="muted small">Nothing has finished yet.</p>
        <ul v-else class="activity">
          <li v-for="a in data.activity" :key="`${a.card_id}-${a.at}`"><strong>{{ a.title }}</strong> <span class="muted small">{{ a.outcome }} · {{ a.assignee }} · {{ a.model ?? a.agent }}{{ a.job ? ` · ${a.job}` : '' }} · {{ when(a.at) }}</span></li>
        </ul>
      </section>
      <CoordinatorScorecard />
      <ModelProfiles />
    </template>
    <p v-else-if="loading" class="muted" role="status">Loading…</p>
  </section>
</template>
<style scoped>
.page { display: grid; gap: var(--gap); }
.lead { max-width: 72ch; line-height: var(--line-height); margin: 0; }
.small { font-size: var(--font-size-sm); margin: 0; }
.filters { display: flex; flex-direction: row; flex-wrap: wrap; gap: var(--gap); align-items: end; }
.filters label { display: grid; gap: var(--gap-xs); font-size: var(--font-size-sm); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: var(--gap); }
.totals { max-width: 100ch; line-height: var(--line-height); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: var(--gap); }
.detail summary { cursor: pointer; font-weight: 600; }
.detail[open] summary { margin-bottom: var(--gap-sm); }
.activity { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--gap-sm); }
h2 { margin: 0; }
</style>
