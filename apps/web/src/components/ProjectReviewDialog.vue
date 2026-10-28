<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getJson } from '@/lib/api'
import type { RecoveryInfo } from '@/lib/routeRecovery'
import AppIcon from '@/components/AppIcon.vue'
import ModalShell from '@/components/ModalShell.vue'
import RouteAdvice from '@/components/RouteAdvice.vue'
import NoteFold from '@/components/NoteFold.vue'
import { agentLabel } from '@/lib/cards'
import { planningBiasLabel, type ProjectNode } from '@/lib/projects'
import { costLabel, routeLabel, type FeatureRoutes } from '@/lib/routes'

// The confirmation step before planning or submitting a project: what will happen, what the standards check says, and the approvals it needs.
interface Check { source?: string | null; property?: string | null; problems: string[]; areas: string[]; fixable?: number }
const props = defineProps<{
  mode: 'plan' | 'submit'
  projectId: number; revision: number; title: string; workingDir: string; planningBias: number
  plannerAgent: string; plannerModel: string; dispatchMode: 'sequential' | 'parallel'
  delegator: string; stories: ProjectNode[]; titles: Record<string, string>
  needsPaidWork: boolean; standardsCheck?: Check | null; error: string; busy: boolean
  fixed?: string[]
  repository?: { name: string; repo: string; folder: string; branch: string } | null
}>()
const coordination = defineModel<boolean>('coordination', { required: true })
const paidPlanner = defineModel<boolean>('paidPlanner', { required: true })
const paidWork = defineModel<boolean>('paidWork', { required: true })
const fresh = defineModel<boolean>('fresh', { required: true })
const emit = defineEmits<{ close: []; confirm: []; fix: [] }>()

const recovery = ref<RecoveryInfo|null>(null)
// Planning: the routes the saved project and policies give the Coordinator and the planner, so a refused route shows here, not after Start.
const coordinatorRoutes = ref<FeatureRoutes | null>(null), plannerRoutes = ref<FeatureRoutes | null>(null)
onMounted(async () => {
  if (props.mode !== 'plan') return
  try { recovery.value = await getJson('/api/profile/route-reliability') } catch { recovery.value = null }
  try {
    ;[coordinatorRoutes.value, plannerRoutes.value] = await Promise.all(['coordinator', 'planner'].map(f => getJson<FeatureRoutes>(`/api/routes?feature=${f}&project_id=${props.projectId}`)))
  } catch { coordinatorRoutes.value = plannerRoutes.value = null }
})
const coordinatorText = computed(() => {
  const r = coordinatorRoutes.value
  if (!r) return '…'
  const row = r.default ? r.allowed.find(x => x.runtime === r.default!.runtime && x.model === r.default!.model) : null
  return r.default ? `${routeLabel(r.default)}${row ? ` · ${costLabel(row.cost_class)}` : ''}` : 'none allowed'
})
const plannerProblem = computed(() => {
  const r = plannerRoutes.value
  if (!r || props.plannerAgent === 'auto') return ''
  if (r.allowed.some(x => x.runtime === props.plannerAgent && x.model === props.plannerModel)) return ''
  const hidden = r.hidden.find(x => x.runtime === props.plannerAgent && x.model === props.plannerModel)
  return `This planner is not allowed: ${hidden?.hidden_because ?? 'it is not available on this host'}. Choose another with Change… on the project's Routes strip and save the revision.`
})
const routeBlocked = computed(() => props.mode === 'plan' && (!!coordinatorRoutes.value?.empty_reason || !!plannerProblem.value))
const heading = computed(() => (props.mode === 'plan' ? 'Review planning request' : 'Review project submission'))
const delegatorName = computed(() => props.delegator || 'Hermes (Coordinator)')
const planner = computed(() => (props.plannerAgent === 'auto' ? (plannerRoutes.value?.default && ['app', 'managed', 'project'].includes(plannerRoutes.value.default_source ?? '') ? `${routeLabel(plannerRoutes.value.default)} (app default)` : 'Installed subscription planner, or a reviewed free Hermes route') : `${agentLabel(props.plannerAgent)} · ${props.plannerModel || 'Agent default'}`))
const problems = computed(() => (props.mode === 'submit' ? props.standardsCheck?.problems ?? [] : []))
const blocked = computed(() => problems.value.length > 0)
const unknownArea = computed(() => problems.value.some(p => p.includes("this repository's areas")))
</script>

<template>
  <ModalShell labelledby="project-review-title" @close="emit('close')">
    <div class="review">
      <header class="head">
        <div class="intro">
          <span class="mark"><AppIcon :name="mode === 'plan' ? 'refresh' : 'send'" size="lg" /></span>
          <div>
            <h2 id="project-review-title" class="section-title">{{ heading }}</h2>
            <p class="hint">{{ title }} · revision {{ revision }} · <RouterLink to="/help?topic=projects">How-to</RouterLink></p>
          </div>
        </div>
        <button type="button" class="btn close" aria-label="Close" @click="emit('close')"><AppIcon name="close" /></button>
      </header>

      <dl class="facts">
        <div><dt>Working directory</dt><dd class="mono">{{ workingDir }}</dd></div>
        <div><dt>Story preference</dt><dd>{{ planningBiasLabel(planningBias) }}</dd></div>
        <div v-if="mode === 'plan'" data-testid="review-coordinator"><dt>Coordinator</dt><dd>{{ coordinatorText }}
          <span v-if="coordinatorRoutes?.empty_reason" class="notice-warn small route-problem" role="alert">{{ coordinatorRoutes.empty_reason }} <RouterLink to="/profile#models-providers">AI &amp; models</RouterLink></span>
          <span v-else-if="coordinatorRoutes?.default_note" class="muted small route-problem">{{ coordinatorRoutes.default_note }}. <RouterLink to="/profile#models-providers">AI &amp; models</RouterLink></span></dd></div>
        <div v-if="mode === 'plan'" data-testid="review-planner"><dt>Planner</dt><dd>{{ planner }}
          <span v-if="plannerProblem" class="notice-warn small route-problem" role="alert">{{ plannerProblem }}</span></dd></div>
        <div v-else><dt>Build</dt><dd>{{ dispatchMode === 'parallel' ? 'In parallel, in separate branches' : 'One story at a time, in dependency order' }}</dd></div>
        <div v-if="repository && !repository.repo" data-testid="repo-step"><dt>Step 1</dt><dd>The dashboard creates the private repository <strong>{{ repository.name }}</strong> with this host's gh sign-in, clones it into the working directory and gives agents its setup branch{{ mode === 'submit' ? ', before any story runs' : ' when you submit' }}.</dd></div>
        <div v-else-if="repository?.repo"><dt>Repository</dt><dd class="mono">{{ repository.repo }} · {{ repository.folder }}/ · {{ repository.branch }}</dd></div>
      </dl>

      <template v-if="mode === 'plan'">
        <p v-if="recovery?.policy.enabled && recovery.policy.routes.length" class="small muted">Recovery routes: {{ recovery.policy.routes.map(r => agentLabel(r.agent) + ' · ' + r.model).join(' → ') }}. Paid alternatives require the separate API approval below. <RouterLink to="/profile#route-recovery">Edit recovery settings</RouterLink></p>
        <p class="lead">{{ delegatorName }} reviews the plan and returns an editable map. This request starts no stories.</p>
        <label class="check option"><input v-model="fresh" type="checkbox" data-testid="plan-fresh" /><span><strong>Plan from scratch.</strong> Do not show the planner the stories on the map now. Use this when the brief or working directory changed, so it does not just repeat the old plan.</span></label>
      </template>
      <template v-else>
        <p class="lead">{{ delegatorName }} will submit this exact revision. Handoffs need your acceptance; routes and scope are fixed, and the source branch is never merged automatically.</p>

        <section v-if="standardsCheck" class="result" :class="blocked ? 'bad' : 'good'" role="status" data-testid="standards-result">
          <h3 class="result-title">{{ blocked ? `Standards check: ${problems.length} ${problems.length === 1 ? 'thing needs' : 'things need'} fixing` : 'Standards check: passes' }}</h3>
          <ul v-if="blocked"><li v-for="p in problems" :key="p">{{ p }}</li></ul>
          <p v-if="unknownArea && standardsCheck.areas.length" class="small">Areas these standards list: {{ standardsCheck.areas.join(', ') }}.</p>
          <template v-if="blocked">
            <p v-if="standardsCheck.fixable" class="small">Fix automatically raises each risk to its area’s minimum and moves high-risk stories off free routes: onto a fallback this plan already approved, or else onto the cheapest subscription route on this host. It saves a new revision for you to review.</p>
            <div v-if="standardsCheck.fixable" class="fix-row"><button type="button" class="btn primary" data-action="standards-fix" :disabled="busy" @click="emit('fix')">Fix automatically ({{ standardsCheck.fixable }})</button></div>
            <p class="small">{{ standardsCheck.fixable ? 'Anything left after that needs an edit on the map: choose a subscription route or make it a human review.' : 'Go back to the map and fix these, or plan again from scratch. This cannot be submitted until they are fixed.' }}</p>
          </template>
        </section>
        <section v-if="fixed?.length" class="result good" role="status" data-testid="standards-fixed">
          <h3 class="result-title">Fixed automatically</h3>
          <ul><li v-for="f in fixed" :key="f">{{ f }}</li></ul>
        </section>

        <details class="fold">
          <summary>Stories in this revision ({{ stories.length }})</summary>
          <div class="stories">
            <article v-for="s in stories" :key="s.key">
              <h4>{{ s.title }}</h4>
              <p class="small muted">{{ agentLabel(s.assignee) }} · {{ s.model || 'Agent default' }} · {{ s.mode }}</p>
              <p class="small">Scope: {{ s.scope || 'Missing: add before submission' }}</p>
              <p class="small">Done when: {{ s.acceptance || 'Missing: add before submission' }}</p>
              <p v-if="s.depends_on.length" class="small muted">Depends on: {{ s.depends_on.map(k => titles[k] ?? k).join(', ') }}</p>
              <p v-if="s.routes.length" class="small muted">Approved handoffs: {{ s.routes.map(r => agentLabel(r.agent) + ' · ' + r.model).join(' → ') }}</p>
            </article>
          </div>
        </details>
        <RouteAdvice :project-id="projectId" :revision="revision" />
      </template>

      <NoteFold label="Spending and billing"><p class="small">The Coordinator uses its reviewed route; the Planner above is a separate choice. Failed planning steps try the next approved model/provider route. Retries stay within AI &amp; models, with paid API last; they never approve paid work. If all routes fail, the project stays available to revise and retry. Membership access and provider API billing are separate. Free models can hit limits, and a Google BYOK fallback can incur Google charges. Hermes and OpenClaw routing shares a $20 per month OpenRouter key cap that includes tracked BYOK usage; this does not cover your whole Google invoice or calls outside this key.</p><RouterLink to="/help?topic=project-models">Model routes and billing</RouterLink></NoteFold>

      <div class="approvals">
        <label class="check"><input v-model="coordination" type="checkbox" /><span>I approve this Coordinator coordination request and its configured routing.</span></label>
        <label v-if="mode === 'plan'" class="check"><input v-model="paidPlanner" type="checkbox" /><span>I separately approve provider API planning charges for the Coordinator model, the selected planner and enabled recovery routes.</span></label>
        <label v-if="mode === 'submit' && needsPaidWork" class="check"><input v-model="paidWork" type="checkbox" /><span>I approve the API / BYOK routes assigned to these stories.</span></label>
      </div>

      <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>

      <div class="actions">
        <button type="button" class="btn" @click="emit('close')">Back to map</button>
        <button type="button" class="btn primary" :disabled="busy || !coordination || blocked || routeBlocked" @click="emit('confirm')">{{ mode === 'plan' ? (busy ? 'Starting planning…' : 'Start planning') : (busy ? 'Submitting…' : 'Submit approved revision') }}</button>
      </div>
    </div>
  </ModalShell>
</template>

<style scoped>
.review { display: flex; flex-direction: column; gap: var(--gap-lg); padding: var(--gap-lg); }
.head { display: flex; align-items: center; justify-content: space-between; gap: var(--gap); }
.intro { display: flex; gap: var(--gap); align-items: center; min-width: 0; }
.intro .hint { margin: var(--gap-xs) 0 0; color: var(--text-muted); font-size: var(--font-size-sm); overflow-wrap: anywhere; }
.mark { display: flex; align-items: center; justify-content: center; flex-shrink: 0; width: var(--dialog-icon-size); height: var(--dialog-icon-size); color: var(--accent); background: var(--accent-soft); border: 1px solid var(--select-border); border-radius: var(--radius); }
.close { width: var(--dialog-icon-size); min-width: var(--dialog-icon-size); padding: 0; }
p { margin: 0; line-height: var(--line-height); }
.lead { max-width: 70ch; }
.facts { display: grid; gap: 0; margin: 0; border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--glass-bg); }
.facts > div { display: grid; grid-template-columns: 10rem minmax(0, 1fr); gap: var(--gap); padding: var(--gap-sm) var(--gap); }
.facts > div + div { border-top: 1px solid var(--glass-border); }
.facts dt { color: var(--text-muted); font-size: var(--font-size-sm); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.mono { font-family: var(--font-mono); font-size: var(--font-size-sm); }
.check { display: flex; align-items: flex-start; gap: var(--gap-sm); line-height: var(--line-height); }
.check input { flex: none; margin-top: 0.3rem; accent-color: var(--accent); }
.option { padding: var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--glass-bg); }
.result { display: flex; flex-direction: column; gap: var(--gap-sm); padding: var(--gap); border: 1px solid var(--surface-border); border-left-width: 3px; border-radius: var(--radius); background: var(--accent-soft); }
.result.bad { border-left-color: var(--danger, #ef4f4f); }
.result.good { border-left-color: var(--accent); }
.result-title { margin: 0; font-size: var(--font-size); font-weight: var(--font-weight-strong); }
.result ul { margin: 0; padding-left: 1.25rem; list-style: disc; display: grid; gap: var(--gap-xs); line-height: var(--line-height); overflow-wrap: anywhere; }
.fold { border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--glass-bg); }
.fold > summary { cursor: pointer; padding: var(--gap) var(--gap); font-weight: var(--font-weight-strong); }
.fold[open] > summary { border-bottom: 1px solid var(--glass-border); }
.fold > :not(summary) { margin: var(--gap); }
.stories { display: grid; gap: var(--gap); max-height: 20rem; overflow: auto; }
.stories article { display: grid; gap: var(--gap-xs); padding-bottom: var(--gap); border-bottom: 1px solid var(--glass-border); }
.stories article:last-child { border-bottom: 0; padding-bottom: 0; }
.stories h4 { margin: 0; font-size: var(--font-size); }
.small { font-size: var(--font-size-sm); }
.approvals { display: grid; gap: var(--gap); padding: var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); }
.actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: var(--gap-sm); padding-top: var(--gap-lg); border-top: 1px solid var(--glass-border); }
.actions .btn { min-height: var(--select-height); }
@media (max-width: 600px) {
  .review { padding: var(--gap); gap: var(--gap); }
  .facts > div { grid-template-columns: 1fr; gap: var(--gap-xs); }
  .actions .btn { flex: 1 1 100%; }
}
.fix-row { display:flex; gap:var(--gap-sm); margin:var(--gap-xs) 0; }
.route-problem{display:block;margin-top:var(--gap-xs)}
</style>
