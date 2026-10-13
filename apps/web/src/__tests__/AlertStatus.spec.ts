import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AlertStatus from '@/components/AlertStatus.vue'
import { stubFetch } from './helpers'
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
it('shows delivery problems and acknowledges review without sending again', async () => {
  let reviewed: number | null = null
  const fetch = stubFetch((url, init) => {
    if (init?.method === 'POST') { reviewed=1100; return {body:{ok:true}} }
    return {body:{enabled:true,delivery_enabled:true,destination:'discord:123456789012345678',checked_at:1000,error:null,attention:reviewed ? 0 : 1,pending:0,events:[{id:'a'.repeat(32),message:'[MCD] Run failed',status:'uncertain',created_at:1000,sent_at:null,error:'Check Discord before resending.',reviewed_at:reviewed}]}}
  })
  const w=mount(AlertStatus); await flushPromises()
  expect(w.text()).toContain('Discord delivery enabled')
  expect(w.text()).toContain('needs delivery review')
  await w.get('button').trigger('click'); await flushPromises()
  expect(w.text()).toContain('Reviewed')
  expect(w.find('button').exists()).toBe(false)
  expect(fetch.mock.calls.filter(([,init]) => init?.method==='POST').map(([url]) => url)).toEqual(['/api/alerts/'+'a'.repeat(32)+'/acknowledge'])
  w.unmount()
})
it('shows paused delivery and a readable loading error', async () => {
  stubFetch(() => ({status:500,body:{detail:'Status unavailable'}}))
  const w=mount(AlertStatus); await flushPromises()
  expect(w.text()).toContain('Delivery paused')
  expect(w.text()).toContain('Status unavailable')
  w.unmount()
})
