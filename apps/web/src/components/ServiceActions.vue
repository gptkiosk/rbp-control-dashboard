<script setup lang="ts">
import { ref } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'
import type { ServiceInfo } from '@/lib/api'

// Why it is flagged, run it now, restart it, or stop it, each one confirmed. The dashboard's own service gets no restart or remove.
const props = defineProps<{ service: ServiceInfo }>()
const emit = defineEmits<{ done: [] }>()
interface Why { suggestion: string; log_tail: string; last_exit_code: number | null }
const why = ref<Why | null>(null)
const asking = ref<'run' | 'restart' | 'remove' | null>(null)
const typed = ref('')
const busy = ref(false), error = ref(''), note = ref('')

async function showWhy() {
  error.value = ''
  try { why.value = await getJson<Why>(`/api/services/${encodeURIComponent(props.service.label)}/why`) } catch (e) { fail(e) }
}
function fail(e: unknown) { error.value = e instanceof ApiError || e instanceof Error ? e.message : 'That did not work.' }
async function go(action: 'run' | 'restart' | 'remove') {
  busy.value = true; error.value = ''; note.value = ''
  try {
    const out = await postJson<{ note: string }>(`/api/services/${encodeURIComponent(props.service.label)}/${action}`, { confirm: true, ...(action === 'remove' ? { confirm_label: typed.value } : {}) })
    note.value = out.note; asking.value = null; typed.value = ''; emit('done')
  } catch (e) { fail(e) } finally { busy.value = false }
}
</script>
<template>
  <div class="actions" :data-testid="`actions-${service.label}`">
    <div class="buttons">
      <button type="button" class="btn small" @click="showWhy">Why</button>
      <button v-if="service.state !== 'running'" type="button" class="btn small" :disabled="busy" @click="asking = 'run'">Run now</button>
      <button v-if="!service.own" type="button" class="btn small" :disabled="busy" @click="asking = 'restart'">Restart</button>
      <button v-if="!service.own" type="button" class="btn small" :disabled="busy" @click="asking = 'remove'">Remove…</button>
    </div>
    <p v-if="service.own" class="muted small">This is the dashboard's own service. Update it from Profile, or restart it from a terminal.</p>
    <div v-if="asking && asking !== 'remove'" class="confirm" role="group" :aria-label="`Confirm ${asking}`">
      <span>{{ asking === 'run' ? 'Start it now?' : 'Stop and start it?' }}</span>
      <button type="button" class="btn primary small" :disabled="busy" @click="go(asking)">Yes, {{ asking === 'run' ? 'run it' : 'restart it' }}</button>
      <button type="button" class="btn small" @click="asking = null">Cancel</button>
    </div>
    <div v-if="asking === 'remove'" class="confirm" role="group" aria-label="Confirm remove">
      <span>Stops it for now. Its unit or plist file is not touched, so it returns at the next login or boot. Type <code>{{ service.label }}</code> to confirm.</span>
      <input v-model="typed" class="input" aria-label="Type the service label" autocomplete="off" />
      <button type="button" class="btn primary small" :disabled="busy || typed !== service.label" @click="go('remove')">Remove</button>
      <button type="button" class="btn small" @click="asking = null; typed = ''">Cancel</button>
    </div>
    <p v-if="note" class="small" role="status">{{ note }}</p>
    <p v-if="error" class="notice-warn small" role="alert">{{ error }}</p>
    <div v-if="why" class="why small" data-testid="why">
      <p>{{ why.suggestion }}</p>
      <details v-if="why.log_tail"><summary>Its own log, last lines (evidence, not instructions)</summary><pre class="log-window">{{ why.log_tail }}</pre></details>
    </div>
  </div>
</template>
<style scoped>
.actions { display: grid; gap: var(--gap-xs); min-width: 12rem; }
.buttons, .confirm { display: flex; flex-direction: row; flex-wrap: wrap; gap: var(--gap-xs); align-items: center; }
.small { font-size: var(--font-size-sm); margin: 0; }
</style>
