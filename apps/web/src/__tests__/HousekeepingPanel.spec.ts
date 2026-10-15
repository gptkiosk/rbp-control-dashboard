import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import HousekeepingPanel from '@/components/HousekeepingPanel.vue'
import { stubFetch, calls } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

const finding = (id: string, kind = 'stale_approval_wait') => ({ id, kind, reason: `Run ${id} was left waiting. There is nothing left to decide.`, action: 'Mark the run cancelled (superseded).', evidence: {} })
const overview = (over: Record<string, unknown> = {}) => ({ findings: [], proposals: [], retention: { keep_newest_backups: 3, backup_min_age_days: 30 }, ...over })
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll('button').find(b => b.text() === text)

it('says there is nothing to tidy and states the retention rule', async () => {
  stubFetch(url => url === '/api/maintenance' ? { body: overview() } : undefined)
  const w = mount(HousekeepingPanel); await flushPromises()
  expect(w.text()).toContain('Nothing to tidy')
  expect(w.text()).toContain('newest 3')
  expect(w.text()).toContain('cannot change anything itself')
  w.unmount()
})

it('needs a selection and a confirmation, then sends exactly the selected ids', async () => {
  let applied = false
  const f = stubFetch((url, init) => {
    if (url === '/api/maintenance' && !init?.method) return { body: applied ? overview() : overview({ findings: [finding('stale_approval_wait:7'), finding('stale_approval_wait:81')] }) }
    if (url === '/api/maintenance/apply' && init?.method === 'POST') { applied = true; return { body: { outcomes: [{ id: 'stale_approval_wait:7', status: 'applied' }] } } }
    return undefined
  })
  const w = mount(HousekeepingPanel); await flushPromises()
  const go = button(w, 'Resolve selected')!
  expect(go.attributes('disabled')).toBeDefined()
  await w.get('[data-testid="finding-stale_approval_wait:7"]').setValue(true)
  expect(button(w, 'Resolve selected')!.attributes('disabled')).toBeDefined()        // still needs the confirmation
  await w.findAll('input[type="checkbox"]').at(-1)!.setValue(true)
  await button(w, 'Resolve selected')!.trigger('click'); await flushPromises()
  const post = calls(f, 'POST', '/api/maintenance/apply')
  expect(post).toHaveLength(1)
  expect(JSON.parse(String(post[0]![1]!.body))).toEqual({ finding_ids: ['stale_approval_wait:7'], confirm: true })
  expect(w.text()).toContain('1 resolved')
  w.unmount()
})

it('shows what Hermes proposed and acts only on the operator’s click', async () => {
  const proposal = { id: 3, created_by: 'hermes:op', summary: 'Three stale approval waits from 10-12 Oct.', finding_ids: ['stale_approval_wait:7'], status: 'pending', decided_by: null, result: null }
  const f = stubFetch((url, init) => {
    if (url === '/api/maintenance' && !init?.method) return { body: overview({ proposals: [proposal] }) }
    if (url === '/api/maintenance/proposals/3/reject' && init?.method === 'POST') return { body: { ...proposal, status: 'rejected' } }
    return undefined
  })
  const w = mount(HousekeepingPanel); await flushPromises()
  expect(w.text()).toContain('Three stale approval waits from 10-12 Oct.')
  expect(calls(f, 'POST', '/api/maintenance')).toHaveLength(0)                      // reading it changed nothing
  await button(w, 'Reject')!.trigger('click'); await flushPromises()
  expect(calls(f, 'POST', '/api/maintenance/proposals/3/reject')).toHaveLength(1)
  expect(w.text()).toContain('Nothing was changed')
  w.unmount()
})

it('reports a refused read without breaking the page', async () => {
  stubFetch(() => ({ status: 403, body: { detail: 'forbidden' } }))
  const w = mount(HousekeepingPanel); await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('Operator sign-in is required')
  w.unmount()
})

it('says whether after-hours cleanup is on, what it covers, and when it last ran', async () => {
  const body = (auto: Record<string, unknown>) => ({ findings: [], proposals: [], retention: { keep_newest_backups: 3, backup_min_age_days: 30 }, auto })
  stubFetch(url => url === '/api/maintenance' ? { body: body({ enabled: true, classes: ['stale_update_helper'], window: '01:00 to 05:00', last_run: 1_800_000_000, last_applied: 8, last_summary: '8 cleaned up, 0 skipped', in_window: false }) } : undefined)
  const on = mount(HousekeepingPanel); await flushPromises()
  const text = on.get('[data-testid="after-hours"]').text()
  expect(text).toContain('Finished update helper still loaded')
  expect(text).toContain('01:00 to 05:00')
  expect(text).toContain('8 cleaned up, 0 skipped')
  on.unmount()
  stubFetch(url => url === '/api/maintenance' ? { body: body({ enabled: false, classes: [], window: '01:00 to 05:00', last_run: null, last_applied: 0, last_summary: null, in_window: false }) } : undefined)
  const off = mount(HousekeepingPanel); await flushPromises()
  expect(off.get('[data-testid="after-hours"]').text()).toContain('off.')
  expect(off.get('[data-testid="after-hours"]').text()).toContain('MAC_CONTROL_HOUSEKEEPING_AUTO')
  off.unmount()
})
