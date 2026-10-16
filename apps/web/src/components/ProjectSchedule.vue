<script setup lang="ts">
import { computed } from 'vue'

// How a parallel project would run: the longest chain, the best-case speed-up and anything to fix before it can be submitted.
interface Schedule { stories: number; total_minutes: number; critical_minutes: number; speedup: number; width: number; critical_path: string[]; problems: string[]; max_concurrent_runs: number }
interface Timing { runs: number; busy_minutes: number; elapsed_minutes: number; overlap: number }
const props = defineProps<{ schedule: Schedule | null; titles?: Record<string, string>; timing?: Timing | null }>()
const hours = (m: number) => (m >= 120 ? `${(m / 60).toFixed(1)} h` : `${m} min`)
const path = computed(() => (props.schedule?.critical_path ?? []).map(k => props.titles?.[k] ?? k).join(' → '))
const limited = computed(() => !!props.schedule && props.schedule.width > props.schedule.max_concurrent_runs)
</script>

<template>
  <section v-if="schedule" class="card schedule" aria-label="Parallel build schedule" data-testid="schedule">
    <h3>Parallel build</h3>
    <p class="small" data-testid="schedule-summary">The longest chain is <strong>{{ hours(schedule.critical_minutes) }}</strong> of <strong>{{ hours(schedule.total_minutes) }}</strong> in total, so the best case is about <strong>{{ schedule.speedup }}×</strong> faster than one story at a time, with up to <strong>{{ schedule.width }}</strong> stories at once.</p>
    <p v-if="path" class="muted small" data-testid="schedule-path">Longest chain: {{ path }}</p>
    <p v-if="limited" class="small" data-testid="schedule-limit">This install runs at most {{ schedule.max_concurrent_runs }} at a time (<code>MAC_CONTROL_MAX_CONCURRENT_RUNS</code>), so the full width will not be used until that is raised.</p>
    <p v-if="timing" class="small" data-testid="schedule-timing">So far: {{ timing.busy_minutes }} min of agent work in {{ timing.elapsed_minutes }} min elapsed, about {{ timing.overlap }}× overlap across {{ timing.runs }} runs.</p>
    <ul v-if="schedule.problems.length" class="problems" data-testid="schedule-problems" role="alert">
      <li v-for="p in schedule.problems" :key="p">{{ p }}</li>
    </ul>
    <p v-if="schedule.problems.length" class="small">Submission is refused until these are fixed. Turn parallel build off to build one story at a time in dependency order.</p>
  </section>
</template>

<style scoped>
.schedule { display: flex; flex-direction: column; gap: var(--gap-sm); }
.problems { margin: 0; padding-left: 1.2rem; }
</style>
