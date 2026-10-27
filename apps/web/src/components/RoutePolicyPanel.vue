<script setup lang="ts">
// Settings → Models & providers: the app route policy. One place decides which providers, runtimes and cost classes the Coordinator, planner,
// stories, chat and tasks may use; every route picker in the app lists only what it allows.
import { computed, onMounted, ref } from 'vue'
import { getJson, putJson } from '@/lib/api'
import { agentLabel } from '@/lib/cards'
import PanelHead from './PanelHead.vue'
import ToggleSwitch from './ToggleSwitch.vue'
import AppSelect from './AppSelect.vue'
import RoutePicker from './RoutePicker.vue'
import { COMMON_PROVIDERS, FEATURE_LABELS, PRESETS, RUNTIMES, applyPreset, presetOf, providerLabel, routeLabel,
  type Choice, type Feature, type FeatureRoutes, type Policy, type PolicyView, type Preset, type Runtime } from '@/lib/routes'

const view = ref<PolicyView | null>(null), policy = ref<Policy | null>(null), summary = ref<FeatureRoutes[]>([])
const busy = ref(false), error = ref(''), saved = ref(false), provider = ref('xai'), coordinatorPaid = ref(true), generation = ref(0)
const preset = computed(() => policy.value ? presetOf(policy.value) : 'custom')
const providers = computed(() => [...new Set([...COMMON_PROVIDERS, ...(view.value?.providers ?? [])])])
const FEATURES: Feature[] = ['coordinator', 'planner', 'stories', 'chat', 'tasks']
const DEFAULTS: Feature[] = ['coordinator', 'planner', 'stories']

async function refresh() {
  const v = await getJson<PolicyView>('/api/routes/policy')
  view.value = v; policy.value = structuredClone(v.app)
  summary.value = await Promise.all(FEATURES.map(f => getJson<FeatureRoutes>(`/api/routes?feature=${f}`)))
  generation.value++
}
onMounted(async () => { try { await refresh() } catch (e) { error.value = 'Models & providers could not be loaded. Refresh to try again.' } })

function choosePreset(id: Preset['id']) { if (policy.value) { policy.value = applyPreset(policy.value, id, provider.value, coordinatorPaid.value); saved.value = false } }
function toggle<T extends string>(list: T[] | null, all: readonly T[], item: T, on: boolean): T[] | null {
  const base = list ?? [...all]
  const next = on ? [...new Set([...base, item])] : base.filter(x => x !== item)
  return next.length === all.length && all.every(x => next.includes(x)) ? null : next
}
function setProvider(id: string, on: boolean) { if (policy.value) { policy.value.providers = toggle(policy.value.providers, providers.value, id, on); saved.value = false } }
function setRuntime(id: Runtime, on: boolean) { if (policy.value) { policy.value.runtimes = toggle(policy.value.runtimes, RUNTIMES, id, on); saved.value = false } }
function setDefault(feature: Feature, choice: Choice | null) {
  if (!policy.value) return
  if (choice) policy.value.defaults[feature] = choice; else delete policy.value.defaults[feature]
  saved.value = false
}
function managedAllows(kind: 'providers' | 'runtimes', id: string) { const m = view.value?.managed; return !m || m[kind] === null || (m[kind] as string[]).includes(id) }
async function save() {
  if (!policy.value) return
  busy.value = true; error.value = ''; saved.value = false
  try { await putJson('/api/routes/policy', { policy: policy.value, confirm: true }); await refresh(); saved.value = true }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
</script>

<template>
  <section id="models-providers" class="card policy-panel" aria-labelledby="models-providers-title">
    <PanelHead id="models-providers-title" title="Models & providers" :status="view?.managed ? 'Managed' : 'App policy'" :tone="view?.managed_error ? 'warn' : 'ok'" help="project-models" />
    <p class="muted small">One policy for the Coordinator, planner, stories, chat and tasks. Every route menu in the app lists only what it allows. Membership routes are always tried first, then free models; paid API is the last resort and still needs approval per plan or task. A project can narrow this policy, never widen it.</p>
    <p v-if="view?.managed_error" class="notice-warn" role="alert">{{ view.managed_error }}</p>
    <div v-else-if="view?.managed" class="notice managed" data-testid="managed-banner">
      <strong>Managed by this installation.</strong> These settings can only narrow it:
      {{ view.managed.providers ? 'providers ' + view.managed.providers.map(providerLabel).join(', ') : 'any provider' }};
      {{ view.managed.runtimes ? 'runtimes ' + view.managed.runtimes.map(agentLabel).join(', ') : 'any runtime' }};
      cost {{ (['membership','free','paid'] as const).filter(k => view!.managed!.cost[k]).join(', ') || 'none' }}.
    </div>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <template v-if="policy">
      <fieldset class="presets"><legend>Start from</legend>
        <label v-for="p in PRESETS" :key="p.id" class="preset" :class="{ on: preset === p.id }">
          <input type="radio" name="route-preset" :value="p.id" :checked="preset === p.id" :data-testid="'preset-' + p.id" @change="choosePreset(p.id)" />
          <span><strong>{{ p.label }}</strong><span class="muted small">{{ p.note }}</span></span>
        </label>
        <div v-if="preset === 'provider'" class="provider-row">
          <label>Provider<AppSelect v-model="provider" aria-label="Single provider" @update:model-value="choosePreset('provider')"><option v-for="id in providers" :key="id" :value="id">{{ providerLabel(id) }}</option></AppSelect></label>
          <ToggleSwitch v-model="coordinatorPaid" label="Allow paid API for the Coordinator only" hint="Hermes reaches this provider's models through an API. Each plan still asks for paid-planning approval." @update:model-value="choosePreset('provider')" />
        </div>
      </fieldset>

      <fieldset><legend>Cost classes</legend>
        <ToggleSwitch v-model="policy.cost.membership" label="Membership routes" hint="Claude, Codex or Grok Build accounts you are signed in to. Uses account quota; provider overage settings still apply." @update:model-value="saved = false" />
        <ToggleSwitch v-model="policy.cost.free" label="Free models" hint="Free endpoints are often slow, limited or unavailable." @update:model-value="saved = false" />
        <ToggleSwitch v-model="policy.cost.paid" label="Paid API (last resort)" hint="Bills your provider account per token. Each plan or task still needs paid-route approval; budget checks remain active." @update:model-value="saved = false" />
      </fieldset>

      <fieldset><legend>Providers <span class="muted small">{{ policy.providers ? policy.providers.length + ' allowed' : 'all allowed' }}</span></legend>
        <div class="checks">
          <label v-for="id in providers" :key="id" class="check" :class="{ off: !managedAllows('providers', id) }">
            <input type="checkbox" :checked="!policy.providers || policy.providers.includes(id)" :disabled="!managedAllows('providers', id)" :data-testid="'provider-' + id" @change="e => setProvider(id, (e.target as HTMLInputElement).checked)" />{{ providerLabel(id) }}
          </label>
        </div>
        <ToggleSwitch v-model="policy.any_free" :disabled="!policy.providers" label="Also offer free models from any provider" hint="Specific free models (never 'provider varies' routes such as openrouter/free) as a no-cost fallback." @update:model-value="saved = false" />
        <p class="muted small">Routes whose provider varies per request (openrouter/free, openrouter/auto) are hidden whenever providers are limited.</p>
      </fieldset>

      <fieldset><legend>Runtimes <span class="muted small">{{ policy.runtimes ? policy.runtimes.length + ' allowed' : 'all allowed' }}</span></legend>
        <div class="checks">
          <label v-for="id in RUNTIMES" :key="id" class="check" :class="{ off: !managedAllows('runtimes', id) }">
            <input type="checkbox" :checked="!policy.runtimes || policy.runtimes.includes(id)" :disabled="!managedAllows('runtimes', id)" :data-testid="'runtime-' + id" @change="e => setRuntime(id, (e.target as HTMLInputElement).checked)" />{{ agentLabel(id) }}
          </label>
        </div>
      </fieldset>

      <fieldset><legend>Defaults</legend>
        <p class="muted small">Pre-selected routes, from what the saved policy allows. Save changes above first to see their effect here.</p>
        <div class="defaults">
          <RoutePicker v-for="f in DEFAULTS" :key="f + generation" :feature="f" :label="FEATURE_LABELS[f]" :model-value="policy.defaults[f] ?? null" automatic="Use the app's usual choice" @update:model-value="c => setDefault(f, c)" />
        </div>
      </fieldset>

      <div class="actions"><button type="button" class="btn primary" :disabled="busy" data-testid="save-route-policy" @click="save">Save Models &amp; providers</button><span v-if="saved" class="muted small" role="status">Saved.</span></div>

      <section class="effect" aria-label="What each feature can use">
        <h3>What each feature can use now</h3>
        <ul><li v-for="r in summary" :key="r.feature" :data-feature="r.feature">
          <strong>{{ r.label }}</strong>:
          <template v-if="r.allowed.length">{{ r.allowed.length }} route{{ r.allowed.length === 1 ? '' : 's' }}; default {{ r.default ? routeLabel(r.default) : 'none' }}</template>
          <span v-else class="warn-text">{{ r.empty_reason }}</span>
        </li></ul>
      </section>
    </template>
  </section>
</template>

<style scoped>
fieldset{border:1px solid var(--surface-border);border-radius:var(--radius);padding:var(--gap-sm) var(--gap);margin:var(--gap) 0;display:grid;gap:var(--gap-sm)}
legend{font-weight:600;padding:0 var(--gap-xs)}.small{font-size:var(--font-size-xs)}
.preset{display:flex;gap:var(--gap-sm);align-items:flex-start;cursor:pointer}.preset>span{display:grid}.preset.on strong{color:var(--accent)}
.provider-row{display:grid;gap:var(--gap-sm);padding-left:1.6em}.checks{display:flex;flex-wrap:wrap;gap:var(--gap-xs) var(--gap)}
.check{display:flex;gap:var(--gap-xs);align-items:center}.check.off{opacity:.55}.defaults{display:grid;gap:var(--gap);grid-template-columns:repeat(auto-fit,minmax(16rem,1fr))}
.actions{display:flex;gap:var(--gap-sm);align-items:center}.effect ul{margin:0;padding-left:1.2em}.effect h3{font-size:var(--font-size-sm);margin:var(--gap) 0 var(--gap-xs)}
.managed{padding:var(--gap-sm);border-left:3px solid var(--accent)}.warn-text{color:var(--warn, inherit)}
</style>
