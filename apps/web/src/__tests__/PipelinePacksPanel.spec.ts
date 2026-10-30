import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PipelinePacksPanel from '@/components/PipelinePacksPanel.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const stubs = { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } }
const service = (ready: boolean) => ({ id: 'upubhub', label: 'upubhub.com', credential: 'upubhub', ready })
const offered = (over: Record<string, unknown> = {}) => ({ id: 'upubhub-class', label: 'upubhub class', summary: 'Textbook, lesson plans and assessments.', version: '0.1.0', service: service(true), installed: null, update: false, ...over })
const listing = (over: Record<string, unknown> = {}) => ({ repository: 'gptkiosk/dashboard-pipeline-packs', release: 'packs-1', error: null, available: [offered()], installed: [], ...over })

it('offers packs in a dropdown and installs the chosen one', async () => {
  let installed = false
  const f = stubFetch((url, init) => {
    if (url === '/api/pipeline-packs/install') { installed = true; return { body: { installed: 'upubhub-class', version: '0.1.0', project_types: ['upubhub-class'] } } }
    if (url.startsWith('/api/pipeline-packs')) return { body: installed ? listing({ available: [offered({ installed: '0.1.0' })], installed: [{ id: 'upubhub-class', label: 'upubhub class', version: '0.1.0', project_types: ['upubhub-class'], service: service(true) }] }) : listing() }
    return undefined
  })
  const w = mount(PipelinePacksPanel, stubs); await flushPromises()
  expect(w.get('[data-testid=packs-add]').text()).toContain('Textbook, lesson plans and assessments.')
  await w.get('[data-action=install]').trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/pipeline-packs/install')[0]![1]!.body))).toEqual({ id: 'upubhub-class' })
  expect(w.text()).toContain('Installed upubhub-class 0.1.0. New project type: upubhub-class.')
  expect(w.get('[data-pack=upubhub-class]').text()).toContain('installed')
  expect(w.find('[data-testid=packs-add]').exists()).toBe(false)                // nothing left to add
  w.unmount()
})

it('says why a service pack cannot be installed yet and keeps its button disabled', async () => {
  stubFetch(url => url.startsWith('/api/pipeline-packs') ? { body: listing({ available: [offered({ service: service(false) })] }) } : undefined)
  const w = mount(PipelinePacksPanel, stubs); await flushPromises()
  expect(w.get('[data-action=install]').attributes('disabled')).toBeDefined()
  expect(w.get('[data-testid=packs-needs]').text()).toContain('Needs your upubhub.com credential')
  w.unmount()
})

it('offers an update for an installed pack and shows why packs could not be listed', async () => {
  stubFetch(url => url.startsWith('/api/pipeline-packs') ? { body: listing({ available: [offered({ installed: '0.1.0', update: true, version: '0.2.0' })],
    installed: [{ id: 'upubhub-class', label: 'upubhub class', version: '0.1.0', project_types: ['upubhub-class'], service: service(true) }] }) } : undefined)
  const w = mount(PipelinePacksPanel, stubs); await flushPromises()
  expect(w.get('[data-pack=upubhub-class] [data-test=version]').text()).toBe('0.1.0 → 0.2.0')
  expect(w.get('[data-action=update]').text()).toBe('Update to 0.2.0')
  w.unmount()
  stubFetch(url => url.startsWith('/api/pipeline-packs') ? { body: listing({ error: 'Could not reach the packs repository: network error (URLError)', available: [] }) } : undefined)
  const e = mount(PipelinePacksPanel, stubs); await flushPromises()
  expect(e.get('[data-testid=packs-error]').text()).toContain('Could not reach the packs repository')
  e.unmount()
})
