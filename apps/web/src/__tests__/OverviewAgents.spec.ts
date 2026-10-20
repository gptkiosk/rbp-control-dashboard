import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import OverviewAgents from '@/components/OverviewAgents.vue'
import { agent, stubFetch } from './helpers'

const epoch = 1_800_000_000
const summary = {
  responses: 1, input_tokens: 100, output_tokens: 10, cached_input_tokens: 50,
  cache_write_tokens: 0, api_equivalent_usd: 0.0123, unpriced: 0, sessions: 1,
  last_active: epoch - 30, models: [{ model: 'test-model' }],
}
const openclaw = agent({
  id: 'openclaw', name: 'OpenClaw', subagents: {
    processes: [{ pid: 1, kind: 'gateway', running_s: 900, model: null, session: null, cwd: '/w' }],
    agents: [{ id: 'mm-developer', name: 'Local Dev', model: 'minimax', default: false,
      bindings: 1, workspace: '/w', sessions_24h: 1, last_active_s: 30, tokens_24h: 100, models: [] }],
  },
})
function usage() {
  return {
    overview: [{ ...summary, agent: 'openclaw' }],
    sessions: [
      { ...summary, id: 'mm-developer', agent: 'openclaw', parent: null, scope: 'selected interval' },
      { ...summary, id: 'child-1', name: 'Researcher', agent: 'openclaw', parent: 'parent-1', scope: 'selected interval' },
      { ...summary, id: 'other-agent-session', name: 'Private elsewhere', agent: 'codex', parent: null, scope: 'selected interval' },
    ],
    coverage: { openclaw: { state: 'ready', checked_at: epoch } },
  }
}
async function mountSummary() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/')
  await router.isReady()
  const w = mount(OverviewAgents, { global: { plugins: [router] } })
  await flushPromises()
  return w
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('Overview live agents', () => {
  it('links related sub-agents to their details without equating a gateway process with running work', async () => {
    vi.useFakeTimers(); vi.setSystemTime(epoch * 1000)
    stubFetch(url => url === '/api/agents' ? { body: { agents: [openclaw], subagents_checked_at: epoch } } : { body: usage() })
    const w = await mountSummary()
    const card = w.get('[data-agent="openclaw"]')
    expect(card.text()).toContain('Recent activity')
    expect(card.text()).toContain('No RCD turns running')
    expect(card.text()).toContain('1 observed processes')
    expect(card.text()).toContain('$0.0123')
    expect(card.text()).not.toContain('Researcher')
    expect(card.text()).toContain('Configured agents')
    expect(w.text()).toContain('retained accounting after project or task deletion')
    expect(card.text()).not.toContain('Private elsewhere')
    expect(card.findAll('a').find(a => a.text() === 'Local Dev')?.attributes('href')).toBe('/agents?agent=openclaw&target=mm-developer')
    expect(card.findAll('a').filter(a => a.text() === 'Local Dev')).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(31_000); await flushPromises()
    expect(card.text()).toContain('Available')
    expect(card.text()).not.toContain('Recent activity')
    w.unmount()
  })

  it('names the models used without a recorded price, so the catalog can be updated', async () => {
    vi.useFakeTimers(); vi.setSystemTime(epoch * 1000)
    const gap = { ...summary, unpriced: 3, unpriced_models: ['brand-new-model', 'other-model', 'third', 'fourth'] }
    stubFetch(url => url === '/api/agents' ? { body: { agents: [openclaw], subagents_checked_at: epoch } } : { body: { ...usage(), overview: [{ ...gap, agent: 'openclaw' }] } })
    const w = await mountSummary()
    const line = w.get('[data-agent="openclaw"] .warning-text')
    expect(line.text()).toContain('3 unpriced records')
    expect(line.text()).toContain('no price for brand-new-model, other-model +2 more')
    expect(line.attributes('title')).toContain('scripts/pricing/check.py --used')
    w.unmount()
  })

  it('refreshes running chat work, preserves it with a stale warning on failure and recovers', async () => {
    vi.useFakeTimers(); vi.setSystemTime(epoch * 1000)
    let current = openclaw
    let failed = false
    stubFetch(url => url === '/api/agents'
      ? failed ? { status: 500, body: { detail: 'offline' } } : { body: { agents: [current] } }
      : { body: usage() })
    const w = await mountSummary()
    current = { ...openclaw, current: [{ run_id: 10, card_id: 0, thread_id: 12, title: 'Live chat', model: 'minimax', running_s: 5 }] }
    await vi.advanceTimersByTimeAsync(5000); await flushPromises()
    expect(w.text()).toContain('Running')
    expect(w.findAll('a').find(a => a.text() === 'Live chat')?.attributes('href')).toBe('/chat?thread=12')
    failed = true
    await vi.advanceTimersByTimeAsync(5000); await flushPromises()
    expect(w.text()).toContain('Status unavailable')
    expect(w.text()).toContain('Last received information is shown')
    expect(w.text()).toContain('Live chat')
    failed = false; current = openclaw
    await vi.advanceTimersByTimeAsync(5000); await flushPromises()
    expect(w.text()).not.toContain('Status unavailable')
    expect(w.text()).not.toContain('Live chat')
    w.unmount()
  })

  it('keeps unavailable usage as unknown instead of a zero-dollar total', async () => {
    stubFetch(url => url === '/api/agents' ? { body: { agents: [openclaw] } } : { status: 503, body: { detail: 'indexing' } })
    const w = await mountSummary()
    expect(w.text()).toContain('Usage could not refresh')
    expect(w.get('.totals').text()).toContain('—')
    expect(w.text()).not.toContain('$0.0000')
    w.unmount()
  })
})
