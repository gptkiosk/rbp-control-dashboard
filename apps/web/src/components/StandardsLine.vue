<script setup lang="ts">
import { ref, watch } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'
import type { Standards, StandardsProposal } from '@/lib/standards'

// One line on the project page saying which repository standards the plan is made under. A missing or unreadable file is a
// warning, never an error: planning continues without it. Failing to ask at all shows nothing rather than a false claim.
const props = defineProps<{ projectId: number; revision?: number }>()
const data = ref<Standards | null>(null)
const proposals = ref<StandardsProposal[]>([])
const busy = ref(false), error = ref('')

async function load() {
  try { data.value = await getJson<Standards>(`/api/projects/${props.projectId}/standards`) } catch { data.value = null }
  try { proposals.value = (await getJson<{ proposals?: StandardsProposal[] }>(`/api/standards/proposals?project_id=${props.projectId}`)).proposals ?? [] } catch { proposals.value = [] }
}
async function decide(p: StandardsProposal, verb: 'approve' | 'reject') {
  busy.value = true; error.value = ''
  try { await postJson(`/api/standards/proposals/${p.id}/${verb}`, {}) } catch (e) { error.value = e instanceof ApiError || e instanceof Error ? e.message : 'The decision could not be recorded.' }
  finally { busy.value = false; await load() }
}
const pending = (list: StandardsProposal[]) => list.filter(p => p.status === 'pending')
watch(() => [props.projectId, props.revision], load, { immediate: true })
</script>
<template>
  <div v-if="data" class="standards" data-testid="standards">
    <p v-if="data.state === 'ok' && data.source === 'starter'" class="small" data-testid="starter">
      <strong>Starter standards</strong> ({{ data.starter_from ?? 'shipped' }}) · {{ data.areas.length }} areas · {{ data.checks.length }} checks.
      <span class="muted">{{ data.message || 'This repository has no standards of its own.' }}</span>
    </p>
    <p v-else-if="data.state === 'ok'" class="small">
      <strong>Standards:</strong> {{ data.property ?? 'this repository' }} · {{ data.areas.length }} {{ data.areas.length === 1 ? 'area' : 'areas' }} ·
      {{ data.checks.length }} {{ data.checks.length === 1 ? 'check' : 'checks' }} · <span class="mono" :title="data.sha256 ?? ''">{{ data.sha256?.slice(0, 12) }}</span>
    </p>
    <p v-else class="notice-warn small" role="status"><strong>No standards in use.</strong> {{ data.message }}</p>
    <section v-if="proposals.length" class="proposals small" aria-label="Proposed additions to the standards">
      <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
      <article v-for="p in proposals" :key="p.id" :data-testid="`proposal-${p.id}`">
        <p><strong>{{ p.status === 'pending' ? 'Waiting for you:' : p.status }}</strong> {{ p.summary }} <span class="muted">({{ p.section }}, proposed by {{ p.created_by }})</span></p>
        <details :open="p.status === 'pending'"><summary>The exact change</summary><pre class="patch">{{ p.patch }}</pre></details>
        <p v-if="p.result?.branch" class="muted">Committed on branch <code>{{ p.result.branch }}</code>. {{ p.result.note }}</p>
        <p v-else-if="p.result?.reason" class="notice-warn" role="status">{{ p.result.reason }}</p>
        <p v-if="p.status === 'pending'" class="actions">
          <button class="btn primary" type="button" :disabled="busy" @click="decide(p, 'approve')">Approve: create a branch</button>
          <button class="btn" type="button" :disabled="busy" @click="decide(p, 'reject')">Reject</button>
        </p>
      </article>
    </section>
    <details v-if="data.warnings?.length" class="small"><summary>{{ data.warnings.length }} {{ data.warnings.length === 1 ? 'note' : 'notes' }} about this file</summary><ul><li v-for="w in data.warnings" :key="w">{{ w }}</li></ul></details>
  </div>
</template>
<style scoped>
.standards { display: grid; gap: var(--gap-xs); }
.small { font-size: var(--font-size-sm); margin: 0; }
.proposals { display: grid; gap: var(--gap-sm); }
.patch { overflow-x: auto; font-size: var(--font-size-sm); background: var(--accent-soft); padding: var(--gap-sm); border-radius: var(--radius); white-space: pre; }
.actions { display: flex; flex-direction: row; gap: var(--gap-sm); margin: 0; }
ul { margin: var(--gap-xs) 0 0; padding-left: 1.2rem; }
</style>
