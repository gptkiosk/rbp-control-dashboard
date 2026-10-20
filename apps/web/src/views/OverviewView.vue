<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import PageHead from '@/components/PageHead.vue'
import StatTile from '@/components/StatTile.vue'
import ChipTag from '@/components/ChipTag.vue'
import OverviewAgents from '@/components/OverviewAgents.vue'
import AlertStatus from '@/components/AlertStatus.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import { navIcon } from '@/router/routes'
import type { MetricsCurrent, ServicesPayload, UpdatesPayload } from '@/lib/api'
import {
  DASH,
  formatAge,
  formatBytes,
  formatPct,
  formatRate,
  formatTemp,
} from '@/lib/format'
import { throttlingStatus, undervoltageStatus } from '@/lib/piHealth'

const current = usePolledJson<MetricsCurrent>('/api/metrics/current', 10_000)
const services = usePolledJson<ServicesPayload>('/api/services', 30_000)
const updates = usePolledJson<UpdatesPayload>('/api/updates', 300_000)

const m = computed(() => current.data.value)

const throttling = computed(() => (m.value ? throttlingStatus(m.value) : null))
const undervoltage = computed(() => (m.value ? undervoltageStatus(m.value) : null))

const diskSub = computed(() => {
  const d = m.value
  if (!d || d.disk_used_pct == null) return DASH
  if (d.disk_days_to_full == null) return 'not filling'
  return `about ${Math.round(d.disk_days_to_full)} days to full`
})

const attention = computed(() => services.data.value?.services.filter((s) => s.severity > 0).length ?? 0)

const updatesOk = computed(() => {
  const u = updates.data.value
  return u && 'updates' in u ? u : null
})
const updatesError = computed(() => {
  const u = updates.data.value
  return u && 'error' in u ? u.error : null
})
const restartCount = computed(() => updatesOk.value?.updates.filter((x) => x.requires_restart).length ?? 0)

function usedOf(used: number | null | undefined, total: number | null | undefined): string {
  if (used == null || total == null) return DASH
  return `${formatBytes(used)} of ${formatBytes(total)}`
}
</script>

<template>
  <section class="page" aria-labelledby="overview-title">
    <PageHead id="overview-title" title="Overview" :icon="navIcon('overview')" help="overview">
      <template #sub><span v-if="m" data-testid="sample-age">Sample taken {{ formatAge(m.sample_age_s) }}</span><span v-else>Live Pi and agent status.</span></template>
    </PageHead>

    <p v-if="current.pending.value" class="notice muted" role="status">Collecting first samples…</p>
    <p v-else-if="current.error.value" class="notice error" role="alert">
      Could not load metrics: {{ current.error.value }}
    </p>

    <div v-if="m" class="grid">
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
        label="Disk used (SD / NVMe)" icon="disk"
        :value="formatPct(m.disk_used_pct)"
        :meter="m.disk_used_pct"
        :sub="diskSub"
      />
      <StatTile
        data-testid="tile-temp"
        label="CPU temperature" icon="temperature"
        :value="formatTemp(m.cpu_temp)"
      />
      <StatTile data-testid="tile-throttling" label="Throttling" icon="alert" :value="throttling!.value">
        <template #sub>
          <ChipTag v-if="throttling!.tone !== 'muted'" class="flag-chip" :tone="throttling!.tone">{{ throttling!.detail }}</ChipTag><template v-else>{{ throttling!.detail }}</template>
        </template>
      </StatTile>
      <StatTile data-testid="tile-undervoltage" label="Undervoltage" icon="power" :value="undervoltage!.value">
        <template #sub>
          <ChipTag v-if="undervoltage!.tone !== 'muted'" class="flag-chip" :tone="undervoltage!.tone">{{ undervoltage!.detail }}</ChipTag><template v-else>{{ undervoltage!.detail }}</template>
        </template>
      </StatTile>
      <StatTile
        data-testid="tile-network"
        label="Network" icon="network"
        :value="`Down ${formatRate(m.net_rx_bps)}`"
        :sub="`Up ${formatRate(m.net_tx_bps)}`"
      />

      <StatTile
        data-testid="tile-services"
        label="Services" icon="services"
        :value="services.data.value ? `${services.data.value.services.length}` : DASH"
      >
        <template #sub>
          <span v-if="services.error.value">Could not load services</span>
          <span v-else-if="services.data.value">{{ attention }} need attention</span>
          <RouterLink to="/services" class="link-inline">View services</RouterLink>
        </template>
      </StatTile>
      <StatTile
        data-testid="tile-updates"
        label="Updates" icon="updates"
        :value="updatesOk ? `${updatesOk.updates.length}` : DASH"
      >
        <template #sub>
          <span v-if="updatesOk">{{ restartCount }} need a restart</span>
          <span v-else-if="updatesError">Could not check: {{ updatesError }}</span>
          <span v-else-if="updates.pending.value">Checking for updates…</span>
          <span v-else>{{ updates.error.value ?? DASH }}</span>
        </template>
      </StatTile>
    </div>
    <OverviewAgents />
    <AlertStatus />
  </section>
</template>

<style scoped>
.heading {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-sm);
}

.heading p,
.page > p {
  margin: 0;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, var(--tile-min-width)), 1fr));
  gap: var(--gap);
}

.notice {
  padding: var(--gap);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  background: var(--panel);
}

.notice.error {
  color: var(--danger);
  border-color: var(--danger);
}
/* Flag details can name several conditions: let the chip wrap inside its tile. */
.flag-chip { white-space: normal; max-width: 100%; }
</style>
