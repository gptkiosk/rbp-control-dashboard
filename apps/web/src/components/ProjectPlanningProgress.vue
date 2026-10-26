<script setup lang="ts">
import { computed } from 'vue'
import type { Project } from '@/lib/projects'
import { agentLabel } from '@/lib/cards'

const props = defineProps<{ project: Project; coordinator: string }>()
const stages = [
  { key: 'coordinate', title: 'Review the brief', detail: 'Coordinator selects the planning route.' },
  { key: 'plan', title: 'Build the map', detail: 'Planner defines stories, tools and prerequisites.' },
  { key: 'return', title: 'Check the plan', detail: 'Coordinator reviews the map before returning it.' },
]
const dispatching = computed(() => props.project.state === 'dispatching')
const ready = computed(() => props.project.state === 'review')
const failed = computed(() => props.project.state === 'planning_failed')
const current = computed(() => stages.findIndex(stage => stage.key === props.project.pipeline?.step))
const task = computed(() => props.project.tasks.find(task => task.card_id === props.project.pipeline?.card_id))
// Queued retries can still have a prior failed run attached. The current card state wins.
const activity = computed(() => {
  if (failed.value) return 'Needs attention'
  if (ready.value) return 'Ready for your review'
  if (task.value?.column === 'queued') return 'Queued'
  if (task.value?.run_stage === 'awaiting_approval') return 'Waiting for approval'
  if (task.value?.column === 'failed' || task.value?.run_stage === 'failed') return 'Waiting for recovery'
  if (task.value?.column === 'running' || task.value?.run_stage === 'running') return 'Running'
  return 'Waiting for the next coordinator update'
})
const working = computed(() => !ready.value && !failed.value && !['Waiting for approval', 'Waiting for recovery'].includes(activity.value))
const title = computed(() => failed.value ? 'Planning needs attention' : ready.value
  ? (props.project.can_cancel_replan ? 'Replacement plan ready to review' : 'Your plan is ready to review')
  : dispatching.value ? 'Preparing story tasks' : 'Planning your project')
const stepTitle = computed(() => dispatching.value ? 'Create tasks from the approved map' : stages[current.value]?.title || 'Waiting for coordinator status')
const route = computed(() => task.value?.agent ? `${agentLabel(task.value.agent)}${task.value.model ? ' · ' + task.value.model : ''}` : '')
</script>

<template>
  <section class="card planning-progress" :class="{ ready, failed }" aria-labelledby="planning-progress-title">
    <div class="progress-heading" role="status" aria-live="polite" aria-atomic="true">
      <span v-if="working" class="spinner" aria-hidden="true" />
      <span v-else class="state-mark" aria-hidden="true">{{ ready ? '✓' : '!' }}</span>
      <div><h2 id="planning-progress-title">{{ title }}</h2><p v-if="!ready && !failed" class="current-step"><strong>{{ stepTitle }}</strong> · {{ activity }}</p><p v-else>{{ activity }}</p></div>
    </div>
    <progress v-if="working" :aria-label="dispatching ? 'Preparing project tasks' : 'Project planning in progress'" />
    <ol class="stages" aria-label="Planning steps">
      <li v-for="(stage, i) in stages" :key="stage.key" :class="{ current: !ready && !dispatching && current === i, finished: ready || dispatching || current > i }" :aria-current="!ready && !dispatching && current === i ? 'step' : undefined">
        <span class="step-number" aria-hidden="true">{{ ready || dispatching || current > i ? '✓' : i + 1 }}</span>
        <div><strong>{{ stage.title }}</strong><small>{{ stage.detail }}</small><small class="step-state">{{ ready || dispatching || current > i ? 'Complete' : current === i ? activity : 'Pending' }}</small></div>
      </li>
    </ol>
    <div class="activity-detail">
      <span v-if="!ready && !dispatching" class="muted">Submitted to {{ agentLabel(coordinator) }}<template v-if="route"> · {{ route }}</template></span>
      <RouterLink v-if="project.pipeline?.card_id" :to="`/tasks?card=${project.pipeline.card_id}`">Open current {{ dispatching ? 'dispatch' : 'planning' }} task #{{ project.pipeline.card_id }}</RouterLink>
      <span v-if="!ready && !failed" class="muted">Updates every 3 seconds</span>
    </div>
    <slot />
  </section>
</template>

<style scoped>
.planning-progress { margin-top: var(--gap); border: 1px solid var(--accent); background: var(--agent-glass); min-width: 0; overflow-wrap: anywhere; }
.progress-heading { display: flex; align-items: center; gap: var(--gap); }
h2 { font-size: var(--font-size-lg); margin: 0; }
p { margin: var(--gap-xs) 0 0; }
.spinner, .state-mark { flex: 0 0 1.6rem; width: 1.6rem; height: 1.6rem; color: var(--accent); }
.spinner { border: 3px solid var(--accent-soft); border-top-color: var(--accent); border-right-color: var(--accent); border-radius: 50%; animation: planning-spin 1s linear infinite; }
.state-mark { display: grid; place-items: center; font-weight: var(--font-weight-strong); }
progress { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.current-step { color: var(--accent); }
.stages { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--gap-sm); list-style: none; padding: 0; margin: var(--gap) 0; }
.stages li { display: flex; align-items: flex-start; gap: var(--gap-sm); padding: var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); color: var(--text-muted); min-width: 0; }
.stages .current { border-color: var(--accent); background: var(--accent-soft); color: var(--text); }
.step-number { display: grid; place-items: center; flex: 0 0 1.5rem; height: 1.5rem; border: 1px solid currentColor; border-radius: 50%; font-size: var(--font-size-xs); }
.stages strong, .stages small { display: block; }
.stages small { font-size: var(--font-size-xs); margin-top: var(--gap-xs); }
.step-state { font-weight: var(--font-weight-strong); }
.finished .step-number, .finished .step-state { color: var(--ok); }
.activity-detail { display: flex; flex-wrap: wrap; gap: var(--gap-sm) var(--gap); font-size: var(--font-size-xs); }
.ready { border-color: var(--ok); }
.ready .state-mark { color: var(--ok); }
.failed { border-color: var(--danger); }
.failed .state-mark { color: var(--danger); }
@keyframes planning-spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) { .stages { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
</style>
