<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getJson, postJson, type Card } from '@/lib/api'
import { agentLabel } from '@/lib/cards'
import type { Project, ProjectTask } from '@/lib/projects'

const props = defineProps<{ card: Card }>()
const emit = defineEmits<{ changed: [] }>()
const project = ref<Project | null>(null)
const busy = ref(false), error = ref(''), notice = ref('')
const visible = computed(() => !!props.card.project && props.card.project.role !== 'story' && ['failed', 'review'].includes(props.card.column))
const task = computed(() => project.value?.tasks.find(t => t.card_id === props.card.id && t.role !== 'story'))
const routes = computed(() => task.value?.planning_retry_routes ?? [])
const ready = computed(() => visible.value && project.value?.state === 'planning_failed'
  && task.value?.column === 'failed' && task.value.run_id === props.card.last_run?.id && routes.value.length > 0)

let generation = 0
watch(() => [props.card.id, props.card.project?.id, props.card.project?.role, props.card.column, props.card.last_run?.id], async () => {
  const mine = ++generation
  project.value = null; error.value = ''; notice.value = ''
  if (!visible.value) return
  try {
    const data = await getJson<Project>(`/api/projects/${props.card.project!.id}`)
    if (mine === generation) project.value = data
  } catch (e) { if (mine === generation) error.value = e instanceof Error ? e.message : String(e) }
}, { immediate: true })

async function retry(route: {agent: string; model: string}) {
  if (busy.value || !ready.value || !project.value || !props.card.project) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const base = `/api/projects/${props.card.project.id}`
    const fresh = await getJson<Project>(base)
    const current: ProjectTask | undefined = fresh.tasks.find(t => t.card_id === props.card.id && t.role !== 'story')
    if (!current || fresh.state !== 'planning_failed' || !['failed', 'review'].includes(current.column) || current.run_id !== props.card.last_run?.id)
      throw new Error('The planning task changed. Refresh before retrying it.')
    if (!current.planning_retry_routes?.some(r => r.agent === route.agent && r.model === route.model))
      throw new Error('This route is no longer approved. Review the current project settings.')
    await postJson(`${base}/planning-tasks/${props.card.id}/retry`, { revision: fresh.revision, route })
    notice.value = 'Retry queued for this planning task. Completed planning steps and the project brief are unchanged.'
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>

<template>
  <section v-if="visible" class="planning-retry" aria-label="Retry failed planning task">
    <strong>Retry this planning task</strong>
    <p class="muted small">Keeps completed planning steps and the project brief. Previous runs stay in history.</p>
    <div v-if="routes.length" class="actions">
      <button v-for="route in routes" :key="`${route.agent}:${route.model}`" type="button" class="btn" :class="{ primary: route.agent === card.agent && route.model === card.model }" :disabled="busy || !ready" @click="retry(route)">
        {{ busy ? 'Queueing…' : route.agent === card.agent && route.model === card.model ? 'Retry task' : `Retry with ${agentLabel(route.agent)} · ${route.model}` }}
      </button>
    </div>
    <p v-else-if="project" class="muted small">No currently approved route is available for this step. Update the planner’s model/provider configuration, then retry from Projects.</p>
    <p v-if="error" class="error-text" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.planning-retry{display:grid;gap:var(--gap-sm);padding:var(--gap);border:1px solid var(--panel-border);border-radius:var(--radius);background:var(--panel-raised)}
.planning-retry p{margin:0;overflow-wrap:anywhere}
.planning-retry .actions{display:flex;flex-wrap:wrap;gap:var(--gap-sm)}
</style>
