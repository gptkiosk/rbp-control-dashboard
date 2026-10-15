import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import StandardsLine from '@/components/StandardsLine.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

const ok = (over: Record<string, unknown> = {}) => ({
  state: 'ok', path: 'docs/development/standards.md', property: 'upubhub', sha256: 'a'.repeat(64),
  areas: [{ area: 'Money', risk: 'high', route: 'foundation' }, { area: 'Docs', risk: 'low', route: 'free' }],
  checks: [{ touches: 'apps/api', run: 'pytest' }], warnings: [], message: '', ...over,
})

it('names the property, how many areas and checks, and a short hash of the file', async () => {
  const f = stubFetch(url => url === '/api/projects/7/standards' ? { body: ok() } : undefined)
  const w = mount(StandardsLine, { props: { projectId: 7, revision: 1 } }); await flushPromises()
  const text = w.get('[data-testid="standards"]').text()
  expect(text).toContain('upubhub')
  expect(text).toContain('2 areas')
  expect(text).toContain('1 check')
  expect(text).toContain('a'.repeat(12))
  expect(calls(f, 'GET', '/api/projects/7/standards')).toHaveLength(1)
  w.unmount()
})

it('warns, in plain words, when the file is missing or unreadable, and says planning goes on', async () => {
  stubFetch(() => ({ body: ok({ state: 'missing', property: null, sha256: null, areas: [], checks: [], message: 'No docs/development/standards.md in this project\'s working directory. Planning continues without standards.' }) }))
  const w = mount(StandardsLine, { props: { projectId: 7 } }); await flushPromises()
  expect(w.get('[role="status"]').text()).toContain('No standards in use.')
  expect(w.text()).toContain('Planning continues without standards.')
  w.unmount()
})

it('lists parser notes behind a fold and says nothing when the question cannot be asked', async () => {
  stubFetch(() => ({ body: ok({ warnings: ['No "Risk by area" table was found.'] }) }))
  const w = mount(StandardsLine, { props: { projectId: 7 } }); await flushPromises()
  expect(w.get('details summary').text()).toContain('1 note')
  expect(w.get('details').attributes('open')).toBeUndefined()
  w.unmount()
  stubFetch(() => ({ status: 500, body: { detail: 'boom' } }))
  const failed = mount(StandardsLine, { props: { projectId: 7 } }); await flushPromises()
  expect(failed.find('[data-testid="standards"]').exists()).toBe(false)
  failed.unmount()
})
