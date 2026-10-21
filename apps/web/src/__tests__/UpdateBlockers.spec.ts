import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import UpdateBlockers from '@/components/UpdateBlockers.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })
const stubs = { global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } } }

it('names the projects in progress and pauses them for the update in one confirmed step', async () => {
  let paused = false
  const f = stubFetch((url, init) => {
    if (url === '/api/app-updates/projects') return { body: paused ? { in_progress: [], paused_for_update: [{ id: 3, title: 'Doors', state: 'paused' }] } : { in_progress: [{ id: 3, title: 'Doors', state: 'active' }], paused_for_update: [] } }
    if (url === '/api/app-updates/pause-projects' && init?.method === 'POST') { paused = true; return { body: { paused: [{ id: 3, title: 'Doors', state: 'paused' }], in_progress: [] } } }
    return undefined
  })
  const w = mount(UpdateBlockers, { props: { blockers: ['1 project(s) in progress: pause them'] }, ...stubs }); await flushPromises()
  expect(w.text()).toContain('Projects in progress: Doors.')
  await w.get('[data-action="pause-projects"]').trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/app-updates/pause-projects')[0]![1]?.body))).toEqual({ confirm: true })
  expect(w.emitted('changed')).toHaveLength(1)
  expect(w.text()).toContain('Paused 1 project(s)')
  await w.setProps({ blockers: [] }); await flushPromises()
  expect(w.get('[data-testid="update-resume"]').text()).toContain('Paused for the update: Doors.')
  w.unmount()
})
