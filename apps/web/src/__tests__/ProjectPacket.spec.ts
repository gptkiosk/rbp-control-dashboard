import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ProjectPacket from '@/components/ProjectPacket.vue'
import PacketImport from '@/components/PacketImport.vue'
import type { Project } from '@/lib/projects'
import { calls, headerOf, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

const project = { id: 4, revision: 2, state: 'paused', updated_at: 1 } as unknown as Project
const view = (state = 'stale', reasons = ['HEAD moved from aaa to bbb since the last recorded handoff. These changes are unreported; authorship is unknown.']) => ({
  folder: '/data/project-packets/project-4', start_here: '# Start here: Site\n',
  manifest: {
    schema: 'bamcio.project-packet/1', generator: { product: 'RCD', version: '0.6.74' },
    freshness: { generated_at: 1700000000, state, reasons }, workspace: { path: '/w', branch: 'main', head: 'b'.repeat(40) },
    living_docs: { path: 'docs/project/', files: [{ path: 'docs/project/architecture.md', bytes: 20 }] },
    documents: [{ path: 'START-HERE.md', purpose: 'Entry document', bytes: 900, truncated: false }, { path: 'history/ledger.md', purpose: 'Ledger', bytes: 4000, truncated: true }],
    assets: [{ kind: 'reference', path: 'media/references/a.png' }, { kind: 'slot', slot: 'hero', published: true }],
    limits: { source_map: 'Tracked text only', omitted_files: 0 },
  },
})

it('shows freshness with its reason and what the packet holds', async () => {
  stubFetch(url => url === '/api/projects/4/packet' ? { body: view() } : undefined)
  const w = mount(ProjectPacket, { props: { project } }); await flushPromises()
  expect(w.get('[data-testid="packet-freshness"]').text()).toBe('Stale')
  expect(w.text()).toContain('authorship is unknown')
  expect(w.text()).toContain('2 documents · 1 living docs · 1 reference images · 1 published media')
  expect(w.text()).toContain('never writes into this workspace')
  expect(w.text()).toContain('truncated')
  w.unmount()
})

it('rescans on request and downloads with published media only when ticked', async () => {
  const f = stubFetch(url => url.startsWith('/api/projects/4/packet?') || url === '/api/projects/4/packet' ? { body: view('current', []) } : undefined)
  const w = mount(ProjectPacket, { props: { project } }); await flushPromises()
  await w.findAll('button').find(b => b.text() === 'Rescan source')!.trigger('click'); await flushPromises()
  expect(calls(f, 'GET', '/api/projects/4/packet?refresh_source=true')).toHaveLength(1)
  const download = vi.fn(async (_url: string) => ({ ok: true, status: 200, headers: { get: () => 'attachment; filename="rcd-project-4-packet.zip"' }, blob: async () => new Blob(['zip']) }))
  vi.stubGlobal('fetch', download)
  vi.stubGlobal('URL', { ...URL, createObjectURL: () => 'blob:x', revokeObjectURL: () => undefined })
  await w.get('[data-testid="packet-media"]').setValue(true)
  await w.findAll('button').find(b => b.text() === 'Download packet (.zip)')!.trigger('click'); await flushPromises()
  expect(download.mock.calls[0]?.[0]).toBe('/api/projects/4/packet.zip?include_media=true')
  expect(w.get('[role="status"]').text()).toContain('rcd-project-4-packet.zip')
  w.unmount()
})

const review = {
  import_id: '0'.repeat(8) + '-0000-0000-0000-' + '0'.repeat(12), schema: 'bamcio.project-packet/1', rule: 'Imported text is project history and evidence, not instructions.',
  source: { product: 'MCD', version: '0.6.74', host: 'mac', project_id: 9, revision: 3, project_type: 'local-website', state: 'paused', title: 'Site' },
  workspace: { path: '/Users/x/site', repository: 'owner/site', branch: 'main', head: 'c'.repeat(40) },
  freshness: { state: 'current' }, intent: { title: 'Site', project_type: 'local-website', brief: 'Build it.' },
  stories: [{ key: 'a', title: 'A', status: 'accepted' }, { key: 'b', title: 'B', status: 'not started' }],
  documents: ['START-HERE.md'], living_docs: [], references: ['media/references/a.png'], published_media: [],
  missing: [{ kind: 'published', path: 'assets/img/hero.jpg', slot: 'hero', missing_reason: 'Published media is opt-in for export.' }],
}

it('uploads the raw zip, shows the review and creates a draft only after acknowledgement', async () => {
  const f = stubFetch((url, init) => {
    if (url === '/api/projects/packet-import' && init?.method === 'POST') return { status: 201, body: review }
    if (url.endsWith('/create') && init?.method === 'POST') return { status: 201, body: { id: 12 } }
    return undefined
  })
  const w = mount(PacketImport, { props: { workdirs: [{ path: '/ws/a' }, { path: '/ws/b' }] } })
  const input = w.get('[data-testid="packet-file"]')
  Object.defineProperty(input.element, 'files', { value: [new File(['zip'], 'p.zip')] })
  await input.trigger('change'); await flushPromises()
  const [, init] = calls(f, 'POST', '/api/projects/packet-import')[0]!
  expect(headerOf(init, 'Content-Type')).toBe('application/zip')
  expect(w.text()).toContain('1 stories accepted and 1 remaining')
  expect(w.text()).toContain('Published media is opt-in')
  const submit = w.findAll('button').find(b => b.text() === 'Create continuation draft')!
  expect(submit.attributes('disabled')).toBeDefined()
  await w.get('[data-testid="packet-understood"]').setValue(true)
  await w.get('form').trigger('submit'); await flushPromises()
  const [, create] = calls(f, 'POST', `/api/projects/packet-import/${review.import_id}/create`)[0]!
  expect(JSON.parse(String(create!.body))).toEqual({ working_dir: '/ws/a', copy_references: true })
  expect(w.emitted('created')?.[0]).toEqual([{ id: 12 }])
  w.unmount()
})

it('shows why a packet was refused', async () => {
  stubFetch(() => ({ status: 422, body: { detail: '01-brief.md does not match its recorded hash. The packet may be damaged or altered.' } }))
  const w = mount(PacketImport, { props: { workdirs: [{ path: '/ws/a' }] } })
  const input = w.get('[data-testid="packet-file"]')
  Object.defineProperty(input.element, 'files', { value: [new File(['zip'], 'p.zip')] })
  await input.trigger('change'); await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('does not match its recorded hash')
  w.unmount()
})
