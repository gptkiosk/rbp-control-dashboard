<script setup lang="ts">
// The routes a project plans and runs on, in plain view at the top of the project: which policy is in force, the Coordinator, the planner and
// the story default. Both the strip and Change… show what the current (possibly unsaved) choices allow, so a narrowing never looks applied before
// it is, and a choice that leaves the Coordinator nothing is flagged before planning. Save revision applies them.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getJson } from '@/lib/api'
import { agentLabel } from '@/lib/cards'
import ModalShell from './ModalShell.vue'
import RoutePicker from './RoutePicker.vue'
import ToggleSwitch from './ToggleSwitch.vue'
import { COMMON_PROVIDERS, RUNTIMES, costLabel, emptyPolicy, previewRoutes, providerLabel, routeLabel, withCoordinatorPaid,
  type CatalogRoute, type Choice, type Feature, type FeatureRoutes, type Policy, type PolicyView, type Runtime } from '@/lib/routes'

const props = defineProps<{ projectId: number; plannerAgent: string; plannerModel: string; routePolicy?: Policy | null; locked?: boolean; dirty?: boolean }>()
const emit = defineEmits<{ planner: [value: { agent: string; model: string }]; policy: [value: Policy | null] }>()
const FEATURES: Feature[] = ['coordinator', 'planner', 'stories']
type Preview = Partial<Record<Feature, FeatureRoutes>>

const strip = ref<Preview>({}), stripError = ref('')
const open = ref(false), app = ref<PolicyView | null>(null), dialog = ref<Preview>({})
const choice = ref<Choice | null>(null), narrow = ref(false), draft = ref<Policy>(emptyPolicy()), coordinatorPaid = ref(false)

function find(r: FeatureRoutes | undefined, c: Choice | null): CatalogRoute | null { return r && c ? r.allowed.find(x => x.runtime === c.runtime && x.model === c.model) ?? null : null }
function describe(r: FeatureRoutes | undefined, c: Choice | null) {
  if (!r) return '…'
  if (!c) return r.empty_reason ? 'none allowed' : 'not set'
  const row = find(r, c)
  return routeLabel(c) + (row ? ` (${costLabel(row.cost_class)})` : ' (not allowed)')
}
// The planner a project uses: its own when one is set, else the Planner default from AI & models (what planning picks first on Automatic).
const appPlanner = computed(() => { const r = strip.value.planner; return r?.default && ['app', 'managed', 'project'].includes(r.default_source ?? '') ? r.default : null })
const plannerChoice = computed<Choice | null>(() => props.plannerAgent !== 'auto' && props.plannerModel ? { runtime: props.plannerAgent as Runtime, model: props.plannerModel } : null)
const scope = computed(() => (strip.value.coordinator?.scope.managed ? 'Managed · ' : '') + (props.routePolicy ? 'Narrowed for this project' : 'App policy') + (props.dirty ? ' · not saved' : ''))
function problems(p: Preview) { return FEATURES.map(f => p[f]?.empty_reason).filter((x): x is string => !!x) }

// The page polls the project every few seconds and replaces its draft with an equal copy each time, so the preview is keyed by content: it is
// requested again only when the project or its policy really changes, and a reply for an older key is dropped.
const stripKey = computed(() => `${props.projectId}|${JSON.stringify(props.routePolicy ?? null)}`)
let wanted = ''
async function loadStrip() {
  const key = stripKey.value
  wanted = key; stripError.value = ''
  try { const r = await previewRoutes(FEATURES, props.projectId, props.routePolicy ?? null); if (wanted === key) strip.value = r }
  catch (e) { if (wanted === key) stripError.value = e instanceof Error ? e.message : String(e) }
}
watch(stripKey, () => { void loadStrip() }, { immediate: true })

// The dialog's own preview follows every change, a quarter second after the last one.
const effective = computed<Policy | null>(() => narrow.value ? withCoordinatorPaid(draft.value, coordinatorPaid.value) : null)
let timer: ReturnType<typeof setTimeout> | undefined
watch(() => open.value && JSON.stringify(effective.value), on => {
  if (!on) return
  clearTimeout(timer)
  timer = setTimeout(async () => { try { dialog.value = await previewRoutes(FEATURES, props.projectId, effective.value) } catch { /* the strip shows load errors */ } }, 250)
})
onBeforeUnmount(() => clearTimeout(timer))

const providers = computed(() => [...new Set([...COMMON_PROVIDERS, ...(app.value?.providers ?? [])])])
function appAllows(kind: 'providers' | 'runtimes', item: string) {
  return [app.value?.app?.[kind], app.value?.managed?.[kind]].every(l => l === null || l === undefined || (l as string[]).includes(item))
}
function appCost(name: 'free' | 'membership' | 'paid') { return !!app.value?.app.cost[name] && (!app.value?.managed || app.value.managed.cost[name]) }
// Paid API for the Coordinator only is offered when the app (and an installation policy) allow paid API for the Coordinator.
const appCoordinatorPaid = computed(() => {
  const a = app.value
  if (!a) return false
  const rule = (p: Policy | null) => !p || (p.features.coordinator ?? p).cost.paid
  return rule(a.app) && rule(a.managed)
})
const coordinatorRow = computed(() => { const r = dialog.value.coordinator; return r ? find(r, r.default) : null })

async function change() {
  app.value = await getJson<PolicyView>('/api/routes/policy')
  choice.value = plannerChoice.value
  narrow.value = !!props.routePolicy
  const saved: Policy | null = props.routePolicy ? JSON.parse(JSON.stringify(props.routePolicy)) : null
  coordinatorPaid.value = !!saved?.features?.coordinator?.cost.paid
  draft.value = saved ? { ...emptyPolicy(), ...saved, features: {}, defaults: saved.defaults ?? {} } : { ...emptyPolicy(), cost: { ...app.value.app.cost } }
  dialog.value = strip.value
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
  emit('policy', effective.value)
  open.value = false
}
defineExpose({ reload: loadStrip })
</script>

<template>
  <section class="card route-strip" aria-label="Project settings" data-testid="route-strip">
    <h2 class="settings-title">Project settings</h2>
    <span class="eyebrow">ROUTES · {{ scope.toUpperCase() }}</span>
    <ul>
      <li><span class="muted">Coordinator</span> {{ describe(strip.coordinator, strip.coordinator?.default ?? null) }}</li>
      <li data-testid="strip-planner"><span class="muted">Planner</span>{{ ' ' }}
        <template v-if="plannerChoice">{{ describe(strip.planner, plannerChoice) }} <span class="muted small">· set for this project</span>
          <button v-if="!locked && strip.planner && !find(strip.planner, plannerChoice)" type="button" class="btn small-btn" data-testid="use-app-planner" @click="emit('planner', { agent: 'auto', model: '' })">Use app default</button></template>
        <template v-else-if="appPlanner">{{ describe(strip.planner, appPlanner) }} <span class="muted small">· app default</span></template>
        <template v-else>Automatic (membership planners first)</template></li>
      <li><span class="muted">Stories</span> {{ describe(strip.stories, strip.stories?.default ?? null) }}</li>
    </ul>
    <button type="button" class="btn" :disabled="locked" data-testid="change-routes" @click="change">Change…</button>
    <p v-if="dirty" class="muted small">Unsaved route changes: Save revision to apply them.</p>
    <p v-for="p in problems(strip)" :key="p" class="notice-warn small" role="alert">{{ p }} <RouterLink to="/profile#models-providers">AI &amp; models</RouterLink></p>
    <p v-if="stripError" class="notice-warn small" role="alert">{{ stripError }}</p>
    <div class="project-controls"><slot /></div>
  </section>
  <ModalShell v-if="open" class="project-dialog" labelledby="routes-title" @close="open = false">
    <form @submit.prevent="apply">
      <h2 id="routes-title">Project routes</h2>
      <section class="coordinator" data-testid="dialog-coordinator" aria-label="Coordinator">
        <strong>Coordinator</strong>
        <span>{{ describe(dialog.coordinator, dialog.coordinator?.default ?? null) }}</span>
        <p class="muted small">Hermes (Settings → AI & models → Coordinator) reviews the brief and checks the plan. It reaches models through free or paid API, never a membership.</p>
        <p v-if="dialog.coordinator?.empty_reason" class="notice-warn small" role="alert" data-testid="coordinator-warning">
          With these choices the Coordinator has no allowed model, so planning cannot start. {{ dialog.coordinator.empty_reason.replace(/^No Coordinator route is allowed\. /, '') }}
          Turn on free models (with a provider that offers them, or "Also offer free models from any provider"), allow paid API for the Coordinator only, or keep Same as app.
        </p>
        <p v-else-if="coordinatorRow?.cost_class === 'paid' || (coordinatorRow && coordinatorRow.cost_class === null)" class="muted small">Each plan asks for paid-planning approval before the Coordinator runs.</p>
      </section>
      <RoutePicker v-model="choice" feature="planner" :project-id="projectId" :routes="dialog.planner ?? null" label="Planner"
        :automatic="appPlanner ? `App default: ${routeLabel(appPlanner)} (AI & models → Defaults)` : 'A task-matched membership planner; an invalid plan may retry on another allowed route'" />
      <details class="advanced" data-testid="project-advanced" :open="narrow">
      <summary>Advanced: narrow the app policy for this project</summary>
      <fieldset>
        <legend>Policy for this project</legend>
        <label class="check"><input v-model="narrow" type="radio" :value="false" name="project-policy" /> Same as app <span class="muted small">(Settings → AI &amp; models)</span></label>
        <label class="check"><input v-model="narrow" type="radio" :value="true" name="project-policy" data-testid="narrow" /> Narrow for this project</label>
        <p class="muted small">A project can only narrow the app policy, never widen it. Items the app policy removes are greyed; change them in <RouterLink to="/profile#models-providers">AI &amp; models</RouterLink>.</p>
        <template v-if="narrow">
          <div class="checks" aria-label="Providers"><strong class="small">Providers</strong>
            <label v-for="p in providers" :key="p" class="check" :class="{ off: !appAllows('providers', p) }"><input type="checkbox" :disabled="!appAllows('providers', p)"
              :checked="appAllows('providers', p) && (!draft.providers || draft.providers.includes(p))" :data-testid="'project-provider-' + p" @change="e => toggle('providers', p, (e.target as HTMLInputElement).checked)" />{{ providerLabel(p) }}</label>
          </div>
          <div class="checks" aria-label="Runtimes"><strong class="small">Runtimes</strong>
            <label v-for="r in RUNTIMES" :key="r" class="check" :class="{ off: !appAllows('runtimes', r) }"><input type="checkbox" :disabled="!appAllows('runtimes', r)"
              :checked="appAllows('runtimes', r) && (!draft.runtimes || draft.runtimes.includes(r))" :data-testid="'project-runtime-' + r" @change="e => toggle('runtimes', r, (e.target as HTMLInputElement).checked)" />{{ agentLabel(r) }}</label>
          </div>
          <ToggleSwitch v-model="draft.cost.membership" :disabled="!appCost('membership')" label="Membership routes" />
          <ToggleSwitch v-model="draft.cost.free" :disabled="!appCost('free')" label="Free models" data-testid="project-free" />
          <ToggleSwitch v-model="draft.any_free" :disabled="!appCost('free') || !draft.cost.free || !draft.providers" label="Also offer free models from any provider" data-testid="project-any-free" />
          <p class="muted small switch-note">Specific free models, never openrouter/free. Lets the Coordinator run free while providers are limited.</p>
          <ToggleSwitch v-model="draft.cost.paid" :disabled="!appCost('paid')" label="Paid API (last resort, approved per plan or task)" />
          <ToggleSwitch v-model="coordinatorPaid" :disabled="!appCoordinatorPaid" label="Paid API for the Coordinator only"
            data-testid="project-coordinator-paid" />
          <p class="muted small switch-note">{{ appCoordinatorPaid ? 'Hermes reaches these providers\' models through an API. Each plan still asks for paid-planning approval.' : 'Paid API is off for the Coordinator in the app policy.' }}
            <RouterLink v-if="!appCoordinatorPaid" to="/profile#models-providers">AI &amp; models</RouterLink></p>
        </template>
      </fieldset>
      </details>
      <div class="dialog-actions"><button type="button" class="btn" @click="open = false">Cancel</button><button class="btn primary" data-testid="apply-routes">Apply to this revision</button></div>
    </form>
  </ModalShell>
</template>

<style scoped>
.route-strip{display:grid;gap:var(--gap-sm);justify-items:start;text-align:left}.route-strip ul{display:flex;flex-wrap:wrap;gap:var(--gap-xs) var(--gap-lg, 1.5rem);margin:0;padding:0;list-style:none}
.route-strip li{overflow-wrap:anywhere}.route-strip p{margin:0}
.switch-note{margin:calc(-1 * var(--gap-xs)) 0 0 2.8rem}.settings-title{font-size:var(--font-size-lg);margin:0}.project-controls{display:grid;gap:var(--gap-sm);width:100%}.advanced>summary{cursor:pointer;font-weight:600}.coordinator{display:grid;gap:var(--gap-xs);overflow-wrap:anywhere}.coordinator p{margin:0}
fieldset{border:1px solid var(--surface-border);border-radius:var(--radius);padding:var(--gap-sm) var(--gap);margin:var(--gap) 0;display:grid;gap:var(--gap-sm)}
.check{display:flex;gap:var(--gap-xs);align-items:center}.check.off{opacity:.55}.checks{display:flex;flex-wrap:wrap;gap:var(--gap-xs) var(--gap);align-items:center}.small{font-size:var(--font-size-xs)}
.project-dialog :deep(.modal-panel){padding:var(--gap-lg)}.project-dialog h2{font-size:var(--font-size-xl)}.project-dialog form{display:grid;gap:var(--gap)}
.project-dialog .dialog-actions{display:flex;justify-content:flex-end;gap:var(--gap-sm);padding-top:var(--gap-lg);border-top:1px solid var(--glass-border)}
@media (max-width:640px){.project-dialog :deep(.modal-panel){padding:var(--gap)}}
</style>
