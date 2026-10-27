import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AgentBillingDialog from '@/components/AgentBillingDialog.vue'
import NewChatDialog from '@/components/NewChatDialog.vue'
import { agent, calls, headerOf, stubFetch } from './helpers'
afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
it('saves subscription configuration with request guard and custom cache rates', async () => {
  const f = stubFetch((u, init) =>
    u === '/api/billing'
      ? {
          body:
            init?.method === 'PATCH'
              ? {}
              : {
                  accounts: { codex: { mode: 'subscription', monthly_usd: 20 } },
                  rates: {},
                  timezone: 'America/Los_Angeles',
                },
        }
      : undefined,
  )
  const w = mount(AgentBillingDialog, {
    props: { agents: [agent({ id: 'codex', name: 'Codex' })], models: ['new-model'] },
  })
  await flushPromises()
  await w.get('input[aria-label="Codex monthly subscription"]').setValue(40)
  await w.get('input[aria-label="Model ID"]').setValue('new-model')
  await w.get('.rate-settings input[type="checkbox"]').setValue(true)
  await w.findAll('.rates input')[0]!.setValue(2)
  await w.findAll('.rates input')[1]!.setValue(10)
  await w.get('form').trigger('submit')
  await flushPromises()
  const call = calls(f, 'PATCH', '/api/billing')[0]!
  expect(headerOf(call[1], 'X-Mac-Control')).toBe('1')
  const body = JSON.parse(String(call[1]?.body))
  expect(body.accounts.codex.monthly_usd).toBe(40)
  expect(body.rates['new-model']).toMatchObject({ input: 2, output: 10, cached: 0, write: 0, write_1h: 0 })
  expect(body.limits).toEqual({ require_reviewed_pricing: false, per_run_cap_usd: null, paid_needs_runtime_limit: false })
  expect(w.emitted('saved')).toHaveLength(1)
  w.unmount()
})
it('shows spending limits off by default and saves the ones you turn on', async () => {
  const f = stubFetch((u, init) =>
    u === '/api/billing'
      ? {
          body:
            init?.method === 'PATCH'
              ? {}
              : { accounts: { codex: { mode: 'api', monthly_usd: 0 } }, rates: {}, timezone: 'America/Los_Angeles' },
        }
      : undefined,
  )
  const w = mount(AgentBillingDialog, {
    props: { agents: [agent({ id: 'codex', name: 'Codex' })], models: [] },
  })
  await flushPromises()
  const box = w.get('.limits')
  expect(box.text()).toContain('Spending & limits')
  expect(box.text()).toContain('Nothing here is on by default')
  const checks = box.findAll('input[type="checkbox"]')
  expect(checks.map((c) => (c.element as HTMLInputElement).checked)).toEqual([false, false])
  await checks[0]!.setValue(true)
  await box.get('input[aria-label="Cap per run in USD"]').setValue(2.5)
  await w.get('form').trigger('submit')
  await flushPromises()
  const body = JSON.parse(String(calls(f, 'PATCH', '/api/billing')[0]![1]?.body))
  expect(body.limits).toEqual({ require_reviewed_pricing: true, per_run_cap_usd: 2.5, paid_needs_runtime_limit: false })
  w.unmount()
})
it('lists media models, shows unlisted prices as blank and saves only the prices you change', async () => {
  const models = [
    { id: 'fal-ai/nano-banana-2', label: 'Nano Banana 2', kind: 'image', mode: 'text-to-image', unit: 'image', price_usd: 0.08, listed_price_usd: 0.08, price_source: 'https://fal.ai/pricing', price_verified: '2026-10-17', tier: 'standard', note: '' },
    { id: 'fal-ai/veo3.1/fast/image-to-video', label: 'Veo 3.1 Fast (image to video)', kind: 'video', mode: 'image-to-video', unit: 'second', price_usd: null, listed_price_usd: null, price_source: 'https://fal.ai/pricing', price_verified: '2026-10-17', tier: 'standard', note: 'Price not on fal pricing page.' },
  ]
  const f = stubFetch((u, init) => {
    if (u === '/api/media/models')
      return { body: { provider: 'fal', fal_key_saved: true, models, key_rules: { preset: 'API', note: '', allowed_models: ['fal-ai/veo3.1*'] } } }
    if (u === '/api/billing')
      return { body: init?.method === 'PATCH' ? {} : { accounts: { codex: { mode: 'api', monthly_usd: 0 } }, rates: {}, timezone: 'America/Los_Angeles' } }
  })
  const w = mount(AgentBillingDialog, { props: { agents: [agent({ id: 'codex', name: 'Codex' })], models: [] } })
  await flushPromises()
  const box = w.get('.media-models')
  expect(box.text()).toContain('Nano Banana 2')
  expect(box.text()).toContain('fal key: saved')
  expect(box.text()).toContain('fal-ai/veo3.1*')
  const veo = box.get('input[aria-label="Veo 3.1 Fast (image to video) price per second"]')
  expect((veo.element as HTMLInputElement).placeholder).toBe('not listed')
  expect((box.get('input[aria-label="Nano Banana 2 price per image"]').element as HTMLInputElement).value).toBe('')
  await veo.setValue(0.15)
  await w.get('form').trigger('submit')
  await flushPromises()
  const body = JSON.parse(String(calls(f, 'PATCH', '/api/billing')[0]![1]?.body))
  expect(body.media_rates).toEqual({ 'fal-ai/veo3.1/fast/image-to-video': 0.15 })
  w.unmount()
})
it('uses configured OpenClaw names and submits the selected ID', async () => {
  const f = stubFetch((u, init) => {
    if (u === '/api/agents')
      return {
        body: {
          agents: [
            agent({
              id: 'openclaw',
              name: 'OpenClaw',
              subagents: {
                processes: [],
                agents: [
                  {
                    id: 'mm-main',
                    name: 'Orchestrator',
                    default: true,
                    model: 'gemini',
                    bindings: 1,
                    workspace: '/ws',
                    sessions_24h: 0,
                    last_active_s: null,
                    tokens_24h: null,
                    models: [],
                  },
                  {
                    id: 'mm-dev',
                    name: 'Developer',
                    default: false,
                    model: 'minimax',
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
          ],
        },
      }
    if (u === '/api/workdirs')
      return { body: { workdirs: [{ path: '/ws', root: '/ws', branch: 'feature' }] } }
    if (init?.method === 'POST') return { body: { id: 12 } }
  })
  const w = mount(NewChatDialog)
  await flushPromises()
  await w.get('#nchat-agent-native').setValue('openclaw')
  expect(w.get('select#nchat-target-native').text()).toContain('Developer · mm-dev')
  await w.get('#nchat-target-native').setValue('mm-dev')
  expect(w.text()).toContain('Configured model: minimax')
  await w.get('form').trigger('submit')
  await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/chat/threads')[0]![1]?.body)).agent_target).toBe('mm-dev')
  w.unmount()
})
it('leaves out the accounts of runtimes an installation-managed route policy removes', async () => {
  const { resetManagedRuntimes } = await import('@/lib/routes')
  resetManagedRuntimes()
  stubFetch(u => u === '/api/billing' ? { body: { accounts: { codex: { mode: 'subscription', monthly_usd: 20 }, grok: { mode: 'subscription', monthly_usd: 30 } }, rates: {}, timezone: 'America/Los_Angeles' } }
    : u === '/api/routes/policy' ? { body: { managed_runtimes: ['grok', 'hermes'] } } : undefined)
  const w = mount(AgentBillingDialog, {
    props: { agents: [agent({ id: 'codex', name: 'Codex' }), agent({ id: 'grok', name: 'Grok Build' })], models: [] },
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  await flushPromises()
  expect(w.findAll('.account strong').map(s => s.text())).toEqual(['Grok Build'])
  expect(w.get('[data-testid="managed-hidden"]').text()).toContain('Claude, Codex, OpenClaw')
  resetManagedRuntimes()
})
