import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RoutePicker from '@/components/RoutePicker.vue'
import RoutePolicyPanel from '@/components/RoutePolicyPanel.vue'
import ProjectRouteStrip from '@/components/ProjectRouteStrip.vue'
import RouteRecoveryPanel from '@/components/RouteRecoveryPanel.vue'
import { applyPreset, emptyPolicy, presetOf, reliabilityLabel, type CatalogRoute, type FeatureRoutes, type Feature, type PolicyView, type Prices } from '@/lib/routes'
import { calls, stubFetch } from './helpers'

afterEach(() => vi.unstubAllGlobals())
const stubs = { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } }
const row = (runtime: CatalogRoute['runtime'], model: string, cost: CatalogRoute['cost_class'], extra: Partial<CatalogRoute> = {}): CatalogRoute =>
  ({ runtime, model, target: '', provider: runtime === 'grok' ? 'xai' : runtime === 'claude' ? 'anthropic' : 'xai', cost_class: cost, ready: true, listed_price: null,
     reliability: { attempts: 12, failures: 2, recent_failures: 1, persistent: false }, ...extra })
function routes(feature: Feature, over: Partial<FeatureRoutes> = {}): FeatureRoutes {
  return { feature, label: feature[0]!.toUpperCase() + feature.slice(1), default: { runtime: 'grok', model: 'grok-build-0.1' }, default_note: null,
    allowed: [row('grok', 'grok-build-0.1', 'subscription'), row('hermes', 'x-ai/grok-4.5', 'paid')],
    hidden: [row('claude', 'claude-opus-5-5', 'subscription', { hidden_because: 'App policy: anthropic is not an allowed provider' })],
    empty_reason: null, scope: { managed: false, managed_error: null, app_saved: true, project: null }, ...over }
}
const view = (over: Partial<PolicyView> = {}): PolicyView => ({ app: emptyPolicy(), app_saved: true, managed: null, managed_error: null,
  features: ['coordinator', 'planner', 'stories', 'chat', 'tasks'], runtimes: ['claude', 'codex', 'grok', 'hermes', 'openclaw'], providers: ['anthropic', 'xai'], ...over })

describe('route policy helpers', () => {
  it('presets write the cost classes they promise and are recognised again', () => {
    expect(applyPreset(emptyPolicy(), 'free').cost).toEqual({ free: true, membership: false, paid: false })
    expect(presetOf(applyPreset(emptyPolicy(), 'memberships'))).toBe('memberships')
    const grok = applyPreset(emptyPolicy(), 'provider', 'xai', true)
    expect(grok.providers).toEqual(['xai'])
    expect(grok.cost).toEqual({ free: false, membership: true, paid: false })
    expect(grok.features.coordinator?.cost).toEqual({ free: false, membership: false, paid: true })
    expect(applyPreset(grok, 'provider', 'xai', false).features.coordinator).toBeUndefined()
    expect(presetOf(grok)).toBe('provider')
    expect(presetOf({ ...grok, providers: ['xai', 'anthropic'] })).toBe('custom')
  })
  it('describes reliability in words', () => {
    expect(reliabilityLabel({ attempts: 0, failures: 0, recent_failures: 0, persistent: false })).toBe('no recent runs')
    expect(reliabilityLabel({ attempts: 12, failures: 7, recent_failures: 4, persistent: true })).toBe('12 runs in 7 days, 7 failed or timed out (failing repeatedly)')
  })
})

describe('RoutePicker', () => {
  it('lists only allowed routes with cost and reliability, and explains hidden ones', async () => {
    const fetch = stubFetch(url => url.startsWith('/api/routes?') ? { body: routes('planner') } : undefined)
    const w = mount(RoutePicker, { props: { feature: 'planner', projectId: 4, modelValue: { runtime: 'grok', model: 'grok-build-0.1' } }, global: { stubs } })
    await flushPromises()
    expect(String(calls(fetch, 'GET', '/api/routes?')[0]![0])).toBe('/api/routes?feature=planner&project_id=4')
    const options = w.findAll('option').map(o => o.text())
    expect(options).toEqual(['Grok Build · grok-build-0.1', 'Hermes · x-ai/grok-4.5'])
    expect(w.get('[data-testid="route-facts"]').text()).toBe('xAI (Grok) · membership · 12 runs in 7 days, 2 failed or timed out')
    expect(w.text()).toContain('Show hidden (1)')
    expect(w.text()).toContain('App policy: anthropic is not an allowed provider')
  })
  it('says why a saved choice is outside the policy and why nothing is offered', async () => {
    stubFetch(() => ({ body: routes('coordinator', { allowed: [], empty_reason: 'No Coordinator route is allowed. Most common reason: App policy: paid API is off.' }) }))
    const w = mount(RoutePicker, { props: { feature: 'coordinator', modelValue: { runtime: 'claude', model: 'claude-opus-5-5' } }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('is not allowed: App policy: anthropic is not an allowed provider')
    expect(w.text()).toContain('No Coordinator route is allowed')
    expect(w.get('a').attributes('href')).toBe('/profile#models-providers')
  })
})

describe('RoutePolicyPanel', () => {
  it('saves a single-provider preset with paid API for the Coordinator only', async () => {
    let saved: unknown = null
    const fetch = stubFetch((url, init) => {
      if (url === '/api/routes/policy' && init?.method === 'PUT') { saved = JSON.parse(String(init.body)); return { body: view() } }
      if (url === '/api/routes/policy') return { body: view() }
      if (url.startsWith('/api/routes?')) return { body: routes(new URLSearchParams(url.split('?')[1]).get('feature') as Feature) }
    })
    const w = mount(RoutePolicyPanel, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('What each feature can use now')
    await w.get('[data-testid="preset-provider"]').setValue(true)
    await w.get('[data-testid="save-route-policy"]').trigger('click'); await flushPromises()
    expect(calls(fetch, 'PUT', '/api/routes/policy')).toHaveLength(1)
    expect(saved).toMatchObject({ confirm: true, policy: { providers: ['xai'], cost: { free: false, membership: true, paid: false },
      features: { coordinator: { providers: ['xai'], cost: { free: false, membership: false, paid: true } } } } })
    expect(w.text()).toContain('Saved.')
  })
  it('shows a managed policy and greys what it removes', async () => {
    const managed = { ...emptyPolicy(), providers: ['xai'], runtimes: ['grok', 'hermes'] as PolicyView['runtimes'] }
    stubFetch(url => url === '/api/routes/policy' ? { body: view({ managed }) } : url.startsWith('/api/routes?') ? { body: routes('chat') } : undefined)
    const w = mount(RoutePolicyPanel, { global: { stubs } })
    await flushPromises()
    expect(w.get('[data-testid="managed-banner"]').text()).toContain('providers xAI (Grok)')
    expect((w.get('[data-testid="provider-anthropic"]').element as HTMLInputElement).disabled).toBe(true)
    expect((w.get('[data-testid="runtime-claude"]').element as HTMLInputElement).disabled).toBe(true)
    expect((w.get('[data-testid="runtime-grok"]').element as HTMLInputElement).disabled).toBe(false)
  })
})

describe('Prices to review', () => {
  it('records a reviewed price, offers free only for a model listed at no cost, and clears a review', async () => {
    const paid = { ...row('hermes', 'x-ai/grok-4.6', null, { listed_price: { free: false, prompt_per_m: 3, completion_per_m: 15 } }), can_mark_free: false }
    const free = { ...row('hermes', 'google/gemma-4-31b-it:free', null, { provider: 'google', listed_price: { free: true, prompt_per_m: 0, completion_per_m: 0 } }), can_mark_free: true }
    const grokBuild = { ...row('grok', 'grok-build-0.1', null), can_mark_free: false }
    let prices: Prices = { pending: [free, paid, grokBuild], reviewed: [] }
    const puts: unknown[] = []
    stubFetch((url, init) => {
      if (url === '/api/routes/prices' && init?.method === 'PUT') {
        const b = JSON.parse(String(init.body)); puts.push(b)
        prices = b.cost_class ? { pending: [free], reviewed: [{ runtime: 'hermes', target: '', model: b.model, cost_class: b.cost_class }] } : { pending: [free, paid], reviewed: [] }
        return { body: prices }
      }
      if (url === '/api/routes/prices') return { body: prices }
      if (url === '/api/routes/policy') return { body: view() }
      if (url.startsWith('/api/routes?')) return { body: routes(new URLSearchParams(url.split('?')[1]).get('feature') as Feature) }
    })
    const w = mount(RoutePolicyPanel, { global: { stubs } })
    await flushPromises()
    const grok = w.get('[data-route="hermes|x-ai/grok-4.6"]')
    expect(grok.text()).toContain('listed $3/M in, $15/M out')
    expect((grok.get('[data-action="free"]').element as HTMLButtonElement).disabled).toBe(true)
    expect((w.get('[data-route="hermes|google/gemma-4-31b-it:free"] [data-action="free"]').element as HTMLButtonElement).disabled).toBe(false)
    expect(w.get('[data-route="grok|grok-build-0.1"] [data-action="membership"]').attributes('href')).toBe('/agents?action=billing')
    expect(w.find('[data-route="grok|grok-build-0.1"] [data-action="free"]').exists()).toBe(false)
    await grok.get('[data-action="paid"]').trigger('click'); await flushPromises()
    expect(puts[0]).toEqual({ runtime: 'hermes', target: '', model: 'x-ai/grok-4.6', cost_class: 'paid' })
    expect(w.get('[data-reviewed="hermes|x-ai/grok-4.6"]').text()).toContain('paid API')
    await w.get('[data-reviewed="hermes|x-ai/grok-4.6"] [data-action="clear"]').trigger('click'); await flushPromises()
    expect(puts[1]).toMatchObject({ model: 'x-ai/grok-4.6', cost_class: null })
    expect(w.find('[data-reviewed]').exists()).toBe(false)
  })
})

describe('ProjectRouteStrip', () => {
  it('shows the routes in force and narrows only within the app policy', async () => {
    stubFetch(url => url === '/api/routes/policy' ? { body: view({ app: { ...emptyPolicy(), providers: ['xai'] } }) }
      : url.startsWith('/api/routes?') ? { body: routes(new URLSearchParams(url.split('?')[1]).get('feature') as Feature, { scope: { managed: false, managed_error: null, app_saved: true, project: 'same_as_app' } }) } : undefined)
    const w = mount(ProjectRouteStrip, { props: { projectId: 3, plannerAgent: 'auto', plannerModel: '', routePolicy: null }, global: { stubs } })
    await flushPromises()
    const text = w.get('[data-testid="route-strip"]').text()
    expect(text).toContain('ROUTES · APP POLICY')
    expect(text).toContain('Coordinator Grok Build · grok-build-0.1 (membership)')
    expect(text).toContain('Planner Automatic (membership planners first)')
    await w.get('[data-testid="change-routes"]').trigger('click'); await flushPromises()
    await w.get('[data-testid="narrow"]').setValue(true)
    expect((w.get('[data-testid="project-provider-anthropic"]').element as HTMLInputElement).disabled).toBe(true)
    expect((w.get('[data-testid="project-provider-xai"]').element as HTMLInputElement).disabled).toBe(false)
    await w.get('[data-testid="apply-routes"]').trigger('submit')
    expect(w.emitted('planner')?.[0]).toEqual([{ agent: 'auto', model: '' }])
    expect((w.emitted('policy')?.[0]?.[0] as { cost: unknown }).cost).toEqual({ free: true, membership: true, paid: false })
  })
})

it('Model recovery no longer has its own cost switches', async () => {
  stubFetch(url => url === '/api/profile/route-reliability' ? { body: { policy: { enabled: false, apply_to_stories: false, routes: [] }, subscription_allowed: true, paid_allowed: false, options: [], health: [], recommendations: [], window_days: 7, sample_limit: 500 } } : undefined)
  const w = mount(RouteRecoveryPanel, { global: { stubs } })
  await flushPromises()
  expect(w.get('[data-testid="cost-classes"]').text()).toContain('membership allowed, paid API off')
})
