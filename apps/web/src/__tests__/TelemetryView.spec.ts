import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TelemetryView from '@/views/TelemetryView.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

const body = (over: Record<string, unknown> = {}) => ({
  generated_at: 1_800_000_000, days: 30, filters: {}, options: { job: ['p1r1'], kind: ['implement', 'review'], risk: [], size: [], tier: ['free', 'subscription'], assignee: ['codex', 'jamie@example.com'], agent: ['codex', 'hermes'], model: ['gpt-6.1-sol'] },
  tiles: { unassigned: 2, in_progress: 3, waiting_for_you: 1, completed: 14, completed_days: 30, estimates_missing: 4, failed: 1, untagged: 5 },
  by_status: [{ column: 'backlog', count: 4 }, { column: 'running', count: 3 }, { column: 'done', count: 14 }],
  by_tier: [{ tier: 'free', count: 12 }, { tier: 'subscription', count: 6 }, { tier: 'api', count: 0 }, { tier: 'human', count: 2 }],
  by_assignee: [{ name: 'codex', type: 'agent', open: 2, done: 9, failed: 1 }, { name: 'jamie@example.com', type: 'human', open: 1, done: 3, failed: 0 }, { name: 'Unassigned', type: 'human', open: 2, done: 0, failed: 0 }],
  velocity: [{ week: '2026-10-05', done: 6 }, { week: '2026-10-12', done: 8 }],
  jobs: [{ job: 'p1r1', project_id: 1, title: 'Ship the thing', stories: 5, done: 3, failed: 0, open: 2, estimate_minutes: 300, actual_minutes: 180, cost_usd: 0, api_equivalent_usd: 1.25, last_activity: 1_799_990_000 }],
  by_kind: [{ kind: 'implement', stories: 8, done: 6, median_minutes: 42, first_pass_rate: 0.67, median_actual_over_estimate: 1.2 }],
  models: [{ agent: 'hermes', model: 'google/gemini-2.5-flash', tier: 'free', runs: 10, succeeded: 8, success_rate: 0.8, median_seconds: 95, tokens: 120000, cost_usd: 0, api_equivalent_usd: 0.4, served_instead_of_requested: 3 }],
  activity: [{ at: 1_799_990_000, card_id: 7, title: 'Write the notes', outcome: 'succeeded', assignee: 'hermes', agent: 'hermes', model: 'openrouter/free', job: 'p1r1' }],
  totals: { cost_usd: 0, api_equivalent_usd: 1.65, unpriced_runs: 1, tokens: 120000, cards: 20 }, note: 'API-equivalent cost is an estimate.', ...over,
})

it('shows the tiles, who work is assigned to (people and agents), the agent and model that served each run, and the totals', async () => {
  stubFetch(url => url.startsWith('/api/telemetry') ? { body: body() } : undefined)
  const w = mount(TelemetryView); await flushPromises()
  const tiles = w.findAll('article.tile').map(t => t.text().replace(/\s+/g, ' '))
  expect(tiles.some(t => t.includes('Unassigned') && t.includes('2'))).toBe(true)
  expect(tiles.some(t => t.includes('Completed, 30 days') && t.includes('14'))).toBe(true)
  const assignees = w.get('[aria-label="Work by assignee"]').text()
  expect(assignees).toContain('codex (agent)')
  expect(assignees).toContain('jamie@example.com (human)')
  expect(assignees).toContain('Unassigned (human)')
  const models = w.get('[aria-label="Agents and models table"]').text()
  expect(models).toContain('hermes')
  expect(models).toContain('google/gemini-2.5-flash')
  expect(models).toContain('Served instead of requested')
  expect(w.get('[aria-label="Jobs table"]').text()).toContain('Ship the thing')
  expect(w.text()).toContain('1 unpriced run')
  expect(w.text()).toContain('API-equivalent $1.65')
  w.unmount()
})

it('shows charts at a glance (donuts and stacked bars) with the tables folded away until asked for', async () => {
  stubFetch(url => url.startsWith('/api/telemetry') ? { body: body() } : undefined)
  const w = mount(TelemetryView); await flushPromises()
  const status = w.get('[aria-label="Workload by status"]')
  expect(status.find('svg').exists()).toBe(true)
  expect(status.text()).toContain('done')
  expect(status.text()).toContain('67%')                                    // 14 of 21, so colour is never the only signal
  expect(w.get('[aria-label="Work by route"]').text()).toContain('free')
  const assignees = w.get('[aria-label="Work by assignee"]')
  expect(assignees.findAll('.seg').length).toBeGreaterThan(0)
  expect(assignees.text()).toContain('9 done')
  expect(w.get('[aria-label="Jobs"] ul.list li').attributes('title')).toContain('estimate')
  expect(w.get('[aria-label="Runs by model"]').text()).toContain('hermes · google/gemini-2.5-flash')
  for (const t of ['Jobs table', 'Agents and models table', 'Kinds of work table']) expect(w.get(`details[aria-label="${t}"]`).attributes('open')).toBeUndefined()
  w.unmount()
})

it('narrows every view when a filter is chosen, by sending it to the server, and clears them', async () => {
  const f = stubFetch(url => url.startsWith('/api/telemetry') ? { body: body() } : undefined)
  const w = mount(TelemetryView); await flushPromises()
  expect(calls(f, 'GET', '/api/telemetry')[0]![0]).toBe('/api/telemetry?days=30')
  await w.get('[role="combobox"][aria-label="Agent"]').trigger('click'); await flushPromises()
  await w.findAll('[role="option"]').find(o => o.text() === 'hermes')!.trigger('click'); await flushPromises()
  const last = calls(f, 'GET', '/api/telemetry').at(-1)![0]
  expect(last).toContain('days=30')
  expect(last).toContain('agent=hermes')
  await w.findAll('button').find(b => b.text() === 'Clear filters')!.trigger('click'); await flushPromises()
  expect(calls(f, 'GET', '/api/telemetry').at(-1)![0]).toBe('/api/telemetry?days=30')
  w.unmount()
})

it('says so when there is nothing yet and explains a refused read', async () => {
  stubFetch(() => ({ status: 403, body: { detail: 'forbidden' } }))
  const refused = mount(TelemetryView); await flushPromises()
  expect(refused.get('[role="alert"]').text()).toContain('Operator sign-in is required')
  refused.unmount()
  stubFetch(url => url.startsWith('/api/telemetry') ? { body: body({ jobs: [], models: [], by_kind: [], activity: [], velocity: [], by_assignee: [], by_status: [], by_tier: [] }) } : undefined)
  const empty = mount(TelemetryView); await flushPromises()
  expect(empty.text()).toContain('No approved plans yet')
  expect(empty.text()).toContain('No runs in this period')
  expect(empty.text()).toContain('Nothing has finished yet')
  empty.unmount()
})
