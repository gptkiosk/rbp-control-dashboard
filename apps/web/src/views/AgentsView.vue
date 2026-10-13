<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import OpenRouterSpend from '@/components/OpenRouterSpend.vue'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import ChipTag from '@/components/ChipTag.vue'
import ReportedValue from '@/components/ReportedValue.vue'
import AgentBillingDialog from '@/components/AgentBillingDialog.vue'
import { useNow } from '@/composables/useNow'
import { usePolledJson } from '@/composables/usePolledJson'
import type { Agent, AgentId, AgentsPayload, UsagePayload, UsageSummary } from '@/lib/api'
import { formatCount, formatDuration, formatSince, formatUsd } from '@/lib/format'
import { stageLabel, stageTone } from '@/lib/cards'
import { agentName } from '@/lib/selectLabels'
import { useGuideAction } from '@/composables/useGuideAction'

const route = useRoute()
const router = useRouter()
const now = useNow()
const ids: AgentId[] = ['openclaw', 'hermes', 'claude', 'codex']
const selectedId = ref<AgentId>(
  ids.includes(route.query.agent as AgentId) ? (route.query.agent as AgentId) : 'openclaw',
)
const target = ref(typeof route.query.target === 'string' ? route.query.target : '')
const period = ref<'24h' | '7d' | 'month'>('month')
const billingOpen = ref(false)
useGuideAction('billing', () => { billingOpen.value = true })
const processId = ref('')
const { data, error } = usePolledJson<AgentsPayload>('/api/agents', 5000)
const usagePath = computed(
  () =>
    `/api/agents/usage?period=${period.value}&agent=${selectedId.value}${target.value ? `&target=${encodeURIComponent(target.value)}` : ''}`,
)
const {
  data: usage,
  error: usageError,
  refresh: refreshUsage,
} = usePolledJson<UsagePayload>(usagePath, 15000)
const selected = computed(() => data.value?.agents.find((a) => a.id === selectedId.value))
const overview = (id: AgentId) => usage.value?.overview.find((a) => a.agent === id)
const processes = computed(() => selected.value?.subagents?.processes ?? [])
const process = computed(() => processes.value.find((p) => String(p.pid) === processId.value))
const configured = computed(() => selected.value?.subagents?.agents ?? [])
const configuredTarget = computed(() => configured.value.find((a) => a.id === target.value))
const sessions = computed(() => usage.value?.sessions ?? [])
const targetOptions = computed(() => {
  const options = configured.value.map((a) => ({ id: a.id, label: `${a.name || a.id} · ${a.id}`, name: agentName(a.name, a.id), detail: `${a.id}${a.default ? ' · Default' : ''}` }))
  for (const s of sessions.value)
    if (!options.some((o) => o.id === s.id))
      options.push({ id: s.id, label: `${s.name || (s.parent ? 'Sub-agent' : 'Session')} · ${s.id}`, name: s.name && s.name !== s.id ? s.name : s.parent ? 'Sub-agent' : 'Session', detail: s.id })
  for (const s of selected.value?.subagents?.sessions ?? [])
    if (!options.some((o) => o.id === s.id))
      options.push({ id: s.id, label: `${s.title || 'Session'} · ${s.id}`, name: s.title || 'Session', detail: s.id })
  return options
})
const allModels = computed(() => [
  ...new Set(
    usage.value?.overview.flatMap((a) => a.models.map((m) => m.model)).filter((m) => m !== 'not reported') ??
      [],
  ),
])
const source = computed(() => usage.value?.coverage[selectedId.value])
const periodLabel = computed(() =>
  period.value === 'month' ? 'This month' : period.value === '24h' ? 'Last 24 hours' : 'Last 7 days',
)
const lifetime = computed(
  () => !!target.value && sessions.value.find((s) => s.id === target.value)?.scope === 'session lifetime',
)
const summary = computed<UsageSummary | undefined>(() =>
  lifetime.value ? sessions.value.find((s) => s.id === target.value) : usage.value?.summary,
)
const stats = computed(() =>
  summary.value
    ? [
        { label: 'API equivalent', value: summary.value.api_equivalent_usd, format: formatUsd },
        { label: 'Input tokens', value: summary.value.input_tokens, format: formatCount },
        { label: 'Output tokens', value: summary.value.output_tokens, format: formatCount },
        { label: 'Cache read', value: summary.value.cached_input_tokens, format: formatCount },
        { label: 'Cache write', value: summary.value.cache_write_tokens, format: formatCount },
        { label: 'Sessions', value: summary.value.sessions, format: formatCount },
      ]
    : [],
)
const receivedAt = ref(Date.now() / 1000)
watch(data, () => (receivedAt.value = Date.now() / 1000))
watch(
  () => route.query,
  (query) => {
    if (ids.includes(query.agent as AgentId)) selectedId.value = query.agent as AgentId
    target.value = typeof query.target === 'string' ? query.target : ''
  },
)
function chooseAgent(id: AgentId) {
  selectedId.value = id
  target.value = ''
  processId.value = ''
  void router.replace({ query: { agent: id } })
}
watch(target, (value) => {
  void router.replace({ query: { agent: selectedId.value, ...(value ? { target: value } : {}) } })
})
watch(processes, (values) => {
  if (!values.some((p) => String(p.pid) === processId.value))
    processId.value = values[0] ? String(values[0].pid) : ''
})
function activityText(a: Agent) {
  return `${a.subagents?.processes.length ?? 0} live processes · ${a.current.length} RCD runs`
}
function saved() {
  refreshUsage()
}
</script>
<template>
  <section class="page agents-page" aria-labelledby="agents-title">
    <header class="page-head">
      <div>
        <h1 id="agents-title" class="page-title has-icon"><AppIcon name="agents" size="lg" />Agents</h1>
        <p class="muted">Your agent fleet, sub-agents, activity and model usage.</p>
      </div>
      <div class="toolbar">
        <label class="sr-only" for="usage-period">Usage period</label
        ><AppSelect id="usage-period" v-model="period" class="input">
          <option value="month">This month</option>
          <option value="24h">Last 24 hours</option>
          <option value="7d">Last 7 days</option></AppSelect
        ><button class="btn" @click="billingOpen = true"><AppIcon name="cost" />Billing & rates</button>
      </div>
    </header>
    <p v-if="error" class="error-text" role="alert">Could not load agents: {{ error }}</p>
    <p v-if="usageError" class="error-text" role="alert">Could not load usage: {{ usageError }}</p>
    <div v-if="data" class="fleet">
      <button
        v-for="a in [...data.agents].sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id))"
        :key="a.id"
        class="glass fleet-tile"
        :class="{ selected: a.id === selectedId }"
        :data-agent="a.id"
        :aria-pressed="a.id === selectedId"
        @click="chooseAgent(a.id)"
      >
        <span class="tile-head"
          ><strong>{{ a.name }}</strong
          ><AppIcon name="agents"
        /></span>
        <span class="chips"
          ><ChipTag :tone="a.role === 'manager' ? 'accent' : 'muted'" data-testid="role-chip">{{
            a.role === 'manager' ? 'Manager' : 'Worker'
          }}</ChipTag
          ><ChipTag :tone="a.available ? 'ok' : 'danger'">{{
            a.available ? 'Installed' : 'Not found'
          }}</ChipTag></span
        >
        <span class="small muted">{{ activityText(a) }}</span>
        <span class="tile-cost"
          ><ReportedValue :value="overview(a.id)?.api_equivalent_usd" :format="formatUsd" /><small
            class="muted"
            >{{ periodLabel }} · API equivalent</small
          ></span
        >
        <span class="small muted"
          >{{ overview(a.id)?.sessions ?? '—' }} sessions · {{ a.subagents?.agents?.length ?? 0 }} configured
          agents</span
        >
        <span class="small muted">Source: {{ usage?.coverage[a.id]?.state || 'starting' }}</span>
        <span v-if="overview(a.id)?.unpriced" class="small warning-text"
          >{{ overview(a.id)?.unpriced }} unpriced usage records</span
        >
        <span v-if="!a.available" class="small muted binary">{{ a.binary }}</span>
      </button>
    </div>
    <OpenRouterSpend :data="usage?.openrouter" :agent="selectedId" />
    <article v-if="selected" class="glass detail">
      <header class="detail-head">
        <div>
          <span class="eyebrow">AGENT EXPLORER</span>
          <h2 class="section-title">{{ selected.name }}</h2>
          <p class="muted small">
            {{ activityText(selected) }} · {{ targetOptions.length }} agents / sessions available
          </p>
        </div>
        <div class="selectors">
          <label for="explorer-agent"
            >Agent<AppSelect
              id="explorer-agent"
              :value="selectedId"
              class="input"
              @change="chooseAgent(($event.target as HTMLSelectElement).value as AgentId)"
            >
              <option v-for="a in data?.agents" :key="a.id" :value="a.id" :data-description="a.role === 'manager' ? 'Manager' : 'Worker'">{{ a.name }}</option>
            </AppSelect></label
          ><label for="explorer-target"
            >Sub-agent / session<AppSelect id="explorer-target" v-model="target" class="input">
              <option value="">All sub-agents & sessions</option>
              <option v-for="o in targetOptions" :key="o.id" :value="o.id" :data-label="o.name" :data-description="o.detail">{{ o.label }}</option>
            </AppSelect></label
          >
        </div>
      </header>
      <div class="coverage small">
        <AppIcon name="activity" /><span
          >Telemetry: {{ source?.state || 'starting'
          }}{{ source?.pending_files ? ` · ${source.pending_files} files still indexing` : ''
          }}<template v-if="source?.checked_at"> · checked {{ formatSince(source.checked_at, now) }}</template
          >. Process presence does not imply an active model turn.</span
        >
      </div>
      <section v-if="configuredTarget" class="target-facts">
        <h3>
          {{ configuredTarget.name || configuredTarget.id }}
          <ChipTag v-if="configuredTarget.default" tone="accent">Default</ChipTag>
        </h3>
        <dl class="facts">
          <div>
            <dt>Configured model</dt>
            <dd><ReportedValue :value="configuredTarget.model" /></dd>
          </div>
          <div>
            <dt>Last session activity</dt>
            <dd>
              <ReportedValue
                :value="configuredTarget.last_active_s"
                :format="(v) => formatDuration(v) + ' ago'"
              />
            </dd>
          </div>
          <div>
            <dt>Bindings</dt>
            <dd>{{ configuredTarget.bindings }}</dd>
          </div>
          <div class="wide">
            <dt>Workspace</dt>
            <dd>{{ configuredTarget.workspace || 'not reported' }}</dd>
          </div>
        </dl>
      </section>
      <p v-if="overview(selectedId)?.lifetime_sessions_excluded" class="warning-text small">
        {{ overview(selectedId)?.lifetime_sessions_excluded }} session lifetime counters cross this period’s
        boundary and are excluded from its totals. Choose a session below to inspect its lifetime usage.
      </p>
      <div id="usage-summary" class="section-head">
        <h3>{{ lifetime ? 'Session lifetime usage' : periodLabel + ' usage' }}</h3>
        <span v-if="summary?.unpriced" class="warning-text small"
          >{{ summary.unpriced }} records unpriced · cost is partial</span
        >
      </div>
      <dl class="metrics">
        <div v-for="s in stats" :key="s.label">
          <dt>{{ s.label }}</dt>
          <dd><ReportedValue :value="s.value" :format="s.format" /></dd>
        </div>
      </dl>
      <p v-if="!usage && !usageError" class="muted" role="status">Loading usage…</p>
      <div class="detail-columns">
        <section class="subpanel">
          <h3>Model usage</h3>
          <p v-if="!summary?.models.length" class="muted small">No captured usage for this selection.</p>
          <div v-else class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Input / output</th>
                  <th>API equivalent</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in summary.models" :key="m.model">
                  <td>
                    {{ m.model
                    }}<small v-if="m.unpriced" class="warning-text">{{ m.unpriced }} unpriced</small>
                  </td>
                  <td>
                    <ReportedValue :value="m.input_tokens" :format="formatCount" /> /
                    <ReportedValue :value="m.output_tokens" :format="formatCount" />
                  </td>
                  <td><ReportedValue :value="m.api_equivalent_usd" :format="formatUsd" /></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section class="subpanel subscription">
          <h3>Monthly billing comparison</h3>
          <dl class="facts">
            <div>
              <dt>Captured API equivalent · month to date</dt>
              <dd>
                <ReportedValue :value="overview(selectedId)?.month_api_equivalent_usd" :format="formatUsd" />
              </dd>
            </div>
            <div>
              <dt>
                {{
                  overview(selectedId)?.billing.mode === 'subscription'
                    ? 'Subscription · full month'
                    : 'Billing mode'
                }}
              </dt>
              <dd>
                <ReportedValue
                  v-if="overview(selectedId)?.billing.mode === 'subscription'"
                  :value="overview(selectedId)?.month_subscription_usd"
                  :format="formatUsd"
                /><span v-else>API usage</span>
              </dd>
            </div>
            <div v-if="overview(selectedId)?.billing.mode === 'subscription'" class="wide">
              <dt>Estimated savings · month to date</dt>
              <dd class="savings">
                <ReportedValue :value="overview(selectedId)?.month_savings_usd" :format="formatUsd" />
              </dd>
            </div>
          </dl>
          <p class="muted small">
            All {{ selected.name }} sub-agents included.
            {{
              overview(selectedId)?.month_unpriced
                ? `${overview(selectedId)?.month_unpriced} unpriced records; comparison is partial.`
                : 'Captured usage only.'
            }}
            <template v-if="overview(selectedId)?.month_lifetime_sessions_excluded">
              {{ overview(selectedId)?.month_lifetime_sessions_excluded }} older lifetime sessions excluded
              from monthly totals.</template
            >
            <template v-if="source?.state !== 'ready'"> Source collection is incomplete.</template>
            Negative savings mean usage is below subscription break-even.
          </p>
          <button class="btn" @click="billingOpen = true">Configure billing</button>
        </section>
      </div>
      <div class="detail-columns">
        <section class="subpanel">
          <h3>Live processes</h3>
          <p v-if="!processes.length" class="muted small">No processes observed at the last check.</p>
          <template v-else
            ><label class="sr-only" for="process-select">Live process</label
            ><AppSelect id="process-select" v-model="processId" class="input">
              <option v-for="p in processes" :key="p.pid" :value="String(p.pid)">
                {{ p.kind }} · PID {{ p.pid }}
              </option>
            </AppSelect>
            <dl v-if="process" class="facts">
              <div>
                <dt>Uptime</dt>
                <dd>{{ formatDuration(process.running_s) }}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd><ReportedValue :value="process.model" /></dd>
              </div>
              <div>
                <dt>Session</dt>
                <dd><ReportedValue :value="process.session" /></dd>
              </div>
              <div class="wide">
                <dt>Working directory</dt>
                <dd><ReportedValue :value="process.cwd" /></dd>
              </div></dl
          ></template>
        </section>
        <section class="subpanel">
          <h3>RCD work · last 24 hours</h3>
          <dl class="facts">
            <div>
              <dt>Runs / failed</dt>
              <dd>{{ selected.runs_24h }} / {{ selected.failed_24h }}</dd>
            </div>
            <div>
              <dt>Busy time</dt>
              <dd><ReportedValue :value="selected.busy_s_24h" :format="formatDuration" /></dd>
            </div>
            <div>
              <dt>Default model</dt>
              <dd><ReportedValue :value="selected.default_model" /></dd>
            </div>
            <div v-if="selected.last_run">
              <dt>Last RCD run</dt>
              <dd>
                <ChipTag :tone="stageTone(selected.last_run.stage)">{{
                  stageLabel(selected.last_run.stage)
                }}</ChipTag>
                {{ formatSince(selected.last_run.ended_at ?? selected.last_run.started_at, now) }}
              </dd>
            </div>
          </dl>
          <ul v-if="selected.current.length" class="current">
            <li v-for="r in selected.current" :key="r.run_id">
              <RouterLink
                :to="
                  r.thread_id
                    ? { path: '/chat', query: { thread: String(r.thread_id) } }
                    : { path: '/tasks', query: { card: String(r.card_id) } }
                "
                >{{ r.title || `Run #${r.run_id}` }}</RouterLink
              >
              · {{ formatDuration(r.running_s + Math.max(0, now - receivedAt)) }}
            </li>
          </ul>
        </section>
      </div>
      <section class="subpanel session-list">
        <div class="section-head">
          <h3>Sub-agents & sessions</h3>
          <button v-if="target" class="btn" @click="target = ''">Show all</button>
        </div>
        <p v-if="!targetOptions.length" class="muted small">No sub-agents or sessions reported yet.</p>
        <div v-else class="session-grid">
          <button
            v-for="o in targetOptions"
            :key="o.id"
            class="session-btn"
            :class="{ selected: target === o.id }"
            @click="target = o.id"
          >
            <strong>{{ o.label }}</strong
            ><span class="muted small"
              >{{ sessions.find((s) => s.id === o.id)?.scope ?? 'Configured · no captured usage'
              }}<template v-if="sessions.find((s) => s.id === o.id)?.last_active">
                · {{ formatSince(sessions.find((s) => s.id === o.id)!.last_active!, now) }}</template
              ></span
            >
          </button>
        </div>
      </section>
      <section class="subpanel activity">
        <div class="section-head">
          <h3>Recent activity</h3>
          <span class="muted small">Latest 80 captured records</span>
        </div>
        <p v-if="!usage?.activity.length" class="muted small">No captured activity for this selection.</p>
        <div v-else class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>When / agent or session</th>
                <th>Model</th>
                <th>Input / output</th>
                <th>API equivalent</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in usage.activity" :key="r.id">
                <td>
                  {{ formatSince(r.ts, now) }}<small>{{ r.target || r.session_id }}</small
                  ><small v-if="r.parent">Sub-agent of {{ r.parent }}</small
                  ><small v-if="r.scope === 'session lifetime'" class="warning-text"
                    >Lifetime snapshot · not a single turn</small
                  >
                </td>
                <td>
                  {{ r.model || 'not reported'
                  }}<small>{{ r.source }}{{ r.stage ? ' · ' + r.stage : '' }}</small>
                </td>
                <td>
                  <ReportedValue :value="r.input_tokens" :format="formatCount" /> /
                  <ReportedValue :value="r.output_tokens" :format="formatCount" />
                </td>
                <td>
                  <ReportedValue :value="r.api_equivalent_usd" :format="formatUsd" /><small>{{
                    r.cost_basis
                  }}</small>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <p class="muted small">{{ usage?.note }}</p>
      <p class="muted small">{{ selected.notes }}</p>
    </article>
    <AgentBillingDialog
      v-if="billingOpen && data"
      :agents="data.agents"
      :models="allModels"
      @close="billingOpen = false"
      @saved="saved"
    />
  </section>
</template>
<style scoped>
.agents-page {
  background: var(--chat-glow);
  border-radius: var(--radius);
}
.page-head,
.detail-head,
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
  flex-wrap: wrap;
}
p,
h3 {
  margin: 0;
}
h3 {
  font-size: var(--font-size);
}
.page-head p {
  margin-top: var(--gap-xs);
}
.toolbar,
.chips {
  display: flex;
  gap: var(--gap-sm);
  align-items: center;
}
.toolbar .input {
  width: auto;
}
.fleet {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--gap);
}
.glass {
  background: var(--agent-glass);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius);
  -webkit-backdrop-filter: blur(var(--glass-blur));
  backdrop-filter: blur(var(--glass-blur));
}
.fleet-tile {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding: var(--gap-lg);
  text-align: left;
  font: inherit;
  color: var(--text);
  cursor: pointer;
  min-width: 0;
  transition: border-color var(--transition);
}
.fleet-tile:hover,
.selected {
  border-color: var(--accent);
  background: var(--agent-glass-selected);
}
.tile-head {
  display: flex;
  justify-content: space-between;
  gap: var(--gap-sm);
}
.tile-cost {
  display: flex;
  flex-direction: column;
  font-size: var(--font-size-xl);
  margin: var(--gap-sm) 0;
}
.tile-cost small {
  font-size: var(--font-size-xs);
}
.binary,
dd {
  overflow-wrap: anywhere;
}
.detail {
  padding: var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
  min-width: 0;
}
.eyebrow {
  font-size: var(--font-size-xs);
  color: var(--accent);
  letter-spacing: var(--eyebrow-spacing);
}
.selectors {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: var(--gap);
  max-width: 100%;
  flex: 1;
  min-width: min(100%, var(--card-min-width));
}
.selectors label {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  min-width: 0;
  font-size: var(--font-size-sm);
  color: var(--text-muted);
}
.coverage {
  display: flex;
  gap: var(--gap-sm);
  align-items: start;
  color: var(--text-muted);
}
.metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--gap);
  padding: var(--gap-lg);
  background: var(--accent-soft);
  border-radius: var(--radius);
}
dl {
  margin: 0;
}
dt {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}
dd {
  margin: 0;
}
.metrics dd {
  font-size: var(--font-size-lg);
  margin-top: var(--gap-xs);
}
.detail-columns {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: var(--gap-lg);
}
.subpanel,
.target-facts {
  padding: var(--gap-lg);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius);
  background: var(--glass-bg);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-width: 0;
}
.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap);
}
.wide {
  grid-column: 1 / -1;
}
.savings {
  font-size: var(--font-size-xl);
  color: var(--accent);
}
.subscription .btn {
  align-self: start;
}
.table-scroll {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
  text-align: left;
}
th {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-strong);
}
th,
td {
  padding: var(--gap-sm);
  border-bottom: 1px solid var(--glass-border);
  vertical-align: top;
}
td {
  overflow-wrap: anywhere;
}
td small {
  display: block;
  color: var(--text-muted);
  margin-top: var(--gap-xs);
}
.activity table {
  min-width: var(--agent-activity-width);
}
.session-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, var(--tile-min-width)), 1fr));
  gap: var(--gap-sm);
}
.session-btn {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  color: var(--text);
  background: var(--agent-glass);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius);
  padding: var(--gap);
  font: inherit;
  text-align: left;
  cursor: pointer;
  overflow-wrap: anywhere;
  min-width: 0;
}
.session-btn.selected {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.current {
  margin: 0;
  padding-left: var(--gap-lg);
}
@supports not (backdrop-filter: blur(1px)) {
  .glass {
    background: var(--panel);
  }
  .fleet-tile.selected {
    background: var(--panel-raised);
  }
}
@media (max-width: 1100px) {
  .fleet {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 700px) {
  .detail-columns {
    grid-template-columns: 1fr;
  }
  .selectors {
    grid-template-columns: 1fr;
  }
  .detail {
    padding: var(--gap);
  }
  .fleet-tile {
    padding: var(--gap);
  }
  .toolbar {
    flex-wrap: wrap;
  }
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .chips {
    flex-wrap: wrap;
  }
}
@media (max-width: 420px) {
  .fleet {
    grid-template-columns: 1fr;
  }
}
</style>
