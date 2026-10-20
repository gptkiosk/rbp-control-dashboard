import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CoordinatorSetupPanel from '@/components/CoordinatorSetupPanel.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const stubs = { global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } } }
const check = (id: string, state: string, over: Record<string, unknown> = {}) => ({ id, name: id, state, version: state === 'missing' ? null : '1.0.0', model: null, detail: `${id} detail`, link: state === 'ready' ? null : '/profile#agent-tools', ...over })
const setup = (over: Record<string, unknown> = {}) => ({
  mode: 'stable', checks: [check('openclaw', 'ready'), check('grok', 'missing')], problems: [], base: '/w', agents: ['rcd-oc-security'], digest: 'abcdef0123456789', verified: false, last: null,
  changes: [{ action: 'create', kind: 'agent', id: 'rcd-oc-developer', detail: 'Register it.', path: '/w/agents/rcd-oc-developer' }, { action: 'keep', kind: 'agent', id: 'rcd-oc-security', detail: 'Already registered.', path: null }],
  ...over,
})

it('shows each platform with its fix, applies only after confirmation, and shows progress and the log while it runs', async () => {
  vi.useFakeTimers()
  const running = { state: 'running', started: 1, finished: null, log: ['Wrote /w/agents/rcd-oc-developer/SOUL.md', '$ openclaw agents add rcd-oc-developer'], items: [{ id: 'rcd-oc-developer', label: 'Register it.', state: 'running', detail: '' }] }
  const done = { ...running, state: 'done', finished: 2, items: [{ id: 'rcd-oc-developer', label: 'Register it.', state: 'done', detail: 'Registered.' }] }
  let reads = 0
  const f = stubFetch(url => {
    if (url === '/api/profile/coordinator-bootstrap/setup/apply') return { body: setup({ job: running }) }
    if (url === '/api/profile/coordinator-bootstrap/setup') return { body: reads++ === 0 ? setup() : setup({ verified: true, changes: [], job: done }) }
    return undefined
  })
  const w = mount(CoordinatorSetupPanel, { props: { hermesReady: true, persist: async () => {} }, ...stubs }); await flushPromises()
  expect(w.get('[data-platform="grok"] [data-test="word"]').text()).toBe('not installed')
  expect(w.get('[data-platform="grok"] a').attributes('href')).toBe('/profile#agent-tools')
  expect(w.get('[data-test="changes"]').text()).toContain('will create')
  expect(w.get('[data-action="start"]').attributes('disabled')).toBeDefined()
  expect(w.get('[data-action="apply"]').attributes('disabled')).toBeDefined()
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-action="apply"]').trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/profile/coordinator-bootstrap/setup/apply')[0]![1]?.body))).toEqual({ digest: 'abcdef0123456789' })
  // While it runs: a progress bar, the item and the log, and no way to start it again.
  expect(w.get('[data-test="job"]').text()).toContain('0 of 1 done')
  expect(w.find('[data-test="job"] [role="progressbar"]').exists()).toBe(true)
  expect(w.get('[data-test="job"]').text()).toContain('$ openclaw agents add rcd-oc-developer')
  expect(w.get('[data-action="apply"]').text()).toBe('Applying…')
  expect(w.get('[data-action="apply"]').attributes('disabled')).toBeDefined()
  expect(w.find('input[type="checkbox"]').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(1500); await flushPromises()
  expect(w.get('[data-test="job"]').text()).toContain('1 of 1 done')
  expect(w.find('[data-test="job"] [role="progressbar"]').exists()).toBe(false)
  expect(w.text()).toContain('Setup applied. Start the validation project')
  expect(w.find('[data-action="apply"]').exists()).toBe(false)
  expect(w.get('[data-action="start"]').attributes('disabled')).toBeUndefined()
  w.unmount(); vi.useRealTimers()
})

it('lists failed changes, and in configure-myself mode changes nothing and says so', async () => {
  stubFetch(url => url === '/api/profile/coordinator-bootstrap/setup'
    ? { body: setup({ mode: 'custom', changes: [], verified: true, last: { at: 1, results: [{ id: 'rcd-oc-developer', outcome: 'failed', detail: 'openclaw agents add failed: gateway down' }] } }) }
    : undefined)
  const w = mount(CoordinatorSetupPanel, { props: { hermesReady: false, persist: async () => {} }, ...stubs }); await flushPromises()
  expect(w.text()).toContain('setup changes nothing')
  expect(w.text()).toContain('rcd-oc-security')
  expect(w.get('[data-test="failed"]').text()).toContain('gateway down')
  expect(w.get('[data-action="start"]').attributes('disabled')).toBeDefined()
  expect(w.text()).toContain('Finish the Hermes items above first.')
  w.unmount()
})
