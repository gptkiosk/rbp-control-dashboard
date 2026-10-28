import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import AgentsView from '@/views/AgentsView.vue'
import { agent, stubFetch } from './helpers'
const base = {
  responses: 1,
  input_tokens: 100,
  output_tokens: 10,
  cached_input_tokens: 50,
  cache_write_tokens: 0,
  api_equivalent_usd: 0.01,
  unpriced: 0,
  sessions: 1,
  last_active: 1000,
  models: [],
}
const agents = [
  agent({
    id: 'openclaw',
    name: 'OpenClaw',
    subagents: {
      processes: [{ pid: 12, kind: 'gateway', running_s: 60, model: null, session: null, cwd: '/ws' }],
      agents: [
        {
          id: 'mm-developer',
          name: 'Local Dev',
          model: 'minimax',
          default: false,
          bindings: 1,
          workspace: '/ws',
          sessions_24h: 0,
          last_active_s: null,
          tokens_24h: null,
          models: [],
        },
      ],
    },
  }),
  agent({ id: 'hermes', name: 'Hermes', role: 'manager' }),
  agent({ id: 'codex', name: 'Codex' }),
]
function payload(target = '') {
  return {
    period: 'month',
    overview: agents.map((a) => ({
      ...base,
      agent: a.id,
      billing: { mode: a.id === 'codex' ? 'subscription' : 'api', monthly_usd: 20 },
      month_api_equivalent_usd: 0.01,
      month_subscription_usd: 20,
      month_savings_usd: -19.99,
      month_unpriced: 0,
    })),
    summary: target ? { ...base, input_tokens: 42 } : base,
    sessions: [{ ...base, id: 'mm-developer', agent: 'openclaw', scope: 'selected interval' }],
    activity: [],
    coverage: { openclaw: { state: 'ready', checked_at: 1000 } },
    note: 'Captured usage only.',
  }
}
afterEach(() => vi.unstubAllGlobals())
describe('Agents explorer', () => {
  it('shows fleet status and drills into named sub-agent without losing options', async () => {
    const fetch = stubFetch((url) =>
      url === '/api/agents'
        ? { body: { agents } }
        : url.startsWith('/api/agents/usage')
          ? { body: payload(url.includes('target=') ? 'mm-developer' : '') }
          : undefined,
    )
    const router = createAppRouter(createMemoryHistory())
    await router.push('/agents')
    await router.isReady()
    const w = mount(AgentsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.get('[data-agent="hermes"] [data-testid="role-chip"]').text()).toBe('Coordinator')
    expect(w.get('[data-agent="openclaw"]').text()).toContain('1 live processes · 0 RCD runs')
    expect(w.get('.detail').text()).toContain('Telemetry: ready')
    expect(w.get('#process-select-native').text()).toContain('gateway · PID 12')
    const target = w.get('.selectors label:nth-child(2) select')
    await target.setValue('mm-developer')
    await flushPromises()
    expect(w.get('.target-facts').text()).toContain('Local Dev')
    expect(w.get('.metrics').text()).toContain('42')
    expect(target.text()).toContain('All sub-agents & sessions')
    expect(fetch.mock.calls.some(([u]) => u.includes('target=mm-developer'))).toBe(true)
    await w.get('[data-agent="codex"]').trigger('click')
    await flushPromises()
    expect(w.get('.subscription').text()).toContain('Estimated savings · month to date')
    expect(w.get('.savings').text()).toContain('-')
    w.unmount()
  })
  it('links Billing & rates to AI & models, and the Media button opens prices on the media section', async () => {
    const media = { provider: 'fal', fal_key_saved: true, models: [{ id: 'fal-ai/nano-banana-2', label: 'Nano Banana 2', kind: 'image', mode: 'text-to-image', unit: 'image', price_usd: 0.08, listed_price_usd: 0.08, price_source: 'https://fal.ai/pricing', price_verified: '2026-10-17', tier: 'standard', note: '' }], key_rules: { preset: 'API', note: '', allowed_models: ['fal-ai/veo3.1*'] } }
    stubFetch((url) =>
      url === '/api/agents' ? { body: { agents } }
        : url.startsWith('/api/agents/usage') ? { body: payload() }
          : url === '/api/billing' ? { body: { accounts: { openclaw: { mode: 'api', monthly_usd: 0 }, hermes: { mode: 'api', monthly_usd: 0 }, codex: { mode: 'api', monthly_usd: 0 } }, rates: {}, timezone: 'America/Los_Angeles' } }
            : url === '/api/media/models' ? { body: media }
              : undefined,
    )
    const router = createAppRouter(createMemoryHistory())
    await router.push('/agents')
    await router.isReady()
    const w = mount(AgentsView, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()
    const open = async (label: string) => { await w.findAll('button').find((b) => b.text().includes(label))!.trigger('click'); await flushPromises() }
    // Billing & rates lives in Settings → AI & models → Accounts now; the Agents page links there.
    expect(w.get('[data-testid="billing-link"]').attributes('href')).toBe('/profile?action=billing#accounts')
    await open('Media')
    expect((document.querySelector('.media-models') as HTMLDetailsElement).open).toBe(true)
    expect(document.body.textContent).toContain('Nano Banana 2')
    w.unmount()
  })
  it('makes usage failure visible instead of inventing zero costs', async () => {
    stubFetch((url) =>
      url === '/api/agents' ? { body: { agents } } : { status: 503, body: { detail: 'not ready' } },
    )
    const router = createAppRouter(createMemoryHistory())
    await router.push('/agents')
    await router.isReady()
    const w = mount(AgentsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.get('[data-agent="openclaw"] .tile-cost').text()).toContain('not reported')
    w.unmount()
  })
})
