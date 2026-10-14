<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ChipTag from '@/components/ChipTag.vue'
import { useNow } from '@/composables/useNow'
import type { AgentId, OpenRouterSpending } from '@/lib/api'
import { formatSince, formatUsd } from '@/lib/format'
const props = defineProps<{ data?: OpenRouterSpending; agent?: AgentId }>()
const now = useNow()
const names: Partial<Record<AgentId, string>> = { hermes: 'Hermes', openclaw: 'OpenClaw' }
const visible = computed(() => !props.agent || props.agent === 'hermes' || props.agent === 'openclaw')
const meters = computed(() => props.data?.meters.filter(m => !props.agent || m.agents.includes(props.agent)) ?? [])
const unavailable = computed(() => props.data?.unavailable_agents.filter(a => !props.agent || a === props.agent) ?? [])
const windows = [
  { label: 'Today · UTC', field: 'today_usd', byok: 'byok_today_usd' },
  { label: 'This week · UTC', field: 'week_usd', byok: 'byok_week_usd' },
  { label: 'This month · UTC', field: 'month_usd', byok: 'byok_month_usd' },
  { label: 'Key lifetime', field: 'lifetime_usd', byok: 'byok_lifetime_usd' },
] as const
</script>

<template>
  <section v-if="visible" id="openrouter-spending" class="router-spend" aria-label="OpenRouter actual spending">
    <header class="spend-head">
      <h2 class="section-title has-icon"><AppIcon name="cost" />OpenRouter actual spending</h2>
      <span class="small muted">Refreshes every minute · provider calendar windows</span>
    </header>
    <p v-if="!data" class="small muted" role="status">Waiting for OpenRouter spending…</p>
    <p v-for="a in unavailable" :key="a" class="small muted">{{ names[a] }}: no readable default OpenRouter key configured.</p>
    <article v-for="meter in meters" :key="meter.id" class="meter">
      <header class="spend-head">
        <strong>{{ meter.agents.length > 1 ? 'Shared key' : 'Default key' }} · {{ meter.agents.map(a => names[a] || a).join(' + ') }}</strong>
        <ChipTag :tone="meter.state === 'ready' && meter.updated_at && now - meter.updated_at < 120 ? 'ok' : 'warn'">
          {{ meter.state === 'ready' && meter.updated_at && now - meter.updated_at < 120 ? 'Connected' : meter.updated_at ? 'Last known spending' : 'Unavailable' }}
        </ChipTag>
      </header>
      <p v-if="meter.state !== 'ready'" class="small warning-text" role="status">OpenRouter could not refresh. {{ meter.updated_at ? 'Last successful values are shown.' : 'Charges are not available yet.' }}</p>
      <dl class="spend-grid">
        <div v-for="w in windows" :key="w.field">
          <dt>{{ w.label }}</dt>
          <dd>{{ formatUsd(meter[w.field], 5) }}</dd>
          <small class="muted">OpenRouter credits used</small>
          <p v-if="meter[w.byok] != null" class="byok"><span class="muted">External BYOK usage</span><strong>{{ formatUsd(meter[w.byok], 5) }}</strong></p>
        </div>
      </dl>
      <p class="small muted">Key-wide spending includes every app using this key.{{ meter.agents.length > 1 ? ' This shared total is shown once; Hermes and OpenClaw charges cannot be separated by key.' : '' }} Model, session and sub-agent filters apply to captured usage below.</p>
      <p class="small muted">BYOK means your own provider key; its reported external usage is separate from OpenRouter credits and provider invoices.</p>
      <footer class="small muted">
        <template v-if="meter.updated_at">Updated {{ formatSince(meter.updated_at, now) }} · </template>
        <template v-if="meter.limit_usd != null">Key limit {{ formatUsd(meter.limit_usd) }}{{ meter.limit_reset ? ' / '+meter.limit_reset : '' }}{{ meter.include_byok_in_limit ? ' including BYOK' : '' }} · remaining {{ formatUsd(meter.remaining_usd) }} · </template>
        <a href="https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key" target="_blank" rel="noopener noreferrer">OpenRouter reported usage</a>
      </footer>
    </article>
  </section>
</template>

<style scoped>
.router-spend { display: flex; flex-direction: column; gap: var(--gap); }
.spend-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--gap-sm); }
.meter { display: flex; flex-direction: column; gap: var(--gap); min-width: 0; padding: var(--gap-lg); background: var(--agent-glass); border: 1px solid var(--glass-border); border-radius: var(--radius); -webkit-backdrop-filter: blur(var(--glass-blur)); backdrop-filter: blur(var(--glass-blur)); }
h2, p { margin: 0; }
.spend-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--gap); margin: 0; }
.spend-grid > div { min-width: 0; padding: var(--gap); background: var(--glass-bg); border-radius: var(--radius-sm); }
dt { color: var(--text-muted); font-size: var(--font-size-sm); }
dd { margin: var(--gap-xs) 0; font-size: var(--font-size-xl); font-weight: var(--font-weight-strong); overflow-wrap: anywhere; }
.byok { margin-top: var(--gap); padding-top: var(--gap-sm); border-top: 1px solid var(--glass-border); display: flex; flex-direction: column; gap: var(--gap-xs); font-size: var(--font-size-xs); }
footer { border-top: 1px solid var(--glass-border); padding-top: var(--gap-sm); }
@supports not (backdrop-filter: blur(1px)) { .meter { background: var(--panel); } }
@media (max-width: 1000px) { .spend-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .meter { padding: var(--gap); } .spend-grid { gap: var(--gap-sm); } dd { font-size: var(--font-size-lg); } }
</style>
