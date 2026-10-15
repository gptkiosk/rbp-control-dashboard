import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CoordinatorScorecard from '@/components/CoordinatorScorecard.vue'
import { stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

const group = (label: string, over: Record<string, unknown> = {}) => ({ label, plans: 2, score: 0.9, edits_per_plan: 3, first_pass_rate: 0.67, estimate_ratio: 1.2, stories_done: 6, ...over })
const body = (over: Record<string, unknown> = {}) => ({
  generated_at: 1, days: 90, briefs: 8, note: 'Scores check the plan, not the model.',
  by_planner: [group('claude · claude-opus-5-5')], by_wording: [group('v2'), group('v2+custom', { plans: 1, score: 0.7, edits_per_plan: null, first_pass_rate: null })],
  plans: [{ project_id: 7, revision: 2, title: 'Ship it', approved_at: 1_800_000_000, planner: 'claude · claude-opus-5-5', delegator: 'hermes · free', wording: { label: 'v2', sha: 'abc' }, score: 0.9, failed: ['acceptance'], returned_score: 0.8,
    edits: { added: 1, removed: 0, changed: 2, total: 3, nodes_returned: 4 }, stories: 5, done: 3, first_pass: 2, failed_stories: 0, estimate_ratio: 1.2 }], ...over,
})

it('shows plan score by planner and by wording with edits and first pass, and the numbers folded away', async () => {
  stubFetch(url => url === '/api/coordinator/scorecard' ? { body: body() } : undefined)
  const w = mount(CoordinatorScorecard); await flushPromises()
  const text = w.get('[aria-label="Coordinator scorecard"]').text()
  expect(text).toContain('Plan score by planner')
  expect(text).toContain('claude · claude-opus-5-5')
  expect(text).toContain('90')
  expect(text).toContain('3 edits each')
  expect(text).toContain('v2+custom')
  expect(text).toContain('8 fixed briefs')
  expect(w.get('details[aria-label="Scored plans table"]').attributes('open')).toBeUndefined()
  const table = w.get('details[aria-label="Scored plans table"]').text()
  expect(table).toContain('Ship it')
  expect(table).toContain('acceptance')
  expect(table).toContain('3 of 5')
  w.unmount()
})

it('says so when there are no approved plans yet, and shows nothing when it cannot be read', async () => {
  stubFetch(() => ({ body: body({ plans: [], by_planner: [], by_wording: [] }) }))
  const w = mount(CoordinatorScorecard); await flushPromises()
  expect(w.text()).toContain('No approved plans in this period yet')
  w.unmount()
  stubFetch(() => ({ status: 500, body: { detail: 'boom' } }))
  const failed = mount(CoordinatorScorecard); await flushPromises()
  expect(failed.find('[aria-label="Coordinator scorecard"]').exists()).toBe(false)
  failed.unmount()
})
