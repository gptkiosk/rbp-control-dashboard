import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ProjectTotals from '@/components/ProjectTotals.vue'
import type { ProjectTotals as Totals, TotalsBucket } from '@/lib/projects'

const bucket = (b: Partial<TotalsBucket> = {}): TotalsBucket => ({ runs: 0, succeeded: 0, duration_s: 0, input_tokens: 0, output_tokens: 0, cached_input_tokens: 0, api_usd: 0, api_unpriced: 0, actual_usd: 0, actual_unpriced: 0, ...b })
const totals: Totals = {
  ...bucket({ runs: 28, succeeded: 23, duration_s: 3813, input_tokens: 3164680, output_tokens: 260540, cached_input_tokens: 2389205, api_usd: 4.21, actual_usd: 0.31 }),
  planning: bucket({ runs: 10, duration_s: 2467 }), stories: bucket({ runs: 18, duration_s: 1346, actual_usd: 0.31 }), elapsed_s: 300000,
  models: [
    { ...bucket({ runs: 15, succeeded: 13, duration_s: 1550, input_tokens: 2394294, output_tokens: 60912, api_usd: 3.6 }), agent: 'codex', model: 'gpt-6.1-sol', billed: 'membership', model_derived: true },
    { ...bucket({ runs: 2, succeeded: 2, duration_s: 172, api_usd: 0.31, actual_usd: 0.31 }), agent: 'hermes', model: 'google/gemini-2.5-flash', billed: 'api', model_derived: false },
  ],
  media: { images: 8, estimate_usd: 0.96, unpriced: 0 }, total_api_usd: 5.17, total_actual_usd: 1.27, billing_note: 'Estimates, not invoices.',
}

it('shows time, tokens and both costs, says what membership covered, and lists each model with how it was billed', () => {
  const w = mount(ProjectTotals, { props: { totals, complete: true } })
  expect(w.text()).toContain('Project totals')
  expect(w.get('[data-testid=totals-actual]').text()).toBe('$1.2700')
  expect(w.get('[data-testid=totals-api]').text()).toBe('$5.1700')
  expect(w.text()).toContain('$3.9000 covered by membership or free models')
  expect(w.get('[data-testid=totals-media]').text()).toContain('8 generated images')
  const rows = w.get('[data-testid=totals-models]').text()
  expect(rows).toContain('codex · gpt-6.1-sol (derived)')
  expect(rows).toContain('Membership')
  expect(rows).toContain('(13 ok)')
  expect(w.find('[data-testid=totals-unpriced]').exists()).toBe(false)
})

it('calls a running project totals so far and counts what has no rate', () => {
  const w = mount(ProjectTotals, { props: { totals: { ...totals, api_unpriced: 2 } } })
  expect(w.text()).toContain('Totals so far')
  expect(w.get('[data-testid=totals-unpriced]').text()).toContain('2 items have no published rate')
})
