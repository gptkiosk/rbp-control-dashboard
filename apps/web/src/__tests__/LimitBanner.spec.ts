import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import LimitBanner from '@/components/LimitBanner.vue'
import { detailLine, liftLine, remaining } from '@/lib/limits'
import { stubFetch } from './helpers'

const NOW = 1_760_000_000
const limit = (over: Record<string, unknown> = {}) => ({
  provider: 'claude', name: 'Claude Code', detected_at: NOW - 60, lift_at: NOW + 4320, seconds_left: 4320, lift_label: '4:00 PM',
  rerouting: false, handoffs: 0, rerouted: 0, waiting: 0, alternate: 'codex', alternate_name: 'Codex', alternate_limited: false,
  can_reroute: false, ...over,
})
beforeEach(() => { vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] }); vi.setSystemTime(NOW * 1000); localStorage.clear() })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('words the lift time and the details calmly, only mentioning what happened', () => {
  expect(remaining(30)).toBe('under a minute'); expect(remaining(3000)).toBe('50 min'); expect(remaining(4320)).toBe('1 h 12 m'); expect(remaining(7200)).toBe('2 h')
  expect(liftLine(limit() as never, NOW)).toMatch(/^Claude Code limit reached\. Resets .+ \(in 1 h 12 m\)\.$/)
  expect(liftLine(limit({ lift_at: null }) as never, NOW)).toBe('Claude Code limit reached. Resume time not reported.')
  expect(liftLine(limit({ lift_at: NOW - 5 }) as never, NOW)).toContain('should have lifted')
  expect(detailLine(limit() as never)).toBe('')
  expect(detailLine(limit({ handoffs: 2, waiting: 5 }) as never)).toBe('2 stories moved to Codex on their own · 5 waiting for Claude Code.')
  expect(detailLine(limit({ handoffs: 1, rerouted: 3, waiting: 4, rerouting: true }) as never)).toBe('1 story moved to Codex on their own · 3 stories started on Codex.')
})

it('shows nothing when there is no limit', async () => {
  stubFetch(() => ({ body: { active: [], now: NOW } }))
  const w = mount(LimitBanner); await flushPromises()
  expect(w.find('section').exists()).toBe(false)
  w.unmount()
})

it('offers one button, sends the waiting stories on request and then offers to turn it off', async () => {
  let rerouting = false
  const fetch = stubFetch((url, init) => {
    if (init?.method === 'POST') { rerouting = JSON.parse(String(init.body)).enabled; return { body: { active: [], now: NOW } } }
    return { body: { active: [limit({ waiting: 5, can_reroute: !rerouting, rerouting, handoffs: 2 })], now: NOW } }
  })
  const w = mount(LimitBanner); await flushPromises()
  expect(w.text()).toContain('Claude Code limit reached')
  expect(w.text()).toContain('2 stories moved to Codex on their own')
  const send = w.findAll('button').find(b => b.text().startsWith('Send the 5 waiting stories to Codex'))!
  await send.trigger('click'); await flushPromises()
  expect(fetch.mock.calls.filter(([, i]) => i?.method === 'POST').map(([u, i]) => [u, JSON.parse(String(i!.body))])).toEqual([['/api/limits/claude/reroute', { enabled: true }]])
  expect(w.text()).toContain('New stories go to Codex until it lifts, then return.')
  expect(w.findAll('button').some(b => b.text() === 'Turn off')).toBe(true)
  w.unmount()
})

it('says so instead of offering a button when the other subscription is limited too', async () => {
  stubFetch(() => ({ body: { active: [limit({ waiting: 3, alternate_limited: true, can_reroute: false })], now: NOW } }))
  const w = mount(LimitBanner); await flushPromises()
  expect(w.text()).toContain('Codex is limited too')
  expect(w.findAll('button').filter(b => b.text().startsWith('Send')).length).toBe(0)
  w.unmount()
})

it('can be dismissed for that event and stays dismissed on reload', async () => {
  stubFetch(() => ({ body: { active: [limit()], now: NOW } }))
  const w = mount(LimitBanner); await flushPromises()
  await w.get('button[aria-label="Dismiss this notice"]').trigger('click')
  expect(w.find('section').exists()).toBe(false)
  w.unmount()
  const again = mount(LimitBanner); await flushPromises()
  expect(again.find('section').exists()).toBe(false)
  again.unmount()
})

it('shows a readable message when the routing change fails', async () => {
  stubFetch((url, init) => init?.method === 'POST' ? { status: 404, body: { detail: 'No active limit for this provider.' } }
    : { body: { active: [limit({ waiting: 1, can_reroute: true })], now: NOW } })
  const w = mount(LimitBanner); await flushPromises()
  await w.findAll('button').find(b => b.text().startsWith('Send the waiting story'))!.trigger('click'); await flushPromises()
  expect(w.text()).toContain('No active limit for this provider.')
  w.unmount()
})
