<script setup lang="ts">
import NoteFold from '@/components/NoteFold.vue'
import { onMounted, ref } from 'vue'
import BarList from '@/components/BarList.vue'
import { getJson } from '@/lib/api'
import type { Group, Scorecard } from '@/lib/coordinator'
import { percent } from '@/lib/telemetry'

// How well the coordinator plans, from fixed checks on each approved plan plus what happened next. The checks look at the plan, not the model.
const data = ref<Scorecard | null>(null)
async function load() {
  try { data.value = await getJson<Scorecard>('/api/coordinator/scorecard') } catch { data.value = null }
}
const bars = (groups: Group[]) => groups.map(g => ({
  label: g.label, value: Math.round(g.score * 100),
  note: `% of checks · ${g.plans} ${g.plans === 1 ? 'plan' : 'plans'}${g.edits_per_plan != null ? ` · ${g.edits_per_plan} edits each` : ''}${g.first_pass_rate != null ? ` · first pass ${percent(g.first_pass_rate)}` : ''}`,
}))
const when = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleDateString() : '–')
onMounted(load)
</script>
<template>
  <section v-if="data" class="scorecard" aria-label="Coordinator scorecard">
    <h2 class="section-title">Coordinator scorecard</h2>
    <NoteFold label="What is scored"><p class="muted small">{{ data.note }} Fixed checks cover the plan schema, the job envelope, estimates against size, checkable acceptance criteria, bounded scope, dependencies, route reasons, the standards and a review for high-risk work. {{ data.briefs }} fixed briefs are available to score any plan against.</p></NoteFold>
    <p v-if="!data.plans.length" class="muted small">No approved plans in this period yet. Each plan you approve is scored and appears here.</p>
    <div v-else class="grid">
      <BarList title="Plan score by planner" :items="bars(data.by_planner)" />
      <BarList title="Plan score by coordinator wording" :items="bars(data.by_wording)" />
    </div>
    <details v-if="data.plans.length" class="card detail" aria-label="Scored plans table">
      <summary>Scored plans: the numbers</summary>
      <div class="table-scroll"><table class="data-table">
        <caption class="sr-only">Scored plans</caption>
        <thead><tr><th>Plan</th><th>Approved</th><th>Planner</th><th>Wording</th><th class="num">Score</th><th class="num">Edits by a person</th><th class="num">Done</th><th class="num">First pass</th><th class="num">Actual over estimate</th><th>Failed checks</th></tr></thead>
        <tbody><tr v-for="p in data.plans" :key="`${p.project_id}-${p.revision}`">
          <td>{{ p.title }} <span class="muted">(p{{ p.project_id }}r{{ p.revision }})</span></td><td>{{ when(p.approved_at) }}</td><td>{{ p.planner ?? '–' }}</td><td>{{ p.wording?.label ?? '–' }}</td>
          <td class="num">{{ percent(p.score) }}</td><td class="num">{{ p.edits ? p.edits.total : '–' }}</td><td class="num">{{ p.done }} of {{ p.stories }}</td>
          <td class="num">{{ p.done ? percent(p.first_pass / p.done) : '–' }}</td><td class="num">{{ p.estimate_ratio == null ? '–' : `×${p.estimate_ratio}` }}</td><td>{{ p.failed.join(', ') || '–' }}</td>
        </tr></tbody>
      </table></div>
    </details>
  </section>
</template>
<style scoped>
.scorecard { display: grid; gap: var(--gap); }
h2 { margin: 0; }
.small { font-size: var(--font-size-sm); margin: 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: var(--gap); }
.detail summary { cursor: pointer; font-weight: 600; }
</style>
