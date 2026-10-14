<script setup lang="ts">
import { computed } from 'vue'
import { useHealthStore } from '@/stores/health'

const health = useHealthStore()

const label = computed(() => {
  if (health.state === 'ok') return `v${health.version} · ${health.gitSha}`
  if (health.state === 'error') return 'API unreachable'
  return 'Checking…'
})

function formatUptime(total: number): string {
  const s = Math.floor(total)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s % 60}s`
  return `${s}s`
}

const tooltip = computed(() => {
  if (health.state === 'ok' && health.uptimeS !== null) {
    return `API uptime: ${formatUptime(health.uptimeS)}`
  }
  if (health.state === 'error') return 'Could not reach /healthz'
  return 'Checking API health'
})
</script>

<template>
  <span class="badge" :title="tooltip" role="status" :data-state="health.state">
    <span class="dot" aria-hidden="true"></span>
    <span class="text">{{ label }}</span>
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-xs) var(--gap-sm);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-pill);
  background: var(--panel);
  font-size: var(--font-size-sm);
  color: var(--text-muted);
  white-space: nowrap;
}

.dot {
  width: var(--dot-size);
  height: var(--dot-size);
  border-radius: 50%;
  background: var(--text-muted);
}

.badge[data-state='ok'] .dot {
  background: var(--ok);
}

.badge[data-state='error'] .dot {
  background: var(--danger);
}

.badge[data-state='ok'] {
  color: var(--text);
}
</style>
