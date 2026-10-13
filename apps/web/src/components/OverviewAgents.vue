<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import OpenRouterSpend from '@/components/OpenRouterSpend.vue'
import ChipTag from '@/components/ChipTag.vue'
import { useNow } from '@/composables/useNow'
import { usePolledJson } from '@/composables/usePolledJson'
import type { Agent, AgentId, AgentsPayload, UsagePayload } from '@/lib/api'
import { formatDuration, formatSince, formatUsd, unpricedModels, UNPRICED_HINT } from '@/lib/format'

const now = useNow()
const agents = usePolledJson<AgentsPayload>('/api/agents', 5000)
const usage = usePolledJson<UsagePayload>('/api/agents/usage?period=24h', 15000)
const receivedAt = ref(now.value)
watch(agents.data, () => (receivedAt.value = now.value))
const order: AgentId[] = ['openclaw', 'hermes', 'claude', 'codex']
const fleet = computed(() =>
  [...(agents.data.value?.agents ?? [])].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id)),
)
const stats = (id: AgentId) => usage.data.value?.overview.find((a) => a.agent === id)
const stale = computed(() => !!agents.error.value || !!agents.pending.value || now.value - receivedAt.value > 20)
function status(a: Agent) {
  if (stale.value) return { label: 'Status unavailable', tone: 'warn' as const }
  if (!a.available) return { label: 'Not installed', tone: 'muted' as const }
  if (a.current.length) return { label: 'Running', tone: 'ok' as const }
  if (!usage.error.value && !usage.pending.value && (stats(a.id)?.last_active ?? 0) >= now.value - 60)
    return { label: 'Recent activity', tone: 'accent' as const }
  return { label: 'Available', tone: 'muted' as const }
}
function related(a: Agent) {
  const items = (a.subagents?.agents ?? []).map((s) => ({
    id: s.id,
    name: s.name?.startsWith(`${s.id} - `) ? s.name.slice(s.id.length + 3) : s.name || s.id,
    last: s.last_active_s == null ? null : (agents.data.value?.subagents_checked_at ?? receivedAt.value) - s.last_active_s,
    parent: false,
    scope: 'configured',
  }))
  for (const s of usage.data.value?.sessions.filter((s) => s.agent === a.id) ?? []) {
    const existing = items.find((i) => i.id === s.id)
    if (existing) {
      if (s.last_active != null) existing.last = Math.max(existing.last ?? 0, s.last_active)
    } else items.push({
      id: s.id, name: s.name || `${s.parent ? 'Sub-agent' : 'Session'} ${a.id === 'hermes' ? s.id.slice(-8) : s.id.slice(0, 8)}`,
      last: s.last_active, parent: !!s.parent, scope: s.scope,
    })
  }
  return items.sort((a, b) => (b.last ?? 0) - (a.last ?? 0))
}
function detail(id: AgentId, target?: string) {
  return { path: '/agents', query: { agent: id, ...(target ? { target } : {}) } }
}
</script>

<template>
  <section class="overview-agents" aria-labelledby="overview-agents-title">
    <header class="agents-heading">
      <div>
        <h2 id="overview-agents-title" class="section-title has-icon"><AppIcon name="agents" />Agents</h2>
        <p class="muted small">Live fleet status · work every 5 seconds · usage every 15 seconds</p>
      </div>
      <RouterLink to="/agents" class="link-inline">Open agent explorer <AppIcon name="chevron-right" /></RouterLink>
    </header>
    <p v-if="agents.error.value" class="warning-text small" role="alert">Agent status could not refresh: {{ agents.error.value }}.<template v-if="agents.data.value"> Last received information is shown.</template></p>
    <p v-else-if="agents.pending.value || !agents.loaded.value" class="muted small" role="status">Waiting for agent status…</p>
    <p v-if="usage.error.value || usage.pending.value" class="warning-text small" role="status">Usage could not refresh; captured activity and costs may be out of date.</p>
    <div v-if="fleet.length" class="agent-grid">
      <article v-for="a in fleet" :key="a.id" class="agent-card" :data-agent="a.id">
        <header class="agent-heading">
          <RouterLink :to="detail(a.id)" class="agent-name">{{ a.name }}</RouterLink>
          <ChipTag :tone="status(a).tone">{{ status(a).label }}</ChipTag>
        </header>
        <p class="small muted">{{ a.role === 'manager' ? 'Manager' : 'Worker' }} · {{ a.subagents?.processes.length ?? '—' }} observed processes</p>
        <p v-if="a.failed_24h" class="warning-text small">{{ a.failed_24h }} failed RCD {{ a.failed_24h === 1 ? 'run' : 'runs' }} · last 24h</p>
        <div class="work">
          <template v-if="a.current.length">
            <strong>{{ a.current.length }} running RCD {{ a.current.length === 1 ? 'turn' : 'turns' }}</strong>
            <RouterLink :to="a.current[0]!.thread_id ? { path: '/chat', query: { thread: String(a.current[0]!.thread_id) } } : { path: '/tasks', query: { card: String(a.current[0]!.card_id) } }">
              {{ a.current[0]!.title || `Run #${a.current[0]!.run_id}` }}
            </RouterLink>
            <span class="small muted">{{ a.current[0]!.model || 'Model not reported' }} · {{ formatDuration(a.current[0]!.running_s + Math.max(0, now - receivedAt)) }}<template v-if="a.current.length > 1"> · +{{ a.current.length - 1 }} more</template></span>
          </template>
          <template v-else>
            <strong>No RCD turns running</strong>
            <span class="small muted">Last captured activity: {{ stats(a.id)?.last_active ? formatSince(stats(a.id)!.last_active, now) : 'not reported' }}</span>
            <span class="small muted">{{ stats(a.id)?.models.slice(0, 2).map(m => m.model).join(' · ') || a.default_model || 'Model not reported' }}<template v-if="(stats(a.id)?.models.length ?? 0) > 2"> · +{{ stats(a.id)!.models.length - 2 }} models</template></span>
          </template>
        </div>
        <dl class="totals">
          <div><dt>API equivalent · 24h</dt><dd>{{ formatUsd(stats(a.id)?.api_equivalent_usd) }}</dd></div>
          <div><dt>Captured sessions · 24h</dt><dd>{{ stats(a.id)?.sessions ?? '—' }}</dd></div>
        </dl>
        <p v-if="stats(a.id)?.unpriced" class="warning-text small" :title="UNPRICED_HINT">{{ stats(a.id)!.unpriced }} unpriced records · cost is partial<template v-if="stats(a.id)?.unpriced_models?.length"> · {{ unpricedModels(stats(a.id)?.unpriced_models) }}</template></p>
        <div class="related">
          <span class="small muted">Sub-agents & sessions</span>
          <ul v-if="related(a).length">
            <li v-for="s in related(a).slice(0, 3)" :key="s.id">
              <RouterLink :to="detail(a.id, s.id)" :title="`${s.name} · ${s.id}`">{{ s.name }}</RouterLink>
              <span class="small muted">{{ s.scope === 'session lifetime' ? 'Lifetime snapshot' : s.last ? formatSince(s.last, now) : 'No captured activity' }}<template v-if="s.parent"> · sub-agent</template></span>
            </li>
          </ul>
          <span v-else class="small muted">None reported</span>
          <RouterLink v-if="related(a).length > 3" :to="detail(a.id)" class="small">+{{ related(a).length - 3 }} more in explorer</RouterLink>
        </div>
        <p class="source small muted">Source: {{ usage.data.value?.coverage[a.id]?.state ?? 'starting' }}<template v-if="agents.data.value?.subagents_checked_at"> · sub-agents checked {{ formatSince(agents.data.value.subagents_checked_at, now) }}</template></p>
      </article>
    </div>
    <OpenRouterSpend :data="usage.data.value?.openrouter" />
    <p class="muted small">Observed processes can be idle. Recent activity means a captured update within the last minute. API equivalents are estimates; subscriptions and detailed usage are in the explorer.</p>
  </section>
</template>

<style scoped>
.overview-agents { display: flex; flex-direction: column; gap: var(--gap); background: var(--chat-glow); border-radius: var(--radius); }
.agents-heading, .agent-heading { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: var(--gap-sm); }
h2, p { margin: 0; }
.agents-heading p { margin-top: var(--gap-xs); }
.link-inline { display: inline-flex; gap: var(--gap-xs); align-items: center; }
.agent-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--gap); }
.agent-card { min-width: 0; display: flex; flex-direction: column; gap: var(--gap-sm); padding: var(--gap-lg); background: var(--agent-glass); border: 1px solid var(--glass-border); border-radius: var(--radius); -webkit-backdrop-filter: blur(var(--glass-blur)); backdrop-filter: blur(var(--glass-blur)); }
.agent-name { font-size: var(--font-size-lg); font-weight: var(--font-weight-strong); color: var(--text); }
.agent-name:hover { color: var(--accent); }
.work, .related { display: flex; flex-direction: column; gap: var(--gap-xs); min-width: 0; }
.work { padding: var(--gap) 0; }
.work a, .work span, .related a { overflow-wrap: anywhere; }
.totals { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--gap); margin: 0; padding: var(--gap); background: var(--glass-bg); border-radius: var(--radius-sm); }
dt { color: var(--text-muted); font-size: var(--font-size-xs); }
dd { margin: 0; font-size: var(--font-size-lg); }
.related { padding-top: var(--gap-sm); }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--gap-sm); }
li { display: flex; flex-direction: column; gap: var(--gap-xs); }
.source { border-top: 1px solid var(--glass-border); padding-top: var(--gap-sm); margin-top: auto; }
@supports not (backdrop-filter: blur(1px)) { .agent-card { background: var(--panel); } }
@media (max-width: 1100px) { .agent-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .agent-grid { grid-template-columns: 1fr; } .agent-card { padding: var(--gap); } }
</style>
