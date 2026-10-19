import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MediaGeneratePanel from '@/components/MediaGeneratePanel.vue'
import { calls, stubFetch } from './helpers'
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = '' })
const plan = (endpoint: string, estimate: number | null) => ({ endpoint, estimate_usd: estimate })
const img = { draft: plan('d', 0.08), standard: plan('s', 0.08), premium: plan('p', 0.15) }
const veo = { draft: plan('k', 0.35), standard: plan('v', null), premium: plan('v', null) }
const slot = (over: object) => ({ name: 'a', kind: 'image', world: 'light', purpose: 'Anchor still', prompt: 'p', published: false, inbox: null, candidates: [] as string[], waiting_for_stills: [] as string[], plans: img, ...over })
type S = ReturnType<typeof slot>
function setup(getSlots: () => S[], extra: (u: string, init?: RequestInit) => { status?: number; body: unknown } | undefined = () => undefined, keySaved = true, defaultTiers?: Record<string, string>) {
  const f = stubFetch((u, init) => {
    if (u === '/api/media/folders') return { body: { folders: [{ path: '/ws/site', name: 'site' }] } }
    if (u.startsWith('/api/media/slots')) return { body: { working_dir: '/ws/site', slots: getSlots(), cost: { spent_usd: 1.1, spent_runs: 3 }, ...(defaultTiers ? { default_tiers: defaultTiers } : {}) } }
    if (u === '/api/media/ledger') return { body: { runs: 3, done: 2, estimated_usd: 0.16, unpriced: 0, repeats: 0, repeat_usd: 0, rows: [], note: 'Estimates are not invoices.' } }
    return extra(u, init)
  })
  return { f, w: mount(MediaGeneratePanel, { props: { keySaved } }) }
}
const buttons = (w: ReturnType<typeof mount>, label: string, within = '') => (within ? w.get(within) : w).findAll('button').filter(b => b.text() === label)

it('groups slots by what needs you and keeps Generate off until spending is acknowledged', async () => {
  const { w } = setup(() => [slot({ name: 'todo-a' }), slot({ name: 'review-b', candidates: ['review-b-1.png'] }), slot({ name: 'done-c', published: true }), slot({ name: 'clip-d', kind: 'video', plans: veo, waiting_for_stills: ['todo-a'] })])
  await flushPromises()
  expect(w.get('[data-testid=summary]').text()).toContain('1 published · 0 skipped · 1 waiting for your decision · 2 not made yet')
  const todo = w.get('[data-slot=todo-a]')
  expect(todo.text()).toContain('about $0.08')
  await todo.get('select').setValue('premium')
  expect(todo.text()).toContain('about $0.15')
  expect(w.get('[data-slot=clip-d]').text()).toContain('price not listed')
  expect(w.get('[data-slot=clip-d]').text()).toContain('Waiting for the approved still')
  const go = buttons(w, 'Generate', '[data-slot=todo-a]')[0]!
  expect(go.attributes('disabled')).toBeUndefined()                                         // never a silent dead button: pressing it says what is missing
  await go.trigger('click'); await flushPromises()
  expect(w.get('[data-note=todo-a]').text()).toContain('Tick "I understand each run spends')
  await w.get('input[type=checkbox]').setValue(true)
  expect(go.attributes('disabled')).toBeUndefined()
  expect(buttons(w, 'Generate', '[data-slot=clip-d]')[0]!.attributes('disabled')).toBeDefined()
  w.unmount()
})
it('keeps a published slot out of the way: no Generate until you ask to regenerate it', async () => {
  const { w } = setup(() => [slot({ name: 'done-c', published: true })])
  await flushPromises()
  const row = w.get('[data-slot=done-c]')
  expect(row.text()).toContain('✓ published')
  expect(buttons(w, 'Generate', '[data-slot=done-c]')).toHaveLength(0)
  await w.get('input[type=checkbox]').setValue(true)
  await w.get('button[aria-label="Regenerate done-c"]').trigger('click')
  expect(buttons(w, 'Generate', '[data-slot=done-c]')).toHaveLength(1)
  w.unmount()
})
it('sends the explicit confirmation, tier and count, shows each result as soon as its job finishes, and reports a failure beside the slot', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  let made = false
  const { w, f } = setup(
    () => [slot({ name: 'one', candidates: made ? ['one-1.png'] : [] }), slot({ name: 'two' })],
    (u, init) => {
      if (u === '/api/media/generate' && init?.method === 'POST') { const b = JSON.parse(String(init.body)); return { status: 202, body: { jobs: ['j-' + b.slot], endpoint: 'e', estimate_usd_each: 0.08 } } }
      if (u === '/api/media/jobs/j-one') { made = true; return { body: { id: 'j-one', state: 'done', progress: 'done', slot: 'one', error: null, files: [] } } }
      if (u === '/api/media/jobs/j-two') return { body: { id: 'j-two', state: 'running', progress: 'queued at fal', slot: 'two', error: null, files: [] } }
    },
  )
  await flushPromises()
  const ok = vi.spyOn(window, 'confirm').mockReturnValue(true)
  await w.get('input[type=checkbox]').setValue(true)
  for (const name of ['one', 'two']) {
    const row = w.get(`[data-slot=${name}]`)
    await row.get('select').setValue('draft')
    await row.get('input[type=number]').setValue(2)
    await buttons(w, 'Generate', `[data-slot=${name}]`)[0]!.trigger('click'); await flushPromises()
  }
  ok.mockRestore()
  const posted = calls(f, 'POST', '/api/media/generate').map(c => JSON.parse(String(c[1]?.body)))
  expect(posted[0]).toEqual({ working_dir: '/ws/site', slot: 'one', tier: 'draft', count: 2, confirm_spend: true })
  expect(w.text()).toContain('2 generating now')
  expect(w.get('[data-slot=two] [data-job=two]').text()).toContain('waiting to start')                         // progress sits under the slot's own button at once
  await vi.advanceTimersByTimeAsync(3000); await flushPromises()
  expect(w.get('[data-slot=one]').text()).toContain('one-1.png')                         // one finished: it is on screen while two is still running
  expect(w.text()).toContain('1 generating now')
  expect(w.get('[data-slot=two] [data-job=two]').text()).toContain('generating (queued at fal)')                  // progress sits under the slot's own button
  expect(w.find('[data-slot=two] [data-job=two] .spinner').exists()).toBe(true)
  expect(buttons(w, 'Generating…', '[data-slot=two]')[0]!.attributes('disabled')).toBeDefined()               // and the button itself says it is working
  expect(buttons(w, 'Accept and publish', '[data-slot=one]')).toHaveLength(1)
  w.unmount()
})
it('accepts a candidate in one click: it is chosen and published, and a refusal is explained beside the slot', async () => {
  let published = false
  let refuse = true
  const { w, f } = setup(
    () => [slot({ name: 'hero', candidates: ['hero-1.png', 'hero-2.png'], published })],
    (u, init) => {
      if (u === '/api/media/pick' && init?.method === 'POST') return { body: { copied: 'media/inbox/hero.png', next: '' } }
      if (u === '/api/media/publish' && init?.method === 'POST') {
        if (refuse) return { status: 422, body: { detail: 'hero.png is 640px wide and this slot needs at least 960px (a draft is too small to publish).' } }
        published = true; return { body: { published: 'hero', files: [{ path: 'assets/img/hero.jpg', bytes: 204800 }] } }
      }
    },
  )
  await flushPromises()
  await w.get('button[aria-label="Accept hero-2.png"]').trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/media/pick')[0]![1]?.body))).toEqual({ working_dir: '/ws/site', slot: 'hero', candidate: 'hero-2.png' })
  expect(w.get('[data-note=hero]').text()).toContain('too small to publish')
  expect(w.get('[data-note=hero]').attributes('role')).toBe('alert')
  refuse = false
  await w.get('button[aria-label="Accept hero-2.png"]').trigger('click'); await flushPromises()
  expect(calls(f, 'POST', '/api/media/publish')).toHaveLength(2)
  expect(w.get('[data-slot=hero]').text()).toContain('✓ published')                       // it moves to the published group
  expect(w.text()).toContain('Published: assets/img/hero.jpg (200 KB)')
  w.unmount()
})
it('shows each candidate as a thumbnail or video from the operator-only viewer, and offers another when none is right', async () => {
  const { w } = setup(() => [slot({ name: 'hero-still', candidates: ['hero-still-1.png', 'hero-still-2.png'] }), slot({ name: 'hero', kind: 'video', plans: veo, candidates: ['hero-1.mp4'] })])
  await flushPromises()
  const imgs = w.get('[data-slot=hero-still]').findAll('img')
  expect(imgs.map(i => i.attributes('src'))).toEqual([
    '/api/media/candidate?working_dir=%2Fws%2Fsite&name=hero-still-1.png',
    '/api/media/candidate?working_dir=%2Fws%2Fsite&name=hero-still-2.png',
  ])
  expect(w.get('[data-slot=hero-still] a').attributes('target')).toBe('_blank')
  const video = w.get('[data-slot=hero] video')
  expect(video.attributes('src')).toBe('/api/media/candidate?working_dir=%2Fws%2Fsite&name=hero-1.mp4')
  expect(video.attributes('controls')).toBeDefined()
  expect(w.get('[data-slot=hero]').findAll('img')).toHaveLength(0)
  expect(buttons(w, 'Generate', '[data-slot=hero-still]')).toHaveLength(0)
  expect(w.find('button[aria-label="None of these for hero-still"]').exists()).toBe(true)
  w.unmount()
})
function batchSetup() {
  return setup(
    () => [
      slot({ name: 'a-still' }), slot({ name: 'b-card' }),                                             // ready
      slot({ name: 'c-done', published: true }),                                                       // published: never regenerated
      slot({ name: 'd-picked', candidates: ['d-picked-1.png'] }),                                      // waiting for your decision: not regenerated either
      slot({ name: 'e-clip', kind: 'video', plans: veo, waiting_for_stills: ['a-still'] }),            // needs its still first
      slot({ name: 'f-clip', kind: 'video', plans: { draft: plan('k', 0.35), standard: plan('v', null), premium: plan('v', null) } }),   // ready, price unknown at standard
    ],
    (u, init) => {
      if (u === '/api/media/generate' && init?.method === 'POST') return { status: 202, body: { jobs: ['j' + Math.random()], endpoint: 'e', estimate_usd_each: 0.08 } }
      if (u.startsWith('/api/media/jobs/')) return { body: { id: 'x', state: 'queued', progress: '', slot: 'a-still', error: null, files: [] } }
    },
  )
}
it('counts only what is not made yet and shows the batch price, flagging models with no listed price', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const { f, w } = batchSetup()
  await flushPromises()
  const box = w.get('[data-testid=batch]')
  expect(box.text()).toContain('3 ready')
  expect(box.text()).toContain('1 more need an approved still first')
  expect(box.text()).toContain('never regenerated here')
  expect(box.text()).toContain('about $0.16 plus 1 with no listed price')
  await box.get('select').setValue('draft')
  expect(box.text()).toContain('about $0.51')
  const all = buttons(w, 'Generate all missing', '[data-testid=batch]')[0]!
  expect(all.attributes('disabled')).toBeUndefined()
  await all.trigger('click'); await flushPromises()
  expect(w.text()).toContain('Tick "I understand each run spends')
  expect(calls(f, 'POST', '/api/media/generate')).toHaveLength(0)
  w.unmount()
})
it('asks once with the total, then makes one request per slot that is not made yet', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const { w, f } = batchSetup()
  await flushPromises()
  await w.get('input[type=checkbox]').setValue(true)
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
  const go = buttons(w, 'Generate all missing', '[data-testid=batch]')[0]!
  await w.get('[data-testid=batch] select').setValue('premium')
  await go.trigger('click'); await flushPromises()
  expect(calls(f, 'POST', '/api/media/generate')).toHaveLength(0)
  expect(confirmSpy.mock.calls[0]![0]).toContain('at the premium tier')
  await go.trigger('click'); await flushPromises()
  const sent = calls(f, 'POST', '/api/media/generate').map(c => JSON.parse(String(c[1]?.body)))
  expect(sent.map(b => b.slot)).toEqual(['a-still', 'b-card', 'f-clip'])                              // not the published, not the one awaiting a decision, not the one waiting for a still
  expect(sent.every(b => b.tier === 'premium' && b.count === 1 && b.confirm_spend === true && b.working_dir === '/ws/site')).toBe(true)
  confirmSpy.mockRestore(); w.unmount()
})
it('asks for the key first when none is saved', async () => {
  const { w } = setup(() => [slot({ name: 'a' })], () => undefined, false)
  await flushPromises()
  expect(w.text()).toContain('Add fal key in Settings')
  await w.get('input[type=checkbox]').setValue(true)
  expect(buttons(w, 'Generate', '[data-slot=a]')[0]!.attributes('disabled')).toBeDefined()
  w.unmount()
})
it('records skip, restore and none-of-these as decisions, and the skipped slot leaves the work list', async () => {
  let skipped = false
  const { w, f } = setup(
    () => [slot({ name: 'a', skipped }), slot({ name: 'b', candidates: ['b-1.png'] })],
    (u, init) => {
      if (u === '/api/media/decision' && init?.method === 'POST') { const b = JSON.parse(String(init.body)); if (b.slot === 'a') skipped = b.event === 'skip'; return { body: { slot: b.slot, skipped } } }
    },
  )
  await flushPromises()
  await w.get('button[aria-label="Skip a"]').trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/media/decision')[0]![1]?.body))).toEqual({ working_dir: '/ws/site', slot: 'a', event: 'skip' })
  expect(w.get('[data-testid=summary]').text()).toContain('1 skipped')
  expect(w.get('[data-slot=a]').text()).toContain('skipped, the site uses its fallback')
  expect(w.findAll('button').some(b => b.text() === 'Generate' && b.element.closest('[data-slot=a]'))).toBe(false)         // out of the work list
  await w.get('button[aria-label="Restore a"]').trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/media/decision')[1]![1]?.body)).event).toBe('unskip')
  await w.get('button[aria-label="None of these for b"]').trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/media/decision')[2]![1]?.body))).toEqual({ working_dir: '/ws/site', slot: 'b', event: 'reject' })
  expect(w.get('[data-slot=b]').text()).toContain('Make another below')
  w.unmount()
})
it('opened from a project it uses that folder without a picker, reads the key status itself, and says when every slot is decided', async () => {
  const f = stubFetch((u) => {
    if (u.startsWith('/api/media/slots')) return { body: { working_dir: '/ws/proj', slots: [slot({ name: 'a', published: true }), slot({ name: 'b', skipped: true })], summary: { published: 1, skipped: 1, pending: 0, total: 2, complete: true, text: 'Media: 1 of 2 slots published, 1 skipped.' } } }
    if (u === '/api/media/models') return { body: { provider: 'fal', fal_key_saved: true, models: [], key_rules: { preset: 'API', note: '', allowed_models: [] } } }
    if (u === '/api/media/ledger') return { body: { runs: 0, done: 0, estimated_usd: 0, rows: [], note: 'n' } }
  })
  const w = mount(MediaGeneratePanel, { props: { workingDir: '/ws/proj' } })
  await flushPromises()
  expect(w.find('select[aria-label="Project folder"]').exists()).toBe(false)
  expect(f.mock.calls.some(([u]) => u === '/api/media/folders')).toBe(false)
  expect(f.mock.calls.some(([u]) => String(u).includes('working_dir=%2Fws%2Fproj'))).toBe(true)
  expect(w.get('[data-testid=complete]').text()).toContain('Every slot is decided')
  expect(f.mock.calls.some(([u]) => u === '/api/media/models')).toBe(true)
  expect(w.text()).not.toContain('Save your fal key first')
  w.unmount()
})

it('starts each kind of slot on the tier its project type asks for: a website\'s clips on the cheapest', async () => {
  const { w } = setup(() => [slot({ name: 'a-still' }), slot({ name: 'b-clip', kind: 'video', plans: veo })], () => undefined, true, { image: 'standard', video: 'draft' })
  await flushPromises()
  expect((w.get('[data-slot=a-still] select').element as HTMLSelectElement).value).toBe('standard')
  expect((w.get('[data-slot=b-clip] select').element as HTMLSelectElement).value).toBe('draft')
  w.unmount()
})
it('does not pay for a slot twice by accident: the refusal is shown beside the slot with an explicit Another take', async () => {
  const ok = vi.spyOn(window, 'confirm').mockReturnValue(true)
  let takes = 0
  const { f, w } = setup(() => [slot({ name: 'x' })], (u, init) => {
    if (u === '/api/media/generate' && init?.method === 'POST') {
      const b = JSON.parse(String(init.body))
      if (!b.another_take) return { status: 409, body: { detail: 'x already has 1 generation waiting for your review, and they have already been paid for. Review, accept or reject them first, or choose Another take if you want to pay for more.' } }
      takes++; return { status: 202, body: { jobs: ['j-x'], endpoint: 'e', estimate_usd_each: 0.08 } }
    }
    if (u === '/api/media/jobs/j-x') return { body: { id: 'j-x', state: 'running', progress: 'queued', slot: 'x', error: null, files: [] } }
  })
  await flushPromises()
  await w.get('input[type=checkbox]').setValue(true)
  await buttons(w, 'Generate', '[data-slot=x]')[0]!.trigger('click'); await flushPromises()
  expect(w.get('[data-note=x]').text()).toContain('already been paid for')
  expect(takes).toBe(0)
  await w.get('button[aria-label="Another take for x"]').trigger('click'); await flushPromises()
  expect(takes).toBe(1)
  expect(calls(f, 'POST', '/api/media/generate').map(c => JSON.parse(String(c[1]?.body)).another_take)).toEqual([undefined, true])
  ok.mockRestore(); w.unmount()
})

it('opens with the money at a glance: spent so far, what is left to make at the chosen tiers, and what waits for review', async () => {
  const { w } = setup(() => [slot({ name: 'todo-a' }), slot({ name: 'clip-b', kind: 'video', plans: veo }), slot({ name: 'review-c', candidates: ['review-c-1.png'] })])
  await flushPromises()
  const strip = w.get('[data-testid=cost-strip]')
  expect(strip.text()).toContain('Spent so far')
  expect(strip.text()).toContain('about $1.10')
  expect(strip.text()).toContain('about $0.08 + 1 unpriced')                 // todo-a at standard; clip-b's standard price is not listed
  expect(strip.text()).toContain('2 items at the chosen tiers')
  expect(strip.text()).toContain('1')                                         // one slot waits for a decision
  await w.get('[data-slot=todo-a] select').setValue('premium')
  expect(w.get('[data-testid=cost-strip]').text()).toContain('about $0.15 + 1 unpriced')   // the strip follows the tier choice
  expect(w.text()).toContain('nothing starts until you confirm')
  w.unmount()
})

it('shows what was already made as a gallery with the storage it takes, hides Regenerate under More, and clears unused takes only after a confirmation', async () => {
  const stored = { published_bytes: 3 * 1048576, unused_bytes: 2 * 1048576, unused_count: 2 }
  const f = stubFetch((u, init) => {
    if (u === '/api/media/folders') return { body: { folders: [{ path: '/ws/site', name: 'site' }] } }
    if (u.startsWith('/api/media/slots')) return { body: { working_dir: '/ws/site', slots: [slot({ name: 'hero-still', published: true, published_bytes: 1048576 }), slot({ name: 'hero-clip', kind: 'video', published: true, published_bytes: 2097152 })], cost: { spent_usd: 0, spent_runs: 0 }, storage: stored } }
    if (u === '/api/media/ledger') return { body: { runs: 0, done: 0, estimated_usd: 0, unpriced: 0, repeats: 0, repeat_usd: 0, rows: [], note: 'n' } }
    if (u === '/api/media/clear-unused' && init?.method === 'POST') return { body: { deleted: 2, freed_bytes: 2097152 } }
    return undefined
  })
  const w = mount(MediaGeneratePanel, { props: { keySaved: true } })
  await flushPromises()
  const gallery = w.get('[data-testid=gallery]')
  expect(gallery.find('img[src^="/api/media/published?"]').attributes('src')).toContain('name=hero-still')
  expect(gallery.find('video[src^="/api/media/published?"]').attributes('src')).toContain('name=hero-clip')
  expect(gallery.text()).toContain('1.0 MB')
  expect(gallery.find('details.more-actions button[aria-label="Regenerate hero-still"]').exists()).toBe(true)      // out of the way, not gone
  expect(w.get('[data-testid=storage]').text()).toContain('published 3.0 MB · unused takes 2.0 MB in 2 files')
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await w.get('[data-testid=clear-unused]').trigger('click'); await flushPromises()
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(confirm.mock.calls[0]![0]).toContain('cannot be undone')
  expect(calls(f, 'POST', '/api/media/clear-unused')).toHaveLength(0)                                               // declined: nothing deleted
  confirm.mockReturnValue(true)
  await w.get('[data-testid=clear-unused]').trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/media/clear-unused')[0]![1]!.body))).toEqual({ working_dir: '/ws/site', confirm: true })
  expect(w.text()).toContain('Deleted 2 unused takes, freeing 2.0 MB.')
  w.unmount()
})
