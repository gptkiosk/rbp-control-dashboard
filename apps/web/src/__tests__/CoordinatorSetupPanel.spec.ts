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

it('shows each platform with its fix, previews the changes and applies them only after confirmation', async () => {
  const f = stubFetch((url, init) => {
    if (url === '/api/profile/coordinator-bootstrap/setup/apply') return { body: setup({ verified: true, changes: [], last: { at: 1, results: [{ id: 'rcd-oc-developer', outcome: 'done', detail: 'Registered.' }] } }) }
    if (url === '/api/profile/coordinator-bootstrap/setup') return { body: setup() }
    return undefined
  })
  const persist = vi.fn(async () => {})
  const w = mount(CoordinatorSetupPanel, { props: { hermesReady: true, persist }, ...stubs }); await flushPromises()
  expect(w.get('[data-platform="grok"] [data-test="word"]').text()).toBe('not installed')
  expect(w.get('[data-platform="grok"] a').attributes('href')).toBe('/profile#agent-tools')
  expect(w.get('[data-test="changes"]').text()).toContain('will create')
  expect(w.get('[data-action="start"]').attributes('disabled')).toBeDefined()
  expect(w.get('[data-action="apply"]').attributes('disabled')).toBeDefined()
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-action="apply"]').trigger('click'); await flushPromises()
  const sent = calls(f, 'POST', '/api/profile/coordinator-bootstrap/setup/apply')[0]!
  expect(JSON.parse(String(sent[1]?.body))).toEqual({ digest: 'abcdef0123456789' })
  expect(w.text()).toContain('Setup applied and verified.')
  expect(w.find('[data-action="apply"]').exists()).toBe(false)
  expect(w.get('[data-action="start"]').attributes('disabled')).toBeUndefined()
  w.unmount()
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
