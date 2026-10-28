// Route policy and route catalog (apps/api/route_policy.py, route_catalog.py): which providers, runtimes, models and cost classes may be used.
import { computed, ref, watch, type Ref } from 'vue'
import { getJson, postJson } from '@/lib/api'
import { agentLabel } from '@/lib/cards'

export type Runtime = 'claude' | 'codex' | 'grok' | 'hermes' | 'openclaw'
export type Feature = 'coordinator' | 'planner' | 'stories' | 'chat' | 'tasks'
export type CostClass = 'free' | 'subscription' | 'paid' | null
export interface Reliability { attempts: number; failures: number; recent_failures: number; persistent: boolean }
export interface CatalogRoute {
  runtime: Runtime; target: string; model: string; provider: string; cost_class: CostClass; ready: boolean
  listed_price: { free?: boolean; prompt_per_m?: number | null; completion_per_m?: number | null } | null
  reliability: Reliability; hidden_because?: string
}
export interface Choice { runtime: Runtime; model: string }
export interface FeatureRoutes {
  feature: Feature; label: string; default: Choice | null; default_note: string | null
  allowed: CatalogRoute[]; hidden: CatalogRoute[]; empty_reason: string | null
  scope: { managed: boolean; managed_error: string | null; app_saved: boolean; project: 'narrowed' | 'same_as_app' | null }
}
export interface Cost { free: boolean; membership: boolean; paid: boolean }
export interface Filter { providers: string[] | null; runtimes: Runtime[] | null; models: { allow: string[]; block: string[] }; cost: Cost; any_free: boolean }
export interface Policy extends Filter { features: Partial<Record<Feature, Filter>>; defaults: Partial<Record<Feature, Choice>> }
export interface PolicyView {
  app: Policy; app_saved: boolean; managed: Policy | null; managed_error: string | null; managed_runtimes?: Runtime[] | null
  features: Feature[]; runtimes: Runtime[]; providers: string[]
}
export interface PriceRow extends CatalogRoute { can_mark_free: boolean }
export interface Prices { pending: PriceRow[]; reviewed: { runtime: Runtime; target: string; model: string; cost_class: 'free' | 'paid' }[] }

export const RUNTIMES: Runtime[] = ['claude', 'codex', 'grok', 'hermes', 'openclaw']
export const FEATURE_LABELS: Record<Feature, string> = { coordinator: 'Coordinator', planner: 'Planner', stories: 'Stories', chat: 'Chat', tasks: 'Tasks' }
// Providers that always appear as choices; others are added from what this host's routes name.
export const COMMON_PROVIDERS = ['anthropic', 'openai', 'xai', 'google', 'meta', 'mistral', 'deepseek', 'qwen']
export const PROVIDER_LABELS: Record<string, string> = { anthropic: 'Anthropic', openai: 'OpenAI', xai: 'xAI (Grok)', google: 'Google', meta: 'Meta', mistral: 'Mistral', deepseek: 'DeepSeek', qwen: 'Qwen', router: 'Provider varies' }

export function emptyFilter(): Filter { return { providers: null, runtimes: null, models: { allow: [], block: [] }, cost: { free: true, membership: true, paid: false }, any_free: false } }
export function emptyPolicy(): Policy { return { ...emptyFilter(), features: {}, defaults: {} } }
export function providerLabel(id: string) { return PROVIDER_LABELS[id] ?? id }
export function costLabel(c: CostClass) { return c === 'subscription' ? 'membership' : c === 'free' ? 'free' : c === 'paid' ? 'paid API' : 'price not reviewed (counts as paid)' }
export function reliabilityLabel(r: Reliability) {
  if (!r.attempts) return 'no recent runs'
  const bad = r.failures ? `, ${r.failures} failed or timed out` : ''
  return `${r.attempts} run${r.attempts === 1 ? '' : 's'} in 7 days${bad}` + (r.persistent ? ' (failing repeatedly)' : '')
}
export function routeKey(r: { runtime: string; model: string }) { return `${r.runtime}|${r.model}` }
export function parseKey(key: string): Choice | null {
  const i = key.indexOf('|')
  return i > 0 ? { runtime: key.slice(0, i) as Runtime, model: key.slice(i + 1) } : null
}
export function routeLabel(r: { runtime: string; model: string }) { return `${agentLabel(r.runtime)} · ${r.model}` }

export interface Preset { id: 'free' | 'memberships' | 'provider' | 'custom'; label: string; note: string }
export const PRESETS: Preset[] = [
  { id: 'memberships', label: 'Memberships (recommended)', note: 'Claude, Codex or Grok Build accounts you are signed in to, with free models as a fallback. No API charges.' },
  { id: 'provider', label: 'Single provider…', note: 'Only one provider\'s models, for example xAI. The Coordinator (Hermes) reaches them through an API, so this turns on paid API for the Coordinator; change it under Coordinator.' },
  { id: 'free', label: 'Free only', note: 'For trying the app. Expect frequent timeouts and incomplete output.' },
  { id: 'custom', label: 'Custom', note: 'Choose providers, runtimes and cost classes yourself.' },
]
/** The policy a preset writes. Defaults and per-feature rules not touched by the preset are kept. */
export function applyPreset(policy: Policy, id: Preset['id'], provider = 'xai', coordinatorPaid = true): Policy {
  const next: Policy = JSON.parse(JSON.stringify(policy))   // the policy may be a reactive proxy, which structuredClone cannot copy
  if (id === 'free') Object.assign(next, { providers: null, runtimes: null, any_free: false, cost: { free: true, membership: false, paid: false } })
  if (id === 'memberships') Object.assign(next, { providers: null, runtimes: null, any_free: false, cost: { free: true, membership: true, paid: false } })
  if (id === 'provider') {
    Object.assign(next, { providers: [provider], runtimes: null, any_free: false, cost: { free: false, membership: true, paid: false } })
    if (coordinatorPaid) next.features.coordinator = { ...emptyFilter(), providers: [provider], cost: { free: false, membership: false, paid: true } }
    else delete next.features.coordinator
  }
  return next
}
export function presetOf(p: Policy): Preset['id'] {
  const { free, membership, paid } = p.cost
  // The Coordinator's own paid-API rule (AI & models → Coordinator) does not change which preset the rest of the policy matches.
  if (!p.providers && !p.runtimes && !p.models.allow.length && !p.models.block.length && !Object.keys(p.features).filter(f => f !== 'coordinator').length) {
    if (free && !membership && !paid) return 'free'
    if (free && membership && !paid) return 'memberships'
  }
  if (p.providers?.length === 1 && !p.runtimes && membership && !paid) return 'provider'
  return 'custom'
}

/** Allowed routes for one feature (and project), refreshed when the project changes. */
export function useRoutes(feature: Feature, projectId?: Ref<number | null | undefined>) {
  const data = ref<FeatureRoutes | null>(null), error = ref('')
  async function load() {
    error.value = ''
    const q = new URLSearchParams({ feature })
    if (projectId?.value) q.set('project_id', String(projectId.value))
    try { data.value = await getJson<FeatureRoutes>(`/api/routes?${q}`) }
    catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  }
  if (projectId) watch(projectId, () => { void load() })
  void load()
  return { data, error, load }
}

/** Models the policy allows for one runtime, memberships first; `fallback` until the catalog has loaded. */
export function allowedModels(data: FeatureRoutes | null, runtime: string, fallback: string[] = []) {
  return data ? [...new Set(data.allowed.filter(r => r.runtime === runtime).map(r => r.model))] : fallback
}
export function runtimeAllowed(data: FeatureRoutes | null, runtime: string) { return !data || data.allowed.some(r => r.runtime === runtime) }

/** Runtimes an installation-managed policy leaves, for Agent tools, Setup and Billing & rates. Without a managed policy (or when the policy
 *  cannot be read) every runtime is shown: hiding is a convenience, and routing still enforces the policy. */
let managedLoad: Promise<Runtime[] | null> | null = null
export function useManagedRuntimes() {
  const runtimes = ref<Runtime[] | null>(null)
  managedLoad ??= getJson<PolicyView>('/api/routes/policy').then(v => v.managed_runtimes ?? null, () => { managedLoad = null; return null })
  void managedLoad.then(r => { runtimes.value = r })
  // Agent tools names Claude Code's installer 'claude-code'.
  const shown = (id: string) => { const r = id === 'claude-code' ? 'claude' : id; return !runtimes.value || !(RUNTIMES as string[]).includes(r) || (runtimes.value as string[]).includes(r) }
  const hidden = computed(() => runtimes.value ? RUNTIMES.filter(r => !(runtimes.value as string[]).includes(r)) : [])
  return { runtimes, shown, hidden }
}
/** Tests only: forget the cached managed policy. */
export function resetManagedRuntimes() { managedLoad = null }

/** What each feature would allow with an unsaved project policy (null: Same as app). Saves nothing. */
export async function previewRoutes(features: Feature[], projectId: number | null | undefined, policy: Policy | null) {
  return postJson<Partial<Record<Feature, FeatureRoutes>>>('/api/routes/preview', { features, project_id: projectId ?? null, policy })
}
/** The app policy's Coordinator rule: the general rule with paid API switched on or off for the Coordinator alone. It follows the general
 *  rule's providers, models and free setting; memberships never apply to Hermes. Removed when it would match the general rule. */
export function setCoordinatorPaid(policy: Policy, on: boolean): Policy {
  const next: Policy = JSON.parse(JSON.stringify(policy))
  if (on === next.cost.paid) delete next.features.coordinator
  else next.features.coordinator = { ...emptyFilter(), providers: next.providers, runtimes: null, models: next.models, any_free: next.any_free, cost: { free: next.cost.free, membership: false, paid: on } }
  return next
}
export function coordinatorPaid(policy: Policy) { return (policy.features.coordinator ?? policy).cost.paid }

/** The Coordinator is Hermes (Settings → AI & models → Coordinator), which reaches models only through free or paid API, never a membership. A project's
 *  "paid API for the Coordinator only" exception is a Coordinator rule that follows the project's providers and models. */
export function withCoordinatorPaid(policy: Policy, on: boolean): Policy {
  const next: Policy = JSON.parse(JSON.stringify(policy))
  if (on) next.features.coordinator = { ...emptyFilter(), providers: next.providers, models: next.models, any_free: next.any_free, cost: { free: next.cost.free, membership: false, paid: true } }
  else delete next.features.coordinator
  return next
}
