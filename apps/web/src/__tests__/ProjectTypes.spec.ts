import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ProjectTypePicker from '@/components/ProjectTypePicker.vue'
import PlanChecks from '@/components/PlanChecks.vue'
import { calls, stubFetch } from './helpers'
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = '' })
const types = [
  { id: 'web-app', label: 'Web app (containerized, deployed to a cloud service)', summary: 'A hosted web service.', failure_points: ['x'], human_signoffs: ['y'], visual_checks: '' },
  { id: 'website-property', label: 'Website property (static site with generated media)', summary: 'A static site with generated media.', failure_points: ['x'], human_signoffs: ['y'], visual_checks: '' },
]
it('offers the types, suggests one for a matching brief and uses it on request', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  const f = stubFetch(u => (u === '/api/project-types' ? { body: { types } } : u === '/api/project-types/suggest' ? { body: { suggested: 'website-property' } } : undefined))
  const w = mount(ProjectTypePicker, { props: { modelValue: null, text: '' } })
  await flushPromises()
  expect(w.findAll('option').map(o => o.text())).toEqual(['General (no template)', types[0]!.label, types[1]!.label])
  await w.setProps({ text: 'A static website with dark mode, custom art and animation transitions' })
  await vi.advanceTimersByTimeAsync(700); await flushPromises()
  expect(w.text()).toContain('This looks like a Website property')
  expect(JSON.parse(String(calls(f, 'POST', '/api/project-types/suggest')[0]![1]?.body)).text).toContain('dark mode')
  await w.get('button').trigger('click')
  expect(w.emitted('update:modelValue')![0]).toEqual(['website-property'])
  await w.get('select').setValue('web-app')
  expect(w.emitted('update:modelValue')![1]).toEqual(['web-app'])
  w.unmount()
})
it('does not suggest once a type is chosen and shows nothing when the types cannot be loaded', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  const f = stubFetch(u => (u === '/api/project-types' ? { body: { types } } : { body: { suggested: 'web-app' } }))
  const w = mount(ProjectTypePicker, { props: { modelValue: 'web-app', text: '' } })
  await flushPromises()
  await w.setProps({ text: 'A subscription service on Cloud Run with Stripe payments for members' })
  await vi.advanceTimersByTimeAsync(700); await flushPromises()
  expect(calls(f, 'POST', '/api/project-types/suggest')).toHaveLength(0)
  expect(w.text()).toContain('A hosted web service.')
  w.unmount()
  stubFetch(() => undefined)
  const none = mount(ProjectTypePicker, { props: { modelValue: null, text: '' } })
  await flushPromises()
  expect(none.find('select').exists()).toBe(false)
  none.unmount()
})
it('lists what a plan is missing for its type, or says it has what the type expects', async () => {
  stubFetch(u => (u === '/api/projects/7/checks' ? { body: { project_type: 'website-property', findings: [{ id: 'preview-checkpoint', severity: 'warn', message: 'No agent preview checkpoint story.', stories: [] }, { id: 'container-after-pages', severity: 'warn', message: 'The container story is planned before the pages.', stories: ['s7'] }] } } : u === '/api/projects/8/checks' ? { body: { project_type: 'web-app', findings: [] } } : u === '/api/projects/9/checks' ? { body: { project_type: null, findings: [] } } : undefined))
  const w = mount(PlanChecks, { props: { projectId: 7, revision: 2 } })
  await flushPromises()
  expect(w.get('[data-check=preview-checkpoint]').text()).toContain('No agent preview checkpoint story.')
  expect(w.get('[data-check=container-after-pages]').text()).toContain('stories: s7')
  expect(w.text()).toContain('Nothing here blocks you')
  const ok = mount(PlanChecks, { props: { projectId: 8, revision: 1 } })
  await flushPromises()
  expect(ok.text()).toContain('The plan has what this project type expects')
  const untyped = mount(PlanChecks, { props: { projectId: 9, revision: 1 } })
  await flushPromises()
  expect(untyped.find('section').exists()).toBe(false)           // no type, no card
  w.unmount(); ok.unmount(); untyped.unmount()
})
