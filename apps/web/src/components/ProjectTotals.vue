<script setup lang="ts">
import { computed } from 'vue'
import { formatCount, formatDuration, formatUsd } from '@/lib/format'
import type { ProjectTotals } from '@/lib/projects'

// Everything a project used across all of its tasks, planning included. Actual cost is what was charged; API-rate cost is the same work at
// published API rates, so membership use can be compared with paying per token.
const props = defineProps<{ totals: ProjectTotals; complete?: boolean }>()
const usd = (v: number) => formatUsd(v, v >= 10 ? 2 : 4)
const unpriced = computed(() => props.totals.api_unpriced + props.totals.media.unpriced)
const billed = { membership: 'Membership', free: 'Free model', api: 'API' } as const
const saved = computed(() => Math.max(0, props.totals.total_api_usd - props.totals.total_actual_usd))
</script>

<template>
  <section class="card totals" :aria-label="complete ? 'Project totals' : 'Project totals so far'" data-testid="project-totals">
    <h3>{{ complete ? 'Project totals' : 'Totals so far' }}</h3>
    <dl class="tiles">
      <div><dt>Agent time</dt><dd data-testid="totals-time">{{ formatDuration(totals.duration_s) }}</dd><small class="muted">{{ totals.runs }} runs<template v-if="totals.elapsed_s"> · {{ formatDuration(totals.elapsed_s) }} elapsed</template></small></div>
      <div><dt>Tokens in</dt><dd>{{ formatCount(totals.input_tokens) }}</dd><small v-if="totals.cached_input_tokens" class="muted">{{ formatCount(totals.cached_input_tokens) }} cached</small></div>
      <div><dt>Tokens out</dt><dd>{{ formatCount(totals.output_tokens) }}</dd></div>
      <div><dt>Actual cost</dt><dd data-testid="totals-actual">{{ usd(totals.total_actual_usd) }}</dd><small class="muted">what was charged</small></div>
      <div><dt>API-rate cost</dt><dd data-testid="totals-api">{{ usd(totals.total_api_usd) }}</dd><small class="muted"><template v-if="saved > 0">{{ usd(saved) }} covered by membership or free models</template><template v-else>same work at API rates</template></small></div>
    </dl>
    <p v-if="totals.media.images" class="small" data-testid="totals-media">Includes {{ totals.media.images }} generated {{ totals.media.images === 1 ? 'image' : 'images' }} at about {{ usd(totals.media.estimate_usd) }} (Media studio fal estimate).</p>
    <p class="small muted">Planning: {{ totals.planning.runs }} runs, {{ formatDuration(totals.planning.duration_s) }}, {{ usd(totals.planning.actual_usd) }} actual. Stories: {{ totals.stories.runs }} runs, {{ formatDuration(totals.stories.duration_s) }}, {{ usd(totals.stories.actual_usd) }} actual.</p>
    <div class="table-wrap">
      <table class="models" data-testid="totals-models">
        <caption class="sr-only">Models used across the project</caption>
        <thead><tr><th scope="col">Agent · model</th><th scope="col">Billed as</th><th scope="col">Runs</th><th scope="col">Time</th><th scope="col">Tokens in / out</th><th scope="col">Actual</th><th scope="col">API rate</th></tr></thead>
        <tbody>
          <tr v-for="m in totals.models" :key="m.agent + '/' + m.model">
            <th scope="row">{{ m.agent }} · {{ m.model || 'not reported' }}<small v-if="m.model_derived" class="muted"> (derived)</small></th>
            <td>{{ billed[m.billed] }}</td>
            <td>{{ m.runs }}<small v-if="m.succeeded !== m.runs" class="muted"> ({{ m.succeeded }} ok)</small></td>
            <td>{{ formatDuration(m.duration_s) }}</td>
            <td>{{ formatCount(m.input_tokens) }} / {{ formatCount(m.output_tokens) }}</td>
            <td>{{ m.actual_unpriced ? '—' : usd(m.actual_usd) }}</td>
            <td>{{ m.api_unpriced === m.runs ? 'no rate' : usd(m.api_usd) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="unpriced" class="small" data-testid="totals-unpriced">{{ unpriced }} {{ unpriced === 1 ? 'item has' : 'items have' }} no published rate and {{ unpriced === 1 ? 'is' : 'are' }} left out of the cost figures.</p>
    <p class="small muted">{{ totals.billing_note }}</p>
  </section>
</template>

<style scoped>
.totals { display: flex; flex-direction: column; gap: var(--gap-sm); margin-bottom: var(--gap); }
.totals h3 { margin: 0; font-size: var(--font-size); font-weight: var(--font-weight-strong); }
.totals p { margin: 0; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: var(--gap-sm); margin: 0; }
.tiles div { display: flex; flex-direction: column; gap: var(--gap-xs); min-width: 0; }
.tiles dt { font-size: var(--font-size-sm); color: var(--text-muted); }
.tiles dd { margin: 0; font-size: var(--font-size-lg); font-weight: var(--font-weight-strong); font-variant-numeric: tabular-nums; }
.table-wrap { overflow-x: auto; max-width: 100%; }
.models { width: 100%; border-collapse: collapse; font-size: var(--font-size-sm); font-variant-numeric: tabular-nums; }
.models th, .models td { padding: var(--gap-xs) var(--gap-sm); text-align: left; border-bottom: 1px solid var(--surface-border); white-space: nowrap; }
.models tbody th { font-weight: var(--font-weight); }
</style>
