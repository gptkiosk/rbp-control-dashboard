import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import BriefAmendments from '@/components/BriefAmendments.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

it('lists amendments and adds one without touching the approved plan', async () => {
  const f = stubFetch((url, init) => url === '/api/projects/7/amendments' && init?.method === 'POST'
    ? { body: { id: 7, amendments: [{ id: 1, text: 'Old.', actor: 'op', created_at: 1 }, { id: 2, text: 'No button eyes.', actor: 'op', created_at: 2 }] } } : undefined)
  const w = mount(BriefAmendments, { props: { projectId: 7, amendments: [{ id: 1, text: 'Old.', actor: 'op', created_at: 1 }] } })
  expect(w.findAll('li')).toHaveLength(1)
  expect(w.get('[data-action="amend"]').attributes('disabled')).toBeDefined()
  await w.get('[data-test="amend-text"]').setValue('No button eyes.')
  await w.get('[data-action="amend"]').trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/projects/7/amendments')[0]![1]?.body))).toEqual({ text: 'No button eyes.' })
  expect(w.emitted('updated')).toHaveLength(1)
  expect(w.text()).toContain('Stories that start from now on follow it.')
  w.unmount()
})
