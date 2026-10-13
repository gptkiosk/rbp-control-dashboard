<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import TimeSeriesChart, { type ChartLine } from '@/components/TimeSeriesChart.vue'
import ChipTag from '@/components/ChipTag.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import type { IconName } from '@/icons/icons'
import { navIcon } from '@/router/routes'
import StatTile from '@/components/StatTile.vue'
import type {
  MetricsCurrent,
  SeriesPayload,
  SeriesRange,
  TailscalePayload,
  TopProcessesPayload,
  UpdatesPayload,
} from '@/lib/api'
import {
  DASH,
  formatAge,
  formatBytes,
  formatGB,
  formatKBps,
  formatPct,
  formatTemp,
} from '@/lib/format'
import { throttlingStatus, undervoltageStatus } from '@/lib/piHealth'

const RANGES: SeriesRange[] = ['1h', '24h', '7d', '30d', '1y']
const range = ref<SeriesRange>('1h')

// Only what a Pi reports: no GPU, per-cluster CPU, power-rail or fan series.
const FIELDS = ['cpu_pct', 'mem_used', 'swap_used', 'cpu_temp', 'disk_used', 'net_rx_bps', 'net_tx_bps']

const current = usePolledJson<MetricsCurrent>('/api/metrics/current', 10_000)
const m = computed(() => current.data.value)
const throttling = computed(() => (m.value ? throttlingStatus(m.value) : null))
const undervoltage = computed(() => (m.value ? undervoltageStatus(m.value) : null))

const diskSub = computed(() => {
  const d = m.value
  if (!d || d.disk_used == null || d.disk_total == null) return DASH
  const filling = d.disk_days_to_full == null ? 'not filling' : `about ${Math.round(d.disk_days_to_full)} days to full`
  return `${formatBytes(d.disk_used)} of ${formatBytes(d.disk_total)} · ${filling}`
})

function usedOf(used: number | null | undefined, total: number | null | undefined): string {
  if (used == null || total == null) return DASH
  return `${formatBytes(used)} of ${formatBytes(total)}`
}

const series = usePolledJson<SeriesPayload>(
  () => `/api/metrics/series?range=${range.value}&fields=${FIELDS.join(',')}`,
  () => (range.value === '1h' ? 30_000 : 300_000),
)
const apps = usePolledJson<TopProcessesPayload>('/api/processes/top?limit=15', 10_000)
const tailscale = usePolledJson<TailscalePayload>('/api/tailscale', 30_000)
const updates = usePolledJson<UpdatesPayload>('/api/updates', 300_000)

const payload = computed(() => series.data.value?.series ?? null)

const charts: { title: string; icon: IconName; lines: ChartLine[]; format: (v: number | null | undefined) => string; zeroBased: boolean }[] = [
  {
    title: 'CPU %',
    icon: 'cpu',
    lines: [{ field: 'cpu_pct', label: 'CPU' }],
    format: (v) => formatPct(v, 0),
    zeroBased: true,
  },
  {
    title: 'Memory',
    icon: 'memory',
    lines: [
      { field: 'mem_used', label: 'Memory used' },
      { field: 'swap_used', label: 'Swap used' },
    ],
    format: formatGB,
    zeroBased: true,
  },
  {
    title: 'Temperature',
    icon: 'temperature',
    lines: [{ field: 'cpu_temp', label: 'SoC' }],
    format: formatTemp,
    zeroBased: false,
  },
  {
    title: 'Disk used',
    icon: 'disk',
    lines: [{ field: 'disk_used', label: 'Disk used' }],
    format: formatGB,
    zeroBased: true,
  },
  {
    title: 'Network',
    icon: 'network',
    lines: [
      { field: 'net_rx_bps', label: 'Down' },
      { field: 'net_tx_bps', label: 'Up' },
    ],
    format: formatKBps,
    zeroBased: true,
  },
]


const ts = computed(() => (tailscale.data.value && 'error' in tailscale.data.value ? null : tailscale.data.value))
const tsError = computed(() => {
  const t = tailscale.data.value
  return t && 'error' in t ? t.error : null
})
const upd = computed(() => {
  const u = updates.data.value
  return u && 'updates' in u ? u.updates : null
})
const updError = computed(() => {
  const u = updates.data.value
  return u && 'error' in u ? u.error : null
})

function connection(p: { online: boolean; direct_addr: string | null; relay: string | null }): string {
  if (!p.online) return DASH
  if (p.direct_addr) return 'direct'
  if (p.relay) return `relay (${p.relay})`
  return DASH
}

function lastSeen(iso: string | null): string {
  if (!iso) return DASH
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? DASH : d.toLocaleString()
}
</script>

<template>
  <section class="page" aria-labelledby="pi-title">
    <div class="heading">
      <h1 id="pi-title" class="page-title has-icon"><AppIcon :name="navIcon('pi')" size="lg" />Pi health</h1>
      <div class="ranges" role="group" aria-label="Time range">
        <button
          v-for="r in RANGES"
          :key="r"
          type="button"
          class="range"
          :aria-pressed="range === r ? 'true' : 'false'"
          @click="range = r"
        >
          {{ r }}
        </button>
      </div>
    </div>

    <p v-if="m" class="muted small" data-testid="sample-age">Sample taken {{ formatAge(m.sample_age_s) }}</p>
    <p v-if="current.error.value" class="error" role="alert">Could not load current readings: {{ current.error.value }}</p>

    <div v-if="m" class="tiles" data-testid="pi-tiles">
      <StatTile data-testid="tile-temp" label="Temperature" icon="temperature" :value="formatTemp(m.cpu_temp)" sub="SoC" />
      <StatTile data-testid="tile-throttling" label="Throttling" icon="alert" :value="throttling!.value">
        <template #sub>
          <ChipTag :tone="throttling!.tone">{{ throttling!.detail }}</ChipTag>
        </template>
      </StatTile>
      <StatTile data-testid="tile-undervoltage" label="Undervoltage" icon="power" :value="undervoltage!.value">
        <template #sub>
          <ChipTag :tone="undervoltage!.tone">{{ undervoltage!.detail }}</ChipTag>
        </template>
      </StatTile>
      <StatTile data-testid="tile-cpu" label="CPU" icon="cpu" :value="formatPct(m.cpu_pct)" :meter="m.cpu_pct" />
      <StatTile
        data-testid="tile-memory"
        label="Memory used" icon="memory"
        :value="formatPct(m.mem_used_pct)"
        :meter="m.mem_used_pct"
        :sub="usedOf(m.mem_used, m.mem_total)"
      />
      <StatTile
        data-testid="tile-swap"
        label="Swap" icon="swap"
        :value="formatBytes(m.swap_used)"
        :meter="m.swap_used_pct"
        :sub="`of ${formatBytes(m.swap_total)}`"
      />
      <StatTile
        data-testid="tile-disk"
        label="Disk (SD / NVMe)" icon="disk"
        :value="formatPct(m.disk_used_pct)"
        :meter="m.disk_used_pct"
        :sub="diskSub"
      />
    </div>

    <p v-if="series.error.value" class="error" role="alert">Could not load history: {{ series.error.value }}</p>
    <p v-else-if="series.pending.value" class="muted" role="status">Collecting first samples…</p>

    <div class="charts">
      <TimeSeriesChart
        v-for="c in charts"
        :key="c.title"
        :title="c.title"
        :icon="c.icon"
        :series="payload"
        :lines="c.lines"
        :format="c.format"
        :zero-based="c.zeroBased"
      />
    </div>

    <section class="card" aria-labelledby="apps-title">
      <h2 id="apps-title" class="section-title has-icon">
        <AppIcon name="apps" />
        Top processes
      </h2>
      <p v-if="apps.error.value" class="error" role="alert">Could not load processes: {{ apps.error.value }}</p>
      <div v-if="apps.data.value" class="table-scroll">
        <table class="data-table">
          <caption class="sr-only">Processes using the most memory</caption>
          <thead>
            <tr>
              <th scope="col">Process</th>
              <th scope="col" class="num">Memory</th>
              <th scope="col" class="num">CPU %</th>
              <th scope="col" class="num">Processes</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in apps.data.value.apps" :key="a.app">
              <th scope="row" class="plain">{{ a.app }}</th>
              <td class="num">{{ formatBytes(a.rss) }}</td>
              <td class="num">{{ formatPct(a.cpu_pct) }}</td>
              <td class="num">{{ a.count ?? DASH }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="card" aria-labelledby="ts-title">
      <h2 id="ts-title" class="section-title has-icon">
        <AppIcon name="peers" />
        Tailscale
      </h2>
      <p v-if="tsError" class="muted">Tailscale unavailable: {{ tsError }}</p>
      <p v-else-if="tailscale.error.value" class="error" role="alert">
        Could not load Tailscale: {{ tailscale.error.value }}
      </p>
      <template v-if="ts">
        <p>
          <ChipTag :tone="ts.backend_state === 'Running' ? 'ok' : 'warn'">{{ ts.backend_state }}</ChipTag>
          <span class="muted small gap-left">{{ ts.tailnet }}</span>
        </p>
        <p>
          <strong>{{ ts.self.hostname }}</strong>
          <span class="muted small gap-left">{{ ts.self.ips.join(' · ') }}</span>
        </p>
        <div v-if="ts.peers.length" class="table-scroll">
          <table class="data-table">
            <caption class="sr-only">Tailscale peers</caption>
            <thead>
              <tr>
                <th scope="col">Peer</th>
                <th scope="col">Status</th>
                <th scope="col">Connection</th>
                <th scope="col">Last seen</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in ts.peers" :key="p.dns_name || p.hostname">
                <th scope="row" class="plain">
                  {{ p.hostname }}
                  <span v-if="p.os" class="muted small"> · {{ p.os }}</span>
                </th>
                <td><ChipTag :tone="p.online ? 'ok' : 'muted'">{{ p.online ? 'online' : 'offline' }}</ChipTag></td>
                <td>{{ connection(p) }}</td>
                <td>{{ p.online ? DASH : lastSeen(p.last_seen) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="muted">No peers on this tailnet.</p>
      </template>
    </section>

    <section class="card" aria-labelledby="upd-title">
      <h2 id="upd-title" class="section-title has-icon">
        <AppIcon name="updates" />
        Pending updates
      </h2>
      <p class="muted small">Updates are read-only here. Install them with <code>sudo apt update &amp;&amp; sudo apt full-upgrade</code> on the Pi.</p>
      <p v-if="updError" class="muted">Could not check for updates: {{ updError }}</p>
      <p v-else-if="updates.pending.value" class="muted" role="status">Checking for updates…</p>
      <p v-else-if="updates.error.value" class="error" role="alert">{{ updates.error.value }}</p>
      <p v-else-if="upd && upd.length === 0" class="muted">Everything is up to date.</p>
      <ul v-else-if="upd" class="updates">
        <li v-for="u in upd" :key="u.label">
          <span class="title">{{ u.title }}</span>
          <span v-if="u.version" class="muted small">{{ u.version }}</span>
          <ChipTag v-if="u.requires_restart" tone="warn">Restart needed</ChipTag>
        </li>
      </ul>
    </section>
  </section>
</template>

<style scoped>
.heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
}

.page > p {
  margin: 0;
}

.error {
  color: var(--danger);
}

.ranges {
  display: inline-flex;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  overflow: hidden;
}

.range {
  padding: var(--gap-sm) var(--gap);
  background: var(--panel);
  color: var(--text-muted);
  border: 0;
  border-right: 1px solid var(--panel-border);
  font: inherit;
  cursor: pointer;
}

.range:last-child {
  border-right: 0;
}

.range:hover {
  background: var(--panel-raised);
  color: var(--text);
}

.range[aria-pressed='true'] {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: var(--font-weight-strong);
}

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, var(--tile-min-width)), 1fr));
  gap: var(--gap);
}

.charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, var(--card-min-width)), 1fr));
  gap: var(--gap);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.plain {
  color: var(--text);
  font-weight: var(--font-weight);
  white-space: normal;
}

.gap-left {
  margin-left: var(--gap-sm);
}

.updates {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.updates li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

.title {
  font-weight: var(--font-weight-strong);
}
</style>
