<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import ChipTag from '@/components/ChipTag.vue'
import ServiceActions from '@/components/ServiceActions.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import type { ServiceInfo, ServicesPayload } from '@/lib/api'
import { DASH } from '@/lib/format'
import { navIcon } from '@/router/routes'

const { data, error, pending, loaded, refresh } = usePolledJson<ServicesPayload>('/api/services', 30_000)

function exitText(code: number | null | undefined, fallback: string | null): string {
  if (code != null && code < 0) return `Stopped by signal ${Math.abs(code)}`
  if (code != null) return `Last exit ${code}`
  return fallback ?? DASH
}

function num(v: number | null | undefined): string {
  return v == null ? DASH : String(v)
}

function runs24(s: ServiceInfo): string {
  return `${num(s.runs_24h)} / ${num(s.allowed_runs_24h)} allowed`
}
</script>

<template>
  <section class="page" aria-labelledby="services-title">
    <h1 id="services-title" class="page-title has-icon"><AppIcon :name="navIcon('services')" size="lg" />Services</h1>
    <p class="muted small note">Crash loop = restarts in 24 h beyond what the job's schedule explains.</p>

    <p v-if="error" class="error" role="alert">Could not load services: {{ error }}</p>
    <p v-else-if="pending" class="muted" role="status">Collecting service state…</p>
    <p v-else-if="!loaded" class="muted" role="status">Loading…</p>

    <div v-if="data" class="table-scroll">
      <table class="data-table services">
        <caption class="sr-only">Background services, most severe first</caption>
        <thead>
          <tr>
            <th scope="col">Service</th>
            <th scope="col">Schedule</th>
            <th scope="col">State</th>
            <th scope="col">PID</th>
            <th scope="col">Runs (total)</th>
            <th scope="col">Runs in 24 h</th>
            <th scope="col">Last exit</th>
            <th scope="col">Flags</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in data.services" :key="`${s.domain}/${s.label}`" :data-severity="s.severity">
            <th scope="row" class="name" data-label="Service">
              <span class="label"><template v-for="(part, i) in s.label.split('.')" :key="i">{{ i ? '.' : '' }}<wbr v-if="i" />{{ part }}</template></span>
              <span v-if="s.program" class="program muted">{{ s.program }}</span>
            </th>
            <td data-label="Schedule">{{ s.schedule }}</td>
            <td data-label="State">
              <ChipTag :tone="s.state === 'running' ? 'ok' : 'muted'">{{ s.state }}</ChipTag>
            </td>
            <td data-label="PID" class="num">{{ num(s.pid) }}</td>
            <td data-label="Runs (total)" class="num">{{ num(s.runs) }}</td>
            <td data-label="Runs in 24 h" class="num">{{ runs24(s) }}</td>
            <td data-label="Last exit">{{ s.last_exit ?? DASH }}</td>
            <td data-label="Flags">
              <div class="flags">
                <ChipTag v-if="s.flags.includes('crash_loop')" tone="danger">
                  <AppIcon name="alert" size="sm" />
                  Crash loop
                </ChipTag>
                <ChipTag v-if="s.flags.includes('last_exit_nonzero')" tone="warn">
                  {{ exitText(s.last_exit_code, s.last_exit) }}
                </ChipTag>
                <span v-if="s.flags.length === 0" class="muted">{{ DASH }}</span>
              </div>
            </td>
            <td data-label="Actions"><ServiceActions :service="s" @done="refresh()" /></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.page > p {
  margin: 0;
}

.error {
  color: var(--danger);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.services {
  min-width: var(--table-min-width);
}

.name {
  font-weight: var(--font-weight);
  color: var(--text);
  white-space: normal;
  min-width: var(--service-col-min-width);
}

.label {
  display: block;
  font-weight: var(--font-weight-strong);
  /* Break only after dots (via <wbr>), never mid-word. */
  overflow-wrap: normal;
  word-break: normal;
}

.program {
  display: block;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  overflow-wrap: anywhere;
}

.flags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
}

/* Severity bar on the first cell (table layout). */
tr[data-severity='2'] > th:first-child {
  box-shadow: inset var(--severity-bar-width) 0 0 var(--danger);
}

tr[data-severity='1'] > th:first-child {
  box-shadow: inset var(--severity-bar-width) 0 0 var(--warn);
}

@media (max-width: 767.98px) {
  .table-scroll {
    overflow-x: visible;
    border: 0;
    background: transparent;
  }

  .services {
    min-width: 0;
  }

  .services,
  .services tbody,
  .services tr,
  .services td,
  .services th[scope='row'] {
    display: block;
  }

  .services thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }

  .services tr {
    margin-bottom: var(--gap);
    padding: var(--gap-sm) 0;
    background: var(--card-glass);
    border: 1px solid var(--surface-border);
    border-left-width: var(--severity-bar-width);
    border-radius: var(--surface-radius);
  }

  tr[data-severity='2'] {
    border-left-color: var(--danger);
  }

  tr[data-severity='1'] {
    border-left-color: var(--warn);
  }

  tr[data-severity='2'] > th:first-child,
  tr[data-severity='1'] > th:first-child {
    box-shadow: none;
  }

  .services td,
  .services th[scope='row'] {
    border-bottom: 0;
    padding: var(--gap-xs) var(--gap);
  }

  .services td {
    display: flex;
    justify-content: space-between;
    gap: var(--gap);
    text-align: right;
  }

  .services td::before {
    content: attr(data-label);
    color: var(--text-muted);
    text-align: left;
    flex: none;
  }

  .flags {
    justify-content: flex-end;
  }
}
</style>
