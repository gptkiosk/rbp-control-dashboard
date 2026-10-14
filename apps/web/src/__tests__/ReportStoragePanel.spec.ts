import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ReportStoragePanel from '@/components/ReportStoragePanel.vue'
import { stubFetch, calls, headerOf } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const storage = { sources: [
  { id: 'ops', root: '/srv/dashboard/runtime/reports', mode: 'default', state: 'unavailable', available: false, error: null },
  { id: 'hermes', root: '', mode: 'disabled', state: 'unavailable', available: false, error: null },
], allowed_roots: ['/srv/dashboard/output'], error: null }

it('shows host states and saves guarded host settings separately from preferences', async () => {
  const f = stubFetch(() => ({ body: storage }))
  const w = mount(ReportStoragePanel); await flushPromises()
  expect(w.text()).toContain('default · unavailable')
  expect(w.text()).toContain('/srv/dashboard/output')
  expect(w.text()).toContain('Reports are read-only')
  await w.findAll('input')[0]!.setValue('/srv/dashboard/output')
  await w.get('form').trigger('submit'); await flushPromises()
  const [url, init] = calls(f, 'PUT', '/api/report-storage')[0]!
  expect(url).toBe('/api/report-storage')
  expect(JSON.parse(init!.body as string)).toEqual({ ops: '/srv/dashboard/output', hermes: '', reset: false })
  expect(headerOf(init, 'X-Mac-Control')).toBe('1')
  expect(w.emitted('changed')).toHaveLength(1)
  await w.findAll('button')[1]!.trigger('click'); await flushPromises()
  expect(JSON.parse(calls(f, 'PUT', '/api/report-storage')[1]![1]!.body as string).reset).toBe(true)
  w.unmount()
})

it('explains operator access and shows sanitized save failures', async () => {
  stubFetch(() => ({ status: 403, body: { detail: 'Operator sign-in is required.' } }))
  const denied = mount(ReportStoragePanel); await flushPromises()
  expect(denied.text()).toContain('Operator sign-in is required')
  expect(denied.find('form').exists()).toBe(false)
  denied.unmount()
  stubFetch((url, init) => init?.method === 'PUT' ? { status: 422, body: { detail: 'Use an approved local folder.' } } : { body: storage })
  const w = mount(ReportStoragePanel); await flushPromises()
  await w.get('form').trigger('submit'); await flushPromises()
  expect(w.text()).toContain('Use an approved local folder.')
  expect(w.emitted('changed')).toBeUndefined()
  w.unmount()
})
