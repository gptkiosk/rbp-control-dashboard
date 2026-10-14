<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, getJson, putJson } from '@/lib/api'
interface Source { id: string; root: string; available: boolean; mode: string; state: string; error: string | null }
interface Storage { sources: Source[]; allowed_roots: string[]; error: string | null }
const emit = defineEmits<{ changed: [] }>()
const data = ref<Storage | null>(null), ops = ref(''), hermes = ref('')
const busy = ref(false), error = ref(''), notice = ref(''), forbidden = ref(false)
function apply(value: Storage) {
  data.value = value
  ops.value = value.sources.find(s => s.id === 'ops')?.root ?? ''
  hermes.value = value.sources.find(s => s.id === 'hermes')?.root ?? ''
}
async function load() {
  try { apply(await getJson<Storage>('/api/report-storage')) }
  catch (e) {
    forbidden.value = e instanceof ApiError && (e.status === 403 || e.status === 401)
    error.value = forbidden.value ? 'Operator sign-in is required to configure this host.' : 'Host report storage settings are unavailable.'
  }
}
async function save(reset = false) {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    apply(await putJson<Storage>('/api/report-storage', { ops: ops.value, hermes: hermes.value, reset }))
    notice.value = reset ? 'Installation defaults restored.' : 'Host report folders saved.'
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : 'Report storage could not be saved.' }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <details class="card storage-panel">
    <summary>Host report storage · configure folders</summary>
    <p class="muted">These settings apply to everyone using this installation. Reports are read-only. Folder changes require operator sign-in.</p>
    <p v-if="error || data?.error" class="notice-warn" role="alert">{{ error || data?.error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <template v-if="data">
      <ul><li v-for="s in data.sources" :key="s.id"><strong>{{ s.id === 'ops' ? 'Ops reports' : 'Hermes archive' }}</strong> · {{ s.mode }} · {{ s.available ? 'available' : 'unavailable' }}<br /><code>{{ s.root || 'No folder selected' }}</code><p v-if="s.error" class="muted">{{ s.error }}</p></li></ul>
      <form @submit.prevent="save()">
        <label>Ops report folder<input v-model="ops" class="input" autocomplete="off" spellcheck="false" required /></label>
        <label>Hermes report archive (optional)<input v-model="hermes" class="input" autocomplete="off" spellcheck="false" /></label>
        <p class="muted">Use an existing absolute folder on the dashboard host inside one of these approved report roots:</p>
        <ul><li v-for="root in data.allowed_roots" :key="root"><code>{{ root }}</code></li></ul>
        <p class="muted">The host installer can add dedicated folders with MAC_CONTROL_REPORTS_ALLOWED_ROOTS. Create folders on the host first. Clearing the Hermes field disables its archive; restoring defaults uses the host environment and this installation’s data directory.</p>
        <div class="actions"><button class="btn primary" :disabled="busy || forbidden">Save host folders</button><button type="button" class="btn" :disabled="busy || forbidden" @click="save(true)">Restore installation defaults</button></div>
      </form>
    </template>
  </details>
</template>
<style scoped>
.storage-panel { margin: var(--gap-lg) 0; }
summary { cursor: pointer; font-weight: 600; }
label { display: grid; gap: var(--gap-sm); margin: var(--gap) 0; }
code { overflow-wrap: anywhere; }
ul { padding-left: 1.5em; list-style: disc; }
li { margin: var(--gap-sm) 0; }
.actions { display: flex; gap: var(--gap); flex-wrap: wrap; }
</style>
