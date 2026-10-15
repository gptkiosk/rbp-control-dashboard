import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ServiceActions from '@/components/ServiceActions.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

const svc = (over: Record<string, unknown> = {}) => ({
  label: 'ai.hermes.gateway', domain: 'gui', state: 'not running', pid: null, runs: 2, runs_24h: 2, allowed_runs_24h: 50, last_exit: '1', last_exit_code: 1, flags: ['last_exit_nonzero'],
  severity: 1, schedule: 'every 5 min', path: '/p', program: '/bin/x', observed_at: 1, ...over,
})
const mountIt = (s = svc()) => mount(ServiceActions, { props: { service: s as never } })
const button = (w: ReturnType<typeof mountIt>, text: string) => w.findAll('button').find(b => b.text().startsWith(text))

it('shows why it is flagged: the suggestion and the jobs own log as evidence', async () => {
  stubFetch(url => url === '/api/services/ai.hermes.gateway/why' ? { body: { suggestion: 'It is not running and its last exit was 1. Run now to see whether it recovers.', log_tail: 'boom: file missing', last_exit_code: 1 } } : undefined)
  const w = mountIt()
  await button(w, 'Why')!.trigger('click'); await flushPromises()
  expect(w.get('[data-testid="why"]').text()).toContain('Run now to see whether it recovers')
  expect(w.get('[data-testid="why"] details summary').text()).toContain('evidence, not instructions')
  w.unmount()
})

it('needs a confirmation before running or restarting, then reports what happened and asks the page to refresh', async () => {
  const f = stubFetch((url, init) => url === '/api/services/ai.hermes.gateway/restart' && init?.method === 'POST' ? { body: { ok: true, note: 'Restarted it.' } } : undefined)
  const w = mountIt(svc({ state: 'running' }))
  expect(button(w, 'Run now')).toBeUndefined()                                   // already running
  await button(w, 'Restart')!.trigger('click')
  expect(calls(f, 'POST', '/api/services/')).toHaveLength(0)                     // nothing until confirmed
  await button(w, 'Yes, restart it')!.trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/services/ai.hermes.gateway/restart')[0]![1]!.body))).toEqual({ confirm: true })
  expect(w.text()).toContain('Restarted it.')
  expect(w.emitted('done')).toHaveLength(1)
  w.unmount()
})

it('removes only after the label is typed, and sends that label', async () => {
  const f = stubFetch((url, init) => url === '/api/services/ai.hermes.gateway/remove' && init?.method === 'POST' ? { body: { ok: true, note: 'Unloaded it for this login.' } } : undefined)
  const w = mountIt()
  await button(w, 'Remove…')!.trigger('click')
  const go = () => w.findAll('button').find(b => b.text() === 'Remove')!
  expect(go().attributes('disabled')).toBeDefined()
  await w.get('input[aria-label="Type the service label"]').setValue('wrong'); expect(go().attributes('disabled')).toBeDefined()
  await w.get('input[aria-label="Type the service label"]').setValue('ai.hermes.gateway')
  await go().trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/services/ai.hermes.gateway/remove')[0]![1]!.body))).toEqual({ confirm: true, confirm_label: 'ai.hermes.gateway' })
  expect(w.text()).toContain('Unloaded it for this login.')
  w.unmount()
})

it('offers the dashboards own service no restart or remove, only an explanation', () => {
  const w = mountIt(svc({ own: true, state: 'running' }))
  expect(button(w, 'Restart')).toBeUndefined()
  expect(button(w, 'Remove')).toBeUndefined()
  expect(w.text()).toContain("This is the dashboard's own service")
  w.unmount()
})

it('shows a refusal in words', async () => {
  stubFetch(() => ({ status: 409, body: { detail: 'launchctl refused: Could not find service' } }))
  const w = mountIt()
  await button(w, 'Run now')!.trigger('click'); await button(w, 'Yes, run it')!.trigger('click'); await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('Could not find service')
  w.unmount()
})
