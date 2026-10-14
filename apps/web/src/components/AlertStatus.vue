<script setup lang="ts">
import { ref } from 'vue'
import { postJson } from '@/lib/api'
import { usePolledJson } from '@/composables/usePolledJson'
import { dateLabel } from '@/lib/operations'
import AppIcon from '@/components/AppIcon.vue'
interface AlertEvent { id: string; message: string; status: string; created_at: number; sent_at: number | null; error: string | null; reviewed_at: number | null }
interface Alerts { enabled: boolean; delivery_enabled: boolean; destination: string; checked_at: number | null; error: string | null; attention: number; pending: number; events: AlertEvent[] }
const { data, error, refresh } = usePolledJson<Alerts>('/api/alerts', 30000)
const actionError = ref<string | null>(null)
const reviewing = ref<string | null>(null)
async function acknowledge(event: AlertEvent) {
  reviewing.value = event.id
  actionError.value = null
  try { await postJson(`/api/alerts/${event.id}/acknowledge`); refresh() }
  catch (e) { actionError.value = e instanceof Error ? e.message : String(e) }
  finally { reviewing.value = null }
}
const labels: Record<string, string> = { pending: 'Pending', delivering: 'Sending', sent: 'Sent', uncertain: 'Check delivery', held: 'Held', expired: 'Expired', reviewed: 'Reviewed' }
</script>
<template>
  <section class="card alert-status" aria-labelledby="alerts-title">
    <header><h2 id="alerts-title" class="section-title has-icon"><AppIcon name="alert" />Alerts</h2><span class="muted small">{{ data?.delivery_enabled ? 'Discord delivery enabled' : data?.enabled ? 'Monitoring · delivery paused' : 'Delivery paused' }}</span></header>
    <p v-if="error || data?.error || actionError" role="status" class="notice-warn">{{ error || data?.error || actionError }}</p>
    <template v-if="data">
      <p class="muted small">Failed runs and service crash loops · Last check: {{ dateLabel(data.checked_at) }}<span v-if="data.pending"> · {{ data.pending }} pending</span></p>
      <p v-if="data.attention" role="status" class="notice-warn">{{ data.attention }} alert{{ data.attention === 1 ? ' needs' : 's need' }} delivery review. Check the Discord channel before resending.</p>
      <details><summary>Recent alerts <span class="muted">({{ data.events.length }})</span></summary>
        <ul v-if="data.events.length"><li v-for="event in data.events" :key="event.id"><div class="event-heading"><strong>{{ labels[event.status] || event.status }}<span v-if="event.reviewed_at"> · Reviewed</span></strong><small class="muted">{{ dateLabel(event.sent_at ?? event.created_at) }}</small></div><p class="message">{{ event.message }}</p><p v-if="event.error" class="muted small">{{ event.error }}</p><button v-if="['uncertain', 'held'].includes(event.status) && !event.reviewed_at" class="btn" :disabled="reviewing !== null" @click="acknowledge(event)">{{ reviewing === event.id ? 'Saving…' : 'Mark reviewed' }}</button></li></ul>
        <p v-else class="muted small">No alerts recorded yet.</p>
      </details>
    </template>
    <p v-else-if="!error" class="muted small">Loading alert status…</p>
  </section>
</template>
<style scoped>
header, .event-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--gap); flex-wrap: wrap; }
ul { margin: var(--gap) 0 0; padding: 0; list-style: none; }
li { border-top: 1px solid var(--surface-border); padding: var(--gap) 0; }
summary { cursor: pointer; padding: var(--gap-sm) 0; }
.message { white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--font-size-sm); margin: var(--gap-sm) 0; }
.alert-status p { overflow-wrap: anywhere; }
</style>
