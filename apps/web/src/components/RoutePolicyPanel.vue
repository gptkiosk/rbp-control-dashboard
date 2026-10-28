<script setup lang="ts">
// Settings → AI & models: the app route policy. One place decides which providers, runtimes and cost classes the Coordinator, planner,
// stories, chat and tasks may use; every route picker in the app lists only what it allows.
import { computed, onMounted, ref } from 'vue'
import { getJson, putJson } from '@/lib/api'
import { agentLabel } from '@/lib/cards'
import PanelHead from './PanelHead.vue'
import ToggleSwitch from './ToggleSwitch.vue'
import AppSelect from './AppSelect.vue'
import RoutePicker from './RoutePicker.vue'
import { COMMON_PROVIDERS, FEATURE_LABELS, PRESETS, RUNTIMES, applyPreset, coordinatorPaid, presetOf, providerLabel, routeLabel, setCoordinatorPaid,
  type Choice, type Feature, type FeatureRoutes, type Policy, type PolicyView, type Preset, type PriceRow, type Prices, type Runtime } from '@/lib/routes'

const view = ref<PolicyView | null>(null), policy = ref<Policy | null>(null), summary = ref<FeatureRoutes[]>([])
const busy = ref(false), error = ref(''), saved = ref(false), provider = ref('xai'), generation = ref(0)
const preset = computed(() => policy.value ? presetOf(policy.value) : 'custom')
const providers = computed(() => [...new Set([...COMMON_PROVIDERS, ...(view.value?.providers ?? [])])])
const FEATURES: Feature[] = ['coordinator', 'planner', 'stories', 'chat', 'tasks']
const DEFAULTS: Feature[] = ['planner', 'stories', 'chat', 'tasks']
// Chat's default is also where New chat and the project consultant start; Tasks' is where New task starts.
const DEFAULT_LABELS: Partial<Record<Feature, string>> = { chat: 'Chat and project consultant', tasks: 'New tasks' }

async function refresh() {
  const v = await getJson<PolicyView>('/api/routes/policy')
  view.value = v; policy.value = structuredClone(v.app)
  summary.value = await Promise.all(FEATURES.map(f => getJson<FeatureRoutes>(`/api/routes?feature=${f}`)))
  prices.value = await getJson<Prices>('/api/routes/prices').catch(() => null)
  if (!generation.value) advancedOpen.value = !!(v.app.providers || v.app.runtimes || prices.value?.pending.length)
  generation.value++
}

// Prices to review: a route nobody classified counts as paid API when a run starts. Recording what the operator checked moves it to free or
// paid; free is offered only for a model listed at no cost.
const prices = ref<Prices | null>(null), allPrices = ref(false), priceError = ref('')
// Advanced opens by itself when something in it is in use: limited providers or runtimes, or prices waiting for review.
const advancedOpen = ref(false)
const PRICE_ROWS = 8
// Claude, Codex and Grok Build are memberships when their account is saved as Subscription in Billing & rates.
const MEMBERSHIP_RUNTIMES: Runtime[] = ['claude', 'codex', 'grok']
const pendingShown = computed(() => (prices.value?.pending ?? []).slice(0, allPrices.value ? undefined : PRICE_ROWS))
function listed(r: PriceRow) {
  const p = r.listed_price
  if (!p) return 'not in the cached OpenRouter list'
  if (p.free) return 'listed free'
  return p.prompt_per_m != null ? `listed $${p.prompt_per_m}/M in, $${p.completion_per_m ?? '?'}/M out` : 'listed price unknown'
}
async function review(r: { runtime: Runtime; target: string; model: string }, cost_class: 'free' | 'paid' | null) {
  priceError.value = ''
  try { prices.value = await putJson<Prices>('/api/routes/prices', { runtime: r.runtime, target: r.target, model: r.model, cost_class }); await refresh() }
  catch (e) { priceError.value = e instanceof Error ? e.message : String(e) }
}
onMounted(async () => { try { await refresh() } catch (e) { error.value = 'AI & models could not be loaded. Refresh to try again.' } })

// A single-provider preset allows paid API for the Coordinator by default (Hermes reaches that provider through an API); the Coordinator
// section below changes it.
function choosePreset(id: Preset['id']) { if (policy.value) { policy.value = applyPreset(policy.value, id, provider.value, id === 'provider' ? true : coordinatorPaid(policy.value)); saved.value = false } }
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
function setPaidCoordinator(on: boolean) { if (policy.value) { policy.value = setCoordinatorPaid(policy.value, on); saved.value = false } }
// Paid API for the Coordinator, as an installation-managed policy allows it.
const managedCoordinatorPaid = computed(() => { const m = view.value?.managed; return !m || (m.features.coordinator ?? m).cost.paid })
const coordinatorSummary = computed(() => summary.value.find(r => r.feature === 'coordinator') ?? null)
function managedAllows(kind: 'providers' | 'runtimes', id: string) { const m = view.value?.managed; return !m || m[kind] === null || (m[kind] as string[]).includes(id) }
async function save() {
  if (!policy.value) return
  busy.value = true; error.value = ''; saved.value = false
  // The Coordinator rule follows the general providers, models and free setting chosen above.
  if (policy.value.features.coordinator) policy.value = setCoordinatorPaid(policy.value, coordinatorPaid(policy.value))
  try { await putJson('/api/routes/policy', { policy: policy.value, confirm: true }); await refresh(); saved.value = true }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
</script>

<template>
  <section id="models-providers" class="card policy-panel" aria-labelledby="models-providers-title">
    <PanelHead id="models-providers-title" title="AI & models" :status="view?.managed ? 'Managed' : 'App policy'" :tone="view?.managed_error ? 'warn' : 'ok'" help="models-providers" />
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
        </div>
      </fieldset>

      <fieldset><legend>Cost classes</legend>
        <ToggleSwitch v-model="policy.cost.membership" label="Membership routes" hint="Claude, Codex or Grok Build accounts you are signed in to. Uses account quota; provider overage settings still apply." @update:model-value="saved = false" />
        <ToggleSwitch v-model="policy.cost.free" label="Free models" hint="Free endpoints are often slow, limited or unavailable." @update:model-value="saved = false" />
        <ToggleSwitch v-model="policy.cost.paid" label="Paid API (last resort)" hint="Bills your provider account per token. Each plan or task still needs paid-route approval; budget checks remain active." @update:model-value="saved = false" />
      </fieldset>

      <fieldset data-testid="coordinator-section"><legend>Coordinator</legend>
        <p class="muted small">The Coordinator, Hermes, reviews each brief and checks each plan. It reaches models through free or paid API, never a membership, so a membership-only policy leaves it nothing.</p>
        <ToggleSwitch :model-value="coordinatorPaid(policy)" :disabled="!managedCoordinatorPaid" label="Allow paid API for the Coordinator" data-testid="coordinator-paid" @update:model-value="setPaidCoordinator" />
        <p class="muted small switch-note">{{ managedCoordinatorPaid ? 'Paid models of the allowed providers become Coordinator choices. Each plan still asks for paid-planning approval, and a model whose price was never reviewed counts as paid. Other features keep the cost classes above.' : 'This installation\'s managed policy does not allow paid API for the Coordinator.' }}</p>
        <RoutePicker :key="'coordinator' + generation" feature="coordinator" label="Coordinator model" :model-value="policy.defaults.coordinator ?? null" automatic="Hermes's own configured model when allowed, else the first allowed" @update:model-value="c => setDefault('coordinator', c)" />
        <p v-if="coordinatorSummary && coordinatorSummary.allowed.length === 1" class="notice-warn small" data-testid="coordinator-single">Only one Coordinator model is allowed, so planning stops if it is unavailable. Allow another free provider, or paid API for the Coordinator, to give it a fallback.</p>
        <p class="muted small">The model list comes from the saved policy: save after changing the switch to see paid models here.</p>
        <slot name="coordinator" />
      </fieldset>

      <fieldset><legend>Defaults</legend>
        <p class="muted small">Pre-selected routes, from what the saved policy allows. Save changes above first to see their effect here. New chat, New task and the project consultant start from the Chat and Tasks defaults; you can still change the route in each.</p>
        <div class="defaults">
          <RoutePicker v-for="f in DEFAULTS" :key="f + generation" :feature="f" :label="DEFAULT_LABELS[f] ?? FEATURE_LABELS[f]" :model-value="policy.defaults[f] ?? null" automatic="Use the app's usual choice" @update:model-value="c => setDefault(f, c)" />
        </div>
        <slot name="defaults" />
      </fieldset>

      <div class="actions"><button type="button" class="btn primary" :disabled="busy" data-testid="save-route-policy" @click="save">Save AI &amp; models</button><span v-if="saved" class="muted small" role="status">Saved.</span></div>

      <slot name="accounts" />

      <details class="advanced" data-testid="advanced" :open="advancedOpen" @toggle="e => advancedOpen = (e.target as HTMLDetailsElement).open">
        <summary>Advanced <span class="muted small">providers, runtimes, prices to review, recovery, rates and limits</span></summary>
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
        <section v-if="prices && (prices.pending.length || prices.reviewed.length)" class="prices" aria-labelledby="prices-title" data-testid="prices">
        <h3 id="prices-title">Prices to review</h3>
        <p class="muted small">These routes are allowed apart from their price, which nobody has reviewed, so they count as paid API when a run starts. Check the provider's price and record it. Free is offered only for a model listed at no cost. Memberships are set in Billing &amp; rates.</p>
        <p v-if="priceError" class="notice-warn" role="alert">{{ priceError }}</p>
        <ul class="price-rows">
          <li v-for="r in pendingShown" :key="r.runtime + r.target + r.model" :data-route="r.runtime + '|' + r.model">
            <span><strong>{{ routeLabel(r) }}</strong><span v-if="r.target" class="muted small"> · {{ r.target }}</span> <span class="muted small">{{ providerLabel(r.provider) }} · {{ listed(r) }}</span></span>
            <span class="price-actions">
              <button type="button" class="btn" data-action="paid" @click="review(r, 'paid')">Paid API</button>
              <RouterLink v-if="MEMBERSHIP_RUNTIMES.includes(r.runtime)" class="btn" to="/profile?action=billing#accounts" data-action="membership">Membership: Accounts</RouterLink>
              <button v-else type="button" class="btn" data-action="free" :disabled="!r.can_mark_free" :title="r.can_mark_free ? '' : 'Only a model listed at no cost can be marked free'" @click="review(r, 'free')">Free</button>
            </span>
          </li>
        </ul>
        <button v-if="!allPrices && (prices.pending.length > PRICE_ROWS)" type="button" class="btn link" @click="allPrices = true">Show all ({{ prices.pending.length }})</button>
        <template v-if="prices.reviewed.length">
          <h4>Reviewed here</h4>
          <ul class="price-rows">
            <li v-for="r in prices.reviewed" :key="r.runtime + r.target + r.model" :data-reviewed="r.runtime + '|' + r.model">
              <span><strong>{{ routeLabel(r) }}</strong> <span class="muted small">{{ r.cost_class === 'free' ? 'free' : 'paid API' }}</span></span>
              <button type="button" class="btn" data-action="clear" @click="review(r, null)">Clear</button>
            </li>
          </ul>
        </template>
      </section>
        <slot name="advanced" />
      </details>

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
.advanced{margin:var(--gap) 0}.advanced>summary{cursor:pointer;font-weight:600}.switch-note{margin:calc(-1 * var(--gap-xs)) 0 0 2.8rem}.managed{padding:var(--gap-sm);border-left:3px solid var(--accent)}.warn-text{color:var(--warn, inherit)}
.prices h3{font-size:var(--font-size-sm);margin:var(--gap) 0 var(--gap-xs)}.prices h4{font-size:var(--font-size-xs);margin:var(--gap-sm) 0 var(--gap-xs)}
.price-rows{list-style:none;margin:0;padding:0;display:grid;gap:var(--gap-xs)}.price-rows li{display:flex;flex-wrap:wrap;gap:var(--gap-xs) var(--gap-sm);align-items:center;justify-content:space-between;overflow-wrap:anywhere}
.price-actions{display:flex;gap:var(--gap-xs)}
</style>
