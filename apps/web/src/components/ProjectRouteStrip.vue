<script setup lang="ts">
// The routes a project plans and runs on, in plain view at the top of the project: which policy is in force, the Coordinator, the planner and
// the story default. Change… edits the planner and this project's narrowing of the app policy; Save revision applies them.
import { computed, ref, toRef } from 'vue'
import { getJson } from '@/lib/api'
import { agentLabel } from '@/lib/cards'
import ModalShell from './ModalShell.vue'
import RoutePicker from './RoutePicker.vue'
import ToggleSwitch from './ToggleSwitch.vue'
import { COMMON_PROVIDERS, RUNTIMES, costLabel, emptyFilter, providerLabel, routeLabel, useRoutes,
  type CatalogRoute, type Choice, type Filter, type FeatureRoutes, type PolicyView, type Runtime } from '@/lib/routes'

const props = defineProps<{ projectId: number; plannerAgent: string; plannerModel: string; routePolicy?: Filter | null; locked?: boolean; dirty?: boolean }>()
const emit = defineEmits<{ planner: [value: { agent: string; model: string }]; policy: [value: Filter | null] }>()
const id = toRef(props, 'projectId')
const coordinator = useRoutes('coordinator', id), planner = useRoutes('planner', id), stories = useRoutes('stories', id)
const open = ref(false), app = ref<PolicyView | null>(null)
const choice = ref<Choice | null>(null), narrow = ref(false), draft = ref<Filter>(emptyFilter())

function find(r: FeatureRoutes | null, c: Choice | null): CatalogRoute | null { return r && c ? r.allowed.find(x => x.runtime === c.runtime && x.model === c.model) ?? null : null }
function describe(r: FeatureRoutes | null, c: Choice | null) {
  if (!r) return '…'
  if (!c) return r.empty_reason ? 'none allowed' : 'not set'
  const row = find(r, c)
  return routeLabel(c) + (row ? ` (${costLabel(row.cost_class)})` : ' (not allowed)')
}
const plannerChoice = computed<Choice | null>(() => props.plannerAgent !== 'auto' && props.plannerModel ? { runtime: props.plannerAgent as Runtime, model: props.plannerModel } : null)
const scope = computed(() => (coordinator.data.value?.scope.managed ? 'Managed · ' : '') + (props.routePolicy ? 'Narrowed for this project' : 'App policy'))
const problems = computed(() => [coordinator.data.value, planner.data.value, stories.data.value].filter(r => r?.empty_reason).map(r => r!.empty_reason!))
const providers = computed(() => [...new Set([...COMMON_PROVIDERS, ...(app.value?.providers ?? [])])])
function appAllows(kind: 'providers' | 'runtimes', item: string) {
  const lists = [app.value?.app?.[kind], app.value?.managed?.[kind]]
  return lists.every(l => l === null || l === undefined || (l as string[]).includes(item))
}
function appCost(name: 'free' | 'membership' | 'paid') { return !!app.value?.app.cost[name] && (!app.value?.managed || app.value.managed.cost[name]) }

async function change() {
  app.value = await getJson<PolicyView>('/api/routes/policy')
  choice.value = plannerChoice.value
  narrow.value = !!props.routePolicy
  draft.value = props.routePolicy ? JSON.parse(JSON.stringify(props.routePolicy)) : { ...emptyFilter(), cost: { ...app.value.app.cost } }
  open.value = true
}
function toggle(kind: 'providers' | 'runtimes', item: string, on: boolean) {
  const all = kind === 'providers' ? providers.value : RUNTIMES
  const base = (draft.value[kind] as string[] | null) ?? all.filter(x => appAllows(kind, x))
  const next = on ? [...new Set([...base, item])] : base.filter(x => x !== item)
  ;(draft.value as unknown as Record<string, string[] | null>)[kind] = next
}
function apply() {
  emit('planner', choice.value ? { agent: choice.value.runtime, model: choice.value.model } : { agent: 'auto', model: '' })
  emit('policy', narrow.value ? draft.value : null)
  open.value = false
}
defineExpose({ reload: () => { void coordinator.load(); void planner.load(); void stories.load() } })
</script>

<template>
  <section class="card route-strip" aria-label="Project routes" data-testid="route-strip">
    <span class="eyebrow">ROUTES · {{ scope.toUpperCase() }}</span>
    <ul>
      <li><span class="muted">Coordinator</span> {{ describe(coordinator.data.value, coordinator.data.value?.default ?? null) }}</li>
      <li><span class="muted">Planner</span> {{ plannerChoice ? describe(planner.data.value, plannerChoice) : 'Automatic (membership planners first)' }}</li>
      <li><span class="muted">Stories</span> {{ describe(stories.data.value, stories.data.value?.default ?? null) }}</li>
    </ul>
    <button type="button" class="btn" :disabled="locked" data-testid="change-routes" @click="change">Change…</button>
    <p v-if="dirty" class="muted small">Unsaved route changes: Save revision to apply them.</p>
    <p v-for="p in problems" :key="p" class="notice-warn small" role="alert">{{ p }} <RouterLink to="/profile#models-providers">Models &amp; providers</RouterLink></p>
  </section>
  <ModalShell v-if="open" class="project-dialog" labelledby="routes-title" @close="open = false">
    <form @submit.prevent="apply">
      <h2 id="routes-title">Project routes</h2>
      <RoutePicker v-model="choice" feature="planner" :project-id="projectId" label="Planner" automatic="A task-matched membership planner; an invalid plan may retry on another allowed route" />
      <fieldset>
        <legend>Policy for this project</legend>
        <label class="check"><input v-model="narrow" type="radio" :value="false" name="project-policy" /> Same as app <span class="muted small">(Settings → Models &amp; providers)</span></label>
        <label class="check"><input v-model="narrow" type="radio" :value="true" name="project-policy" data-testid="narrow" /> Narrow for this project</label>
        <p class="muted small">A project can only narrow the app policy, never widen it. Items the app policy removes are greyed; change them in <RouterLink to="/profile#models-providers">Models &amp; providers</RouterLink>.</p>
        <template v-if="narrow">
          <div class="checks" aria-label="Providers"><strong class="small">Providers</strong>
            <label v-for="p in providers" :key="p" class="check" :class="{ off: !appAllows('providers', p) }"><input type="checkbox" :disabled="!appAllows('providers', p)"
              :checked="appAllows('providers', p) && (!draft.providers || draft.providers.includes(p))" :data-testid="'project-provider-' + p" @change="e => toggle('providers', p, (e.target as HTMLInputElement).checked)" />{{ providerLabel(p) }}</label>
          </div>
          <div class="checks" aria-label="Runtimes"><strong class="small">Runtimes</strong>
            <label v-for="r in RUNTIMES" :key="r" class="check" :class="{ off: !appAllows('runtimes', r) }"><input type="checkbox" :disabled="!appAllows('runtimes', r)"
              :checked="appAllows('runtimes', r) && (!draft.runtimes || draft.runtimes.includes(r))" @change="e => toggle('runtimes', r, (e.target as HTMLInputElement).checked)" />{{ agentLabel(r) }}</label>
          </div>
          <ToggleSwitch v-model="draft.cost.membership" :disabled="!appCost('membership')" label="Membership routes" />
          <ToggleSwitch v-model="draft.cost.free" :disabled="!appCost('free')" label="Free models" />
          <ToggleSwitch v-model="draft.cost.paid" :disabled="!appCost('paid')" label="Paid API (last resort, approved per plan or task)" />
        </template>
      </fieldset>
      <div class="dialog-actions"><button type="button" class="btn" @click="open = false">Cancel</button><button class="btn primary" data-testid="apply-routes">Apply to this revision</button></div>
    </form>
  </ModalShell>
</template>

<style scoped>
.route-strip{display:grid;gap:var(--gap-sm);justify-items:start;text-align:left}.route-strip ul{display:flex;flex-wrap:wrap;gap:var(--gap-xs) var(--gap-lg, 1.5rem);margin:0;padding:0;list-style:none}
.route-strip li{overflow-wrap:anywhere}.route-strip p{margin:0}
fieldset{border:1px solid var(--surface-border);border-radius:var(--radius);padding:var(--gap-sm) var(--gap);margin:var(--gap) 0;display:grid;gap:var(--gap-sm)}
.check{display:flex;gap:var(--gap-xs);align-items:center}.check.off{opacity:.55}.checks{display:flex;flex-wrap:wrap;gap:var(--gap-xs) var(--gap);align-items:center}.small{font-size:var(--font-size-xs)}
.project-dialog :deep(.modal-panel){padding:var(--gap-lg)}.project-dialog h2{font-size:var(--font-size-xl)}.project-dialog form{display:grid;gap:var(--gap)}
.project-dialog .dialog-actions{display:flex;justify-content:flex-end;gap:var(--gap-sm);padding-top:var(--gap-lg);border-top:1px solid var(--glass-border)}
@media (max-width:640px){.project-dialog :deep(.modal-panel){padding:var(--gap)}}
</style>
