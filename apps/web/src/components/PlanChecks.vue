<script setup lang="ts">
import { ref, watch } from 'vue'
import { getJson } from '@/lib/api'
const props = defineProps<{ projectId: number; revision: number }>()
interface Finding { id: string; severity: string; message: string; stories: string[] }
const result = ref<{ project_type: string | null; findings: Finding[] } | null>(null)
async function load() {
  try { result.value = await getJson(`/api/projects/${props.projectId}/checks`) } catch { result.value = null }
}
watch(() => [props.projectId, props.revision], load, { immediate: true })
</script>
<template>
  <section v-if="result && result.project_type" class="card plan-checks" aria-labelledby="plan-checks-title">
    <h3 id="plan-checks-title">Plan checks for this project type</h3>
    <p v-if="!result.findings.length" class="small" role="status">The plan has what this project type expects: the gates, the verification, the preview and the human sign-offs.</p>
    <template v-else>
      <p class="muted small">These checks come from the selected project template. Required gates must be repaired before submission; warnings identify decisions to review.</p>
      <ul>
        <li v-for="f in result.findings" :key="f.id" :data-check="f.id"><strong v-if="f.severity === 'block'">Required: </strong>{{ f.message }}<span v-if="f.stories.length" class="muted small"> (stories: {{ f.stories.join(', ') }})</span></li>
      </ul>
    </template>
  </section>
</template>
<style scoped>
.plan-checks { display: flex; flex-direction: column; gap: var(--gap); }
ul { margin: 0; padding-left: 1.2rem; display: flex; flex-direction: column; gap: var(--gap-xs); }
h3, p { margin: 0; }
</style>
