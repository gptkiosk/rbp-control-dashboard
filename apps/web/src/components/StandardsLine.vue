<script setup lang="ts">
import { ref, watch } from 'vue'
import { getJson } from '@/lib/api'
import type { Standards } from '@/lib/standards'

// One line on the project page saying which repository standards the plan is made under. A missing or unreadable file is a
// warning, never an error: planning continues without it. Failing to ask at all shows nothing rather than a false claim.
const props = defineProps<{ projectId: number; revision?: number }>()
const data = ref<Standards | null>(null)

async function load() {
  try { data.value = await getJson<Standards>(`/api/projects/${props.projectId}/standards`) } catch { data.value = null }
}
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
    <details v-if="data.warnings.length" class="small"><summary>{{ data.warnings.length }} {{ data.warnings.length === 1 ? 'note' : 'notes' }} about this file</summary><ul><li v-for="w in data.warnings" :key="w">{{ w }}</li></ul></details>
  </div>
</template>
<style scoped>
.standards { display: grid; gap: var(--gap-xs); }
.small { font-size: var(--font-size-sm); margin: 0; }
ul { margin: var(--gap-xs) 0 0; padding-left: 1.2rem; }
</style>
