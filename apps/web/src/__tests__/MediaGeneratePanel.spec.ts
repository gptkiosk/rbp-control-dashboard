import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MediaGeneratePanel from '@/components/MediaGeneratePanel.vue'
import { calls, headerOf, stubFetch } from './helpers'
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = '' })
const plan = (endpoint: string, estimate: number | null) => ({ endpoint, estimate_usd: estimate })
const slot = (over: object) => ({ name: 'hero-still', kind: 'image', world: 'light', purpose: 'Anchor still', prompt: 'p', published: false, candidates: [], waiting_for_stills: [],
  plans: { draft: plan('fal-ai/nano-banana-2/edit', 0.08), standard: plan('fal-ai/nano-banana-2/edit', 0.08), premium: plan('fal-ai/nano-banana-pro/edit', 0.15) }, ...over })
const veo = { draft: plan('k', 0.35), standard: plan('v', null), premium: plan('v', null) }
function setup(keySaved = true, jobState = 'done') {
  const f = stubFetch((u, init) => {
    if (u === '/api/media/folders') return { body: { folders: [{ path: '/ws/site', name: 'site' }] } }
    if (u.startsWith('/api/media/slots')) return { body: { working_dir: '/ws/site', slots: [slot({ candidates: ['hero-still-1.png'] }), slot({ name: 'hero-clip', kind: 'video', plans: veo, waiting_for_stills: ['hero-still'] })] } }
    if (u === '/api/media/ledger') return { body: { runs: 3, done: 2, estimated_usd: 0.16, rows: [], note: 'Estimates are not invoices.' } }
    if (u === '/api/media/generate' && init?.method === 'POST') return { status: 202, body: { jobs: ['j1'], endpoint: 'e', estimate_usd_each: 0.08 } }
    if (u === '/api/media/jobs/j1') return { body: { id: 'j1', state: jobState, progress: 'queued at fal', slot: 'hero-still', error: jobState === 'failed' ? 'fal reported an error: content policy' : null, files: [] } }
    if (u === '/api/media/pick' && init?.method === 'POST') return { body: { copied: 'media/inbox/hero-still.png', next: 'python3 tools/media/media.py ingest hero-still' } }
  })
  return { f, w: mount(MediaGeneratePanel, { props: { keySaved } }) }
}
it('shows slots with the price for the chosen tier and keeps Generate off until spending is confirmed', async () => {
  const { w } = setup()
  await flushPromises()
  const row = w.get('[data-slot=hero-still]')
  expect(row.text()).toContain('about $0.08')
  await row.get('select').setValue('premium')
  expect(row.text()).toContain('about $0.15')
  expect(w.get('[data-slot=hero-clip]').text()).toContain('price not listed')
  expect(w.get('[data-slot=hero-clip]').text()).toContain('Waiting for the approved still')
  const go = row.findAll('button').find(b => b.text() === 'Generate')!
  expect(go.attributes('disabled')).toBeDefined()
  await w.get('input[type=checkbox]').setValue(true)
  expect(go.attributes('disabled')).toBeUndefined()
  expect(w.get('[data-slot=hero-clip]').findAll('button').find(b => b.text() === 'Generate')!.attributes('disabled')).toBeDefined()
  w.unmount()
})
it('sends the explicit confirmation and the chosen tier and count, then follows the job', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const { w, f } = setup()
  await flushPromises()
  await w.get('input[type=checkbox]').setValue(true)
  const row = w.get('[data-slot=hero-still]')
  await row.get('select').setValue('draft')
  await row.get('input[type=number]').setValue(2)
  await row.findAll('button').find(b => b.text() === 'Generate')!.trigger('click')
  await flushPromises()
  const call = calls(f, 'POST', '/api/media/generate')[0]!
  expect(headerOf(call[1], 'X-Mac-Control')).toBe('1')
  expect(JSON.parse(String(call[1]?.body))).toEqual({ working_dir: '/ws/site', slot: 'hero-still', tier: 'draft', count: 2, confirm_spend: true })
  expect(w.text()).toContain('hero-still: queued')
  await vi.advanceTimersByTimeAsync(3000)
  await flushPromises()
  expect(w.text()).toContain('hero-still: done')
  expect(w.text()).toContain('2 of 3 runs finished')
  w.unmount()
})
it('reports a failed run plainly and picks a candidate without running anything', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const { w, f } = setup(true, 'failed')
  await flushPromises()
  await w.get('input[type=checkbox]').setValue(true)
  await w.get('[data-slot=hero-still]').findAll('button').find(b => b.text() === 'Generate')!.trigger('click')
  await flushPromises(); await vi.advanceTimersByTimeAsync(3000); await flushPromises()
  expect(w.text()).toContain('content policy')
  await w.get('button[aria-label="Use hero-still-1.png"]').trigger('click')
  await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/media/pick')[0]![1]?.body))).toEqual({ working_dir: '/ws/site', slot: 'hero-still', candidate: 'hero-still-1.png' })
  expect(w.text()).toContain('python3 tools/media/media.py ingest hero-still')
  w.unmount()
})
it('asks for the key first when none is saved', async () => {
  const { w } = setup(false)
  await flushPromises()
  expect(w.text()).toContain('Save your fal key first')
  await w.get('input[type=checkbox]').setValue(true)
  expect(w.get('[data-slot=hero-still]').findAll('button').find(b => b.text() === 'Generate')!.attributes('disabled')).toBeDefined()
  w.unmount()
})
function batchSetup() {
  const slots = [
    slot({ name: 'a-still' }),                                              // ready
    slot({ name: 'b-card', plans: { draft: plan('d', 0.08), standard: plan('s', 0.08), premium: plan('p', 0.15) } }),   // ready
    slot({ name: 'c-done', published: true }),                              // already published
    slot({ name: 'd-picked', candidates: ['d-picked-1.png'] }),             // a candidate waits for your choice
    slot({ name: 'e-clip', kind: 'video', plans: veo, waiting_for_stills: ['a-still'] }),   // needs its still first
    slot({ name: 'f-clip', kind: 'video', plans: { draft: plan('k', 0.35), standard: plan('v', null), premium: plan('v', null) } }),   // ready, price unknown at standard
  ]
  const f = stubFetch((u, init) => {
    if (u === '/api/media/folders') return { body: { folders: [{ path: '/ws/site', name: 'site' }] } }
    if (u.startsWith('/api/media/slots')) return { body: { working_dir: '/ws/site', slots } }
    if (u === '/api/media/ledger') return { body: { runs: 0, done: 0, estimated_usd: 0, rows: [], note: 'n' } }
    if (u === '/api/media/generate' && init?.method === 'POST') return { status: 202, body: { jobs: ['j' + Math.random()], endpoint: 'e', estimate_usd_each: 0.08 } }
    if (u.startsWith('/api/media/jobs/')) return { body: { id: 'x', state: 'queued', progress: '', slot: 'a-still', error: null, files: [] } }
  })
  return { f, w: mount(MediaGeneratePanel, { props: { keySaved: true } }) }
}
it('counts only what is still missing and shows the batch price, flagging models with no listed price', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const { w } = batchSetup()
  await flushPromises()
  const box = w.get('[data-testid=batch]')
  expect(box.text()).toContain('3 ready')
  expect(box.text()).toContain('1 more need an approved still first')
  expect(box.text()).toContain('about $0.16 plus 1 with no listed price')
  await box.get('select').setValue('draft')
  expect(box.text()).toContain('about $0.51')                                  // 0.08 + 0.08 + 0.35
  expect(box.findAll('button').find(b => b.text() === 'Generate all missing')!.attributes('disabled')).toBeDefined()   // spending not acknowledged
  w.unmount()
})
it('asks once with the total, then makes one request per missing slot with the chosen tier', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const { w, f } = batchSetup()
  await flushPromises()
  await w.get('input[type=checkbox]').setValue(true)
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
  const go = w.get('[data-testid=batch]').findAll('button').find(b => b.text() === 'Generate all missing')!
  await w.get('[data-testid=batch] select').setValue('premium')
  await go.trigger('click'); await flushPromises()
  expect(calls(f, 'POST', '/api/media/generate')).toHaveLength(0)             // cancelled: nothing was sent
  expect(confirmSpy.mock.calls[0]![0]).toContain('at the premium tier')
  await go.trigger('click'); await flushPromises()
  const sent = calls(f, 'POST', '/api/media/generate').map(c => JSON.parse(String(c[1]?.body)))
  expect(sent.map(b => b.slot)).toEqual(['a-still', 'b-card', 'f-clip'])
  expect(sent.every(b => b.tier === 'premium' && b.count === 1 && b.confirm_spend === true && b.working_dir === '/ws/site')).toBe(true)
  confirmSpy.mockRestore(); w.unmount()
})
it('shows each candidate as a thumbnail or video you can open, from the operator-only viewer', async () => {
  const f = stubFetch((u, init) => {
    if (u === '/api/media/folders') return { body: { folders: [{ path: '/ws/site', name: 'site' }] } }
    if (u.startsWith('/api/media/slots')) return { body: { working_dir: '/ws/site', slots: [slot({ name: 'hero-still', candidates: ['hero-still-1.png', 'hero-still-2.png'] }), slot({ name: 'hero', kind: 'video', plans: veo, candidates: ['hero-1.mp4'] })] } }
    if (u === '/api/media/ledger') return { body: { runs: 0, done: 0, estimated_usd: 0, rows: [], note: 'n' } }
    void init
  })
  const w = mount(MediaGeneratePanel, { props: { keySaved: true } })
  await flushPromises()
  const imgs = w.get('[data-slot=hero-still]').findAll('img')
  expect(imgs.map(i => i.attributes('src'))).toEqual([
    '/api/media/candidate?working_dir=%2Fws%2Fsite&name=hero-still-1.png',
    '/api/media/candidate?working_dir=%2Fws%2Fsite&name=hero-still-2.png',
  ])
  expect(w.get('[data-slot=hero-still] a').attributes('href')).toBe(imgs[0]!.attributes('src'))        // opens full size
  expect(w.get('[data-slot=hero-still] a').attributes('target')).toBe('_blank')
  const video = w.get('[data-slot=hero] video')
  expect(video.attributes('src')).toBe('/api/media/candidate?working_dir=%2Fws%2Fsite&name=hero-1.mp4')
  expect(video.attributes('controls')).toBeDefined()
  expect(w.get('[data-slot=hero]').findAll('img')).toHaveLength(0)
  void f
  w.unmount()
})
