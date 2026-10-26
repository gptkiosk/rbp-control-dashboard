<script setup lang="ts">
import { ref, watch } from 'vue'
import { getJson, postJson } from '@/lib/api'
const props = defineProps<{ projectId: number; revision: number; disabled?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
interface Finding { id: string; severity: string; message: string; stories: string[] }
interface Readiness { ready: boolean; checks: { id: string; status: 'ready' | 'pending' | 'missing'; detail: string; link: string }[] }
const result = ref<{ project_type: string | null; findings: Finding[] } | null>(null)
const readiness = ref<Readiness | null>(null), error = ref(''), busy = ref(false)
let requestId = 0
async function load() {
  const id = ++requestId
  const results = await Promise.allSettled([getJson<{project_type:string|null;findings:Finding[]}>(`/api/projects/${props.projectId}/checks`),getJson<Readiness>(`/api/projects/${props.projectId}/readiness`)])
  if (id !== requestId) return
  result.value = results[0].status === 'fulfilled' ? results[0].value : null
  readiness.value = results[1].status === 'fulfilled' ? results[1].value : null
}
async function repair() {
  busy.value=true; error.value=''
  try { await postJson(`/api/projects/${props.projectId}/repair-plan`,{revision:props.revision}); emit('changed') }
  catch(e) { error.value=e instanceof Error ? e.message : String(e) }
  finally { busy.value=false }
}
watch(() => [props.projectId, props.revision], load, { immediate: true })
</script>
<template>
  <section v-if="result && (result.project_type || result.findings.length)" class="card plan-checks" aria-labelledby="plan-checks-title">
    <h3 id="plan-checks-title">Plan & setup checks</h3>
    <p v-if="!result.findings.length" class="small" role="status">No selected-template or recognized saved-scope conflicts found. Review the actual plan and setup evidence before submitting.</p>
    <template v-else>
      <p class="muted small">Saved requirements take precedence over template examples. Required findings must be repaired before submission.</p>
      <ul><li v-for="f in result.findings" :key="f.id" :data-check="f.id"><strong v-if="f.severity === 'block'">Required: </strong>{{ f.message }}<span v-if="f.stories.length" class="muted small"> ({{ f.stories.join(', ') }})</span></li></ul>
      <button v-if="result.findings.some(f=>f.id === 'saved-model-preference')" class="btn" :disabled="busy || disabled || readiness?.checks.some(c=>c.id === 'story-route' && c.status === 'missing')" @click="repair">{{ busy ? 'Preparing revision…' : 'Restore saved model preference' }}</button>
    </template>
    <details v-if="readiness" :open="!readiness.ready"><summary>Coordinator setup · {{ readiness.ready ? 'ready or planned' : 'needs attention' }}</summary>
      <ul><li v-for="c in readiness.checks" :key="c.id"><strong>{{ c.status === 'ready' ? 'Ready' : c.status === 'pending' ? 'Planned' : 'Required' }}:</strong> {{ c.detail }} <RouterLink v-if="c.status === 'missing'" :to="c.link">Open setup</RouterLink></li></ul>
      <p class="muted small">Planned setup still needs execution evidence. Missing access, credentials or tools use the app's existing controls.</p>
    </details>
    <p v-else class="muted small">Setup readiness could not be read. Refresh before submission; missing evidence is not a ready check.</p>
    <button class="btn" type="button" @click="load">Recheck setup</button>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.plan-checks { display: flex; flex-direction: column; align-items: flex-start; gap: var(--gap); overflow-wrap: anywhere; }
ul { margin: var(--gap-sm) 0; padding-left: 1.2rem; display: flex; flex-direction: column; gap: var(--gap-xs); }
h3, p { margin: 0; }
summary { cursor: pointer; }
</style>
