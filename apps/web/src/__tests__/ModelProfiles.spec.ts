import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ModelProfiles from '@/components/ModelProfiles.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

const model = (over: Record<string, unknown> = {}) => ({
  id: 'google/gemma-4-31b-it:free', name: 'Gemma', free: true, platform: 'OpenRouter', agents: ['hermes'], status: null, in_catalog: true, in_snapshot: true,
  context: 262144, tools: true, structured: true, reasoning: false, inputs: ['text'], price_in: 0, price_out: 0,
  observed: { runs: 12, success_rate: 0.75, median_seconds: 95, tokens: 1000, cost_usd: 0, served_instead_of_requested: 0, proven: true },
  kinds: [{ kind: 'implement', runs: 12, success_rate: 0.75, first_pass: 8, proven: true }, { kind: 'docs', runs: 3, success_rate: 1, first_pass: 3, proven: false }],
  notes: [], ...over,
})
const profiles = (models: unknown[] = [model()], over: Record<string, unknown> = {}) => ({
  generated_at: 1, days: 90, proven_runs: 10, stale_days: 90, stale_notes: 0, snapshot: { fetched_at: 1_800_000_000, count: 463, free: 18 }, models, ...over,
})

it('shows observed success with unproven labelled, and the table folded away', async () => {
  stubFetch(url => url === '/api/models/profiles' ? { body: profiles([model(), model({ id: 'acme/new:free', observed: { runs: 2, success_rate: 1, median_seconds: 10, tokens: 5, cost_usd: 0, served_instead_of_requested: 0, proven: false }, kinds: [] })]) } : undefined)
  const w = mount(ModelProfiles); await flushPromises()
  const bars = w.get('[aria-label="Observed success by model"]').text()
  expect(bars).toContain('google/gemma-4-31b-it:free')
  expect(bars).toContain('acme/new:free (unproven)')
  expect(w.get('details[aria-label="Model profiles table"]').attributes('open')).toBeUndefined()
  const row = w.get('details[aria-label="Model profiles table"]').text()
  expect(row).toContain('implement')                                 // the kind it is proven for
  expect(row).toContain('tools, structured output')
  w.unmount()
})

it('refreshes only on a click, then shows what is new and what changed, and says nothing was changed', async () => {
  const f = stubFetch((url, init) => {
    if (url === '/api/models/profiles') return { body: profiles() }
    if (url === '/api/models/refresh' && init?.method === 'POST') return { body: { fetched_at: 1, count: 463, free: 18, diff: { new_free: ['acme/shiny:free'], no_longer_free: ['old/gone:free'], changed: [{ id: 'a/b', fields: ['context'] }] } } }
    return undefined
  })
  const w = mount(ModelProfiles); await flushPromises()
  expect(calls(f, 'POST', '/api/models/refresh')).toHaveLength(0)
  await w.findAll('button').find(b => b.text() === 'Refresh free models')!.trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/models/refresh')[0]![1]!.body))).toEqual({ confirm: true })
  const out = w.get('[data-testid="refresh-result"]').text()
  expect(out).toContain('Nothing was changed')
  expect(out).toContain('acme/shiny:free')
  expect(out).toContain('old/gone:free')
  expect(out).toContain('a/b (context)')
  w.unmount()
})

it('adds a note with its source and date, shows stale ones, and deletes', async () => {
  let notes: unknown[] = []
  const f = stubFetch((url, init) => {
    if (url === '/api/models/profiles') return { body: profiles([model({ notes })], { stale_notes: notes.length }) }
    if (url === '/api/models/notes' && init?.method === 'POST') { notes = [{ id: 'n1', model: 'google/gemma-4-31b-it:free', text: 'Fast on short docs.', source: 'my trial', date: '2026-01-01', stale: true }]; return { body: notes[0] } }
    if (url === '/api/models/notes/n1' && init?.method === 'DELETE') { notes = []; return { body: { deleted: 'n1' } } }
    return undefined
  })
  const w = mount(ModelProfiles); await flushPromises()
  const form = w.get('form.note-form')
  const inputs = form.findAll('input')
  await inputs[0]!.setValue('google/gemma-4-31b-it:free'); await inputs[1]!.setValue('Fast on short docs.'); await inputs[2]!.setValue('my trial')
  await form.trigger('submit'); await flushPromises()
  const sent = JSON.parse(String(calls(f, 'POST', '/api/models/notes')[0]![1]!.body))
  expect(sent).toMatchObject({ model: 'google/gemma-4-31b-it:free', text: 'Fast on short docs.', source: 'my trial' })
  expect(w.get('details[aria-label="Model notes"]').text()).toContain('my trial, 2026-01-01, stale')
  await w.get('details[aria-label="Model notes"] ul button').trigger('click'); await flushPromises()
  expect(calls(f, 'DELETE', '/api/models/notes/n1')).toHaveLength(1)
  expect(w.get('details[aria-label="Model notes"]').text()).toContain('No notes')
  w.unmount()
})

it('shows nothing when the profiles cannot be read, rather than a false claim', async () => {
  stubFetch(() => ({ status: 500, body: { detail: 'boom' } }))
  const w = mount(ModelProfiles); await flushPromises()
  expect(w.find('[aria-label="Models"]').exists()).toBe(false)
  w.unmount()
})

it('shows whether the weekly watch is on, what it last did, and links the card it left', async () => {
  const watch = (over: Record<string, unknown>) => ({ enabled: true, interval_days: 7, last_run: 1_800_000_000, last_ok: true, last_error: null, last_summary: '2 new free, 1 no longer free, 0 changed', last_card_id: 44, due: false, ...over })
  stubFetch(url => url === '/api/models/profiles' ? { body: profiles([model()], { watch: watch({}) }) } : undefined)
  const on = mount(ModelProfiles, { global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } } }); await flushPromises()
  const text = on.get('[data-testid="watch"]').text()
  expect(text).toContain('on, every 7 days')
  expect(text).toContain('2 new free, 1 no longer free')
  expect(on.get('[data-testid="watch"] a').attributes('href')).toBe('/tasks?card=44')
  on.unmount()
  stubFetch(url => url === '/api/models/profiles' ? { body: profiles([model()], { watch: watch({ enabled: false, last_run: null, last_card_id: null }) }) } : undefined)
  const off = mount(ModelProfiles); await flushPromises()
  expect(off.get('[data-testid="watch"]').text()).toContain('off.')
  expect(off.get('[data-testid="watch"]').text()).toContain('MAC_CONTROL_MODEL_WATCH_ENABLED')
  off.unmount()
  stubFetch(url => url === '/api/models/profiles' ? { body: profiles([model()], { watch: watch({ last_ok: false, last_error: 'The model list could not be read (OSError).', last_summary: null, last_card_id: null }) }) } : undefined)
  const failed = mount(ModelProfiles); await flushPromises()
  expect(failed.get('[data-testid="watch"]').text()).toContain('failed: The model list could not be read')
  failed.unmount()
})
