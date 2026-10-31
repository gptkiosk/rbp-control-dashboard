import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PipelinePacksPanel from '@/components/PipelinePacksPanel.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const stubs = { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } }
const service = (ready: boolean) => ({ id: 'upubhub', label: 'upubhub.com', credential: 'upubhub', ready })
const offered = (over: Record<string, unknown> = {}) => ({ id: 'upubhub-class', label: 'upubhub class', summary: 'Textbook, lesson plans and assessments.', version: '0.1.0', service: service(true), installed: null, update: false,
  author: 'gptkiosk', trust: 'official', settings: [], needs: [], too_new: false, ...over })
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
  expect(w.text()).toContain('Added upubhub-class 0.1.0. New project type: upubhub-class.')
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

it('shows who made a template, its settings and what this host lacks, and holds a template that needs a newer dashboard', async () => {
  const need = (kind: string, id: string, detail: string, link: string) => ({ kind, id, status: 'missing', detail, link })
  stubFetch(url => url.startsWith('/api/pipeline-packs') ? { body: listing({ available: [
    offered({ trust: 'community', author: 'a-teacher', settings: ['Subject code', 'Level'], needs: [need('system_tools', 'ffmpeg', 'Needs ffmpeg: install it in System tools.', '/profile#system-tools')] }),
    offered({ id: 'next-pack', label: 'Next pack', version: '1.0.0', too_new: true, needs: [need('app', '99.0.0', 'Needs dashboard 99.0.0 or newer.', '/profile#updates')] })] }) } : undefined)
  const w = mount(PipelinePacksPanel, stubs); await flushPromises()
  const detail = w.get('[data-testid=packs-detail]')
  expect(detail.text()).toContain('Community, by a-teacher · version 0.1.0')
  expect(w.get('[data-testid=packs-settings]').text()).toBe('Settings you choose: Subject code, Level.')
  expect(w.get('[data-testid=packs-lacking]').text()).toContain('Needs ffmpeg: install it in System tools. Fix this')
  expect(w.get('[data-action=install]').attributes('disabled')).toBeUndefined()      // a missing tool does not stop adding the template
  const pick = w.vm as unknown as { choice: string }; pick.choice = 'next-pack'; await flushPromises()
  expect(w.get('[data-testid=packs-too-new]').text()).toContain('Needs dashboard 99.0.0 or newer.')
  expect(w.get('[data-action=install]').attributes('disabled')).toBeDefined()
  w.unmount()
})

it('lists the approved tools with whether this host has them', async () => {
  const tool = (id: string, status: string, detail = '') => ({ id, name: id.toUpperCase(), description: `${id} does a thing.`, app_min: '0.6.0', status, detail, link: '/profile#system-tools' })
  stubFetch(url => url.startsWith('/api/pipeline-packs') ? { body: listing({ tools: { system_tools: [tool('python3', 'ready'), tool('ffmpeg', 'missing', 'Needs ffmpeg: install it in System tools.')], agents: [] } }) } : undefined)
  const w = mount(PipelinePacksPanel, stubs); await flushPromises()
  await w.get('[data-view=tools]').trigger('click')
  const tools = w.get('[data-testid=packs-tools]')
  expect(tools.findAll('h4').map(h => h.text())).toEqual(['System tools'])          // empty kinds are left out
  expect(w.get('[data-tool=python3]').text()).toContain('Ready')
  expect(w.get('[data-tool=ffmpeg]').text()).toContain('Not set up')
  expect(w.get('[data-tool=ffmpeg]').text()).toContain('Needs ffmpeg: install it in System tools. Fix this')
  w.unmount()
})
