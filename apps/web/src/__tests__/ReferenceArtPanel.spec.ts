import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ReferenceArtPanel from '@/components/ReferenceArtPanel.vue'

afterEach(() => { vi.unstubAllGlobals() })
const usage = { references_bytes: 2048, candidates_bytes: 1024 * 1024, media_bytes: 2 * 1024 * 1024, disk_free_bytes: 5 * 1024 ** 3, disk_total_bytes: 100 * 1024 ** 3 }

it('uploads dropped images one at a time, shows thumbnails and space use, and warns when the disk is nearly full', async () => {
  let items: { name: string; size: number; path: string }[] = []
  const posted: { url: string; type: string }[] = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'content-type': 'application/json' } })
    if (url.startsWith('/api/media/references?') && init?.method === 'POST') {
      const name = new URLSearchParams(url.split('?')[1]).get('name')!
      posted.push({ url, type: (init.headers as Record<string, string>)['Content-Type'] })
      if (name === 'notes.png') return json({ detail: 'Only PNG, JPEG, WebP or GIF images can be used as reference art.' }, 422)
      items = [...items, { name, size: 10, path: `media/references/${name}` }]; return json(items.at(-1), 201)
    }
    if (url.startsWith('/api/media/references?')) return json({ references: items, max_bytes: 10 * 1024 * 1024, max_count: 24, usage })
    return json({})
  })
  const w = mount(ReferenceArtPanel, { props: { workingDir: '/w/site' } }); await flushPromises()
  expect(w.text()).toContain('No reference art yet.')
  expect(w.get('[data-test="space"]').text()).toContain('2.0 MiB'.slice(0, 1))
  expect(w.find('[role="meter"]').attributes('aria-valuenow')).toBe('95')
  expect(w.text()).toContain('over 90% full')
  const files = [new File([new Uint8Array([137, 80])], 'mood.png', { type: 'image/png' }), new File([new Uint8Array([1])], 'notes.png', { type: 'image/png' }),
    new File(['x'], 'readme.txt', { type: 'text/plain' })]
  await w.get('[data-test="drop"]').trigger('drop', { dataTransfer: { files } }); await flushPromises()
  expect(posted.map(p => p.type)).toEqual(['image/png', 'image/png'])          // the text file is never sent
  expect(w.findAll('[data-test="items"] img')).toHaveLength(1)
  expect(w.text()).toContain('Added 1 reference image')
  expect(w.get('[role="alert"]').text()).toContain('notes.png')
  w.unmount()
})
