import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RouteAdvice from '@/components/RouteAdvice.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

it('lists advice per story, marks warnings, and says nothing is blocked', async () => {
  const f = stubFetch(url => url === '/api/models/advice?project_id=7' ? { body: { advice: [
    { key: 'a', level: 'warn', text: 'acme/weak:free has succeeded on only 25% of 12 implement runs here; consider another route.' },
    { key: 'c', level: 'info', text: 'acme/x is unproven for docs work here (0 runs) and this story is high risk.' }] } } : undefined)
  const w = mount(RouteAdvice, { props: { projectId: 7, revision: 1 } }); await flushPromises()
  const text = w.get('[data-testid="route-advice"]').text()
  expect(text).toContain('nothing is blocked')
  expect(text).toContain('only 25% of 12 implement runs')
  expect(w.findAll('li.notice-warn')).toHaveLength(1)
  expect(calls(f, 'GET', '/api/models/advice')).toHaveLength(1)
  w.unmount()
})

it('shows nothing when there is no advice or it cannot be read', async () => {
  stubFetch(() => ({ body: { advice: [] } }))
  const none = mount(RouteAdvice, { props: { projectId: 7 } }); await flushPromises()
  expect(none.find('[data-testid="route-advice"]').exists()).toBe(false)
  none.unmount()
  stubFetch(() => ({ status: 500, body: { detail: 'boom' } }))
  const failed = mount(RouteAdvice, { props: { projectId: 7 } }); await flushPromises()
  expect(failed.find('[data-testid="route-advice"]').exists()).toBe(false)
  failed.unmount()
})
