import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import BugIntakePanel from '@/components/BugIntakePanel.vue'
import { stubFetch, calls } from './helpers'

afterEach(() => vi.unstubAllGlobals())
const REPO = 'gptkiosk/mac-control-dashboard'
const stubs = { global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } } }

it('explains how to turn intake on and offers no check while it is off', async () => {
  stubFetch(url => url === '/api/bug-reports/intake' ? { body: { enabled: false, repository: REPO, checked_at: null, error: null, created: [], waiting: [], already: 0 } } : undefined)
  const w = mount(BugIntakePanel, stubs); await flushPromises()
  expect(w.get('[data-testid="intake-off"]').text()).toContain('MAC_CONTROL_BUG_INTAKE_ENABLED')
  expect(w.findAll('button')).toHaveLength(0)
  w.unmount()
})

it('lists new tasks and what waits for a maintainer, linking only to the official repository', async () => {
  const f = stubFetch((url, init) => {
    const body = { enabled: true, repository: REPO, checked_at: 1700000000, error: null, already: 3,
      created: [{ number: 7, card_id: 41, urgency: 'blocker' }, { number: 9, card_id: 42, urgency: 'queued' }],
      waiting: [{ number: 8, title: 'Looks odd', url: `https://github.com/${REPO}/issues/8` }, { number: 10, title: 'Elsewhere', url: 'https://evil.example/x' }] }
    if (url === '/api/bug-reports/intake' || (url === '/api/bug-reports/intake/refresh' && init?.method === 'POST')) return { body }
    return undefined
  })
  const w = mount(BugIntakePanel, stubs); await flushPromises()
  expect(w.get('[data-testid="intake-created"]').text()).toContain('Issue #7 (break-fix)')
  expect(w.get('[data-testid="intake-created"]').text()).toContain('Issue #9 (non-essential)')
  expect(w.get('[data-testid="intake-created"] a').attributes('href')).toBe('/tasks?card=41')
  const waiting = w.get('[data-testid="intake-waiting"]')
  expect(waiting.findAll('a')).toHaveLength(1)                                           // the foreign link is not rendered
  expect(waiting.text()).toContain('#10 Elsewhere')
  await w.get('button').trigger('click'); await flushPromises()
  expect(calls(f, 'POST', '/api/bug-reports/intake/refresh')).toHaveLength(1)
  w.unmount()
})

it('shows a failed read plainly', async () => {
  stubFetch(() => ({ body: { enabled: true, repository: REPO, checked_at: 5, error: 'GitHub could not be read. Check that the gh login works; nothing was changed.', created: [], waiting: [], already: 0 } }))
  const w = mount(BugIntakePanel, stubs); await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('gh login')
  w.unmount()
})
