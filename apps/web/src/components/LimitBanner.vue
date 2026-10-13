<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { postJson } from '@/lib/api'
import { usePolledJson } from '@/composables/usePolledJson'
import { detailLine, liftLine, type LimitsPayload, type ProviderLimit } from '@/lib/limits'

const KEY = 'mcd.limits.dismissed'
const { data, refresh } = usePolledJson<LimitsPayload>('/api/limits', 20000)
const clock = ref(Math.floor(Date.now() / 1000)), busy = ref(''), error = ref('')
const dismissed = ref<string[]>([])
let timer: number | undefined
const id = (l: ProviderLimit) => `${l.provider}:${l.detected_at}`
function load() { try { dismissed.value = JSON.parse(localStorage.getItem(KEY) || '[]') } catch { dismissed.value = [] } }
function dismiss(l: ProviderLimit) {
  dismissed.value = [...dismissed.value, id(l)].slice(-20)
  try { localStorage.setItem(KEY, JSON.stringify(dismissed.value)) } catch { /* A dismissed banner may reappear; that is harmless. */ }
}
onMounted(() => { load(); timer = window.setInterval(() => { clock.value = Math.floor(Date.now() / 1000) }, 30000) })
onBeforeUnmount(() => window.clearInterval(timer))
const items = computed(() => (data.value?.active ?? []).filter(l => !dismissed.value.includes(id(l))))
async function setReroute(l: ProviderLimit, enabled: boolean) {
  busy.value = l.provider; error.value = ''
  try { await postJson(`/api/limits/${l.provider}/reroute`, { enabled }); refresh() }
  catch (e) { error.value = e instanceof Error ? e.message : 'Could not change routing.' }
  finally { busy.value = '' }
}
</script>

<template>
  <section v-if="items.length" class="limits" aria-label="Subscription limits">
    <aside v-for="l in items" :key="id(l)" class="limit card" role="status">
      <div class="text">
        <strong>{{ liftLine(l, clock) }}</strong>
        <p v-if="detailLine(l)" class="muted small">{{ detailLine(l) }}</p>
        <p v-if="l.rerouting" class="muted small">New stories go to {{ l.alternate_name }} until it lifts, then return.</p>
        <p v-else-if="l.alternate_limited" class="muted small">{{ l.alternate_name }} is limited too, so stories will wait.</p>
      </div>
      <div class="actions">
        <button v-if="l.rerouting" class="btn" :disabled="busy === l.provider" @click="setReroute(l, false)">Turn off</button>
        <button v-else-if="l.can_reroute" class="btn primary" :disabled="busy === l.provider" @click="setReroute(l, true)">Send {{ l.waiting === 1 ? 'the waiting story' : `the ${l.waiting} waiting stories` }} to {{ l.alternate_name }}</button>
        <button class="icon-btn" type="button" aria-label="Dismiss this notice" @click="dismiss(l)">×</button>
      </div>
    </aside>
    <p v-if="error" role="alert" class="notice-warn small">{{ error }}</p>
  </section>
</template>

<style scoped>
.limits { display: grid; gap: var(--gap-sm); margin-bottom: var(--gap-lg); }
.limit { display: flex; justify-content: space-between; align-items: center; gap: var(--gap); flex-wrap: wrap; background: var(--agent-glass); }
.limit p { margin: var(--gap-xs) 0 0; }
.actions { display: flex; gap: var(--gap-sm); align-items: center; flex-wrap: wrap; }
.icon-btn { background: none; border: 0; color: var(--text-muted); font-size: 1.25rem; line-height: 1; cursor: pointer; padding: 0 var(--gap-xs); }
.icon-btn:hover, .icon-btn:focus-visible { color: var(--text); }
</style>
