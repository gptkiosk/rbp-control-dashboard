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
  await w.get('input[type="checkbox"]').setValue(true)
  await w.findAll('.rates input')[0]!.setValue(2)
  await w.findAll('.rates input')[1]!.setValue(10)
  await w.get('form').trigger('submit')
  await flushPromises()
  const call = calls(f, 'PATCH', '/api/billing')[0]!
  expect(headerOf(call[1], 'X-Mac-Control')).toBe('1')
  const body = JSON.parse(String(call[1]?.body))
  expect(body.accounts.codex.monthly_usd).toBe(40)
  expect(body.rates['new-model']).toMatchObject({ input: 2, output: 10, cached: 0, write: 0, write_1h: 0 })
  expect(w.emitted('saved')).toHaveLength(1)
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
  expect(w.get('select#nchat-target-native').text()).toContain('Developer · mm-dev')
  await w.get('#nchat-target-native').setValue('mm-dev')
  expect(w.text()).toContain('Configured model: minimax')
  await w.get('form').trigger('submit')
  await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/chat/threads')[0]![1]?.body)).agent_target).toBe('mm-dev')
  w.unmount()
})
