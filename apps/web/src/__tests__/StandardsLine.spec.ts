import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import StandardsLine from '@/components/StandardsLine.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })

const ok = (over: Record<string, unknown> = {}) => ({
  state: 'ok', path: 'docs/development/standards.md', property: 'upubhub', sha256: 'a'.repeat(64),
  areas: [{ area: 'Money', risk: 'high', route: 'foundation' }, { area: 'Docs', risk: 'low', route: 'free' }],
  checks: [{ touches: 'apps/api', run: 'pytest' }], warnings: [], message: '', ...over,
})

it('names the property, how many areas and checks, and a short hash of the file', async () => {
  const f = stubFetch(url => url === '/api/projects/7/standards' ? { body: ok() } : undefined)
  const w = mount(StandardsLine, { props: { projectId: 7, revision: 1 } }); await flushPromises()
  const text = w.get('[data-testid="standards"]').text()
  expect(text).toContain('upubhub')
  expect(text).toContain('2 areas')
  expect(text).toContain('1 check')
  expect(text).toContain('a'.repeat(12))
  expect(calls(f, 'GET', '/api/projects/7/standards')).toHaveLength(1)
  w.unmount()
})

it('warns, in plain words, when the file is missing or unreadable, and says planning goes on', async () => {
  stubFetch(() => ({ body: ok({ state: 'missing', property: null, sha256: null, areas: [], checks: [], message: 'No docs/development/standards.md in this project\'s working directory. Planning continues without standards.' }) }))
  const w = mount(StandardsLine, { props: { projectId: 7 } }); await flushPromises()
  expect(w.get('[role="status"]').text()).toContain('No standards in use.')
  expect(w.text()).toContain('Planning continues without standards.')
  w.unmount()
})

it('lists parser notes behind a fold and says nothing when the question cannot be asked', async () => {
  stubFetch(() => ({ body: ok({ warnings: ['No "Risk by area" table was found.'] }) }))
  const w = mount(StandardsLine, { props: { projectId: 7 } }); await flushPromises()
  expect(w.get('details summary').text()).toContain('1 note')
  expect(w.get('details').attributes('open')).toBeUndefined()
  w.unmount()
  stubFetch(() => ({ status: 500, body: { detail: 'boom' } }))
  const failed = mount(StandardsLine, { props: { projectId: 7 } }); await flushPromises()
  expect(failed.find('[data-testid="standards"]').exists()).toBe(false)
  failed.unmount()
})

it('says plainly when the starter standards are in use, which copy, and why the repository was not used', async () => {
  stubFetch(() => ({ body: ok({ source: 'starter', starter_from: 'shipped', property: null, repo_state: 'missing', message: 'No docs/development/standards.md in this project\'s working directory. Planning continues without standards.' }) }))
  const w = mount(StandardsLine, { props: { projectId: 7 } }); await flushPromises()
  const text = w.get('[data-testid="starter"]').text()
  expect(text).toContain('Starter standards')
  expect(text).toContain('shipped')
  expect(text).toContain('2 areas')
  expect(text).toContain('No docs/development/standards.md')
  w.unmount()
})

const proposal = (over: Record<string, unknown> = {}) => ({
  id: 4, created_at: 1, created_by: 'hermes:op', project_id: 7, summary: 'Email sending is high risk.', section: 'risk',
  patch: '--- a\n+++ b\n+| Email sending | high |', status: 'pending', decided_by: null, result: null, ...over,
})

it('shows a proposed addition with its exact diff and lets the operator approve it, then shows the branch', async () => {
  let current = proposal()
  const f = stubFetch((url, init) => {
    if (url === '/api/projects/7/standards') return { body: ok() }
    if (url === '/api/standards/proposals?project_id=7') return { body: { proposals: [current] } }
    if (url === '/api/standards/proposals/4/approve' && init?.method === 'POST') {
      current = proposal({ status: 'applied', result: { branch: 'standards/4-risk', note: 'Committed on a new branch. Nothing was pushed.' } })
      return { body: current }
    }
    return undefined
  })
  const w = mount(StandardsLine, { props: { projectId: 7 } }); await flushPromises()
  const card = w.get('[data-testid="proposal-4"]')
  expect(card.text()).toContain('Waiting for you:')
  expect(card.get('pre.patch').text()).toContain('+| Email sending | high |')
  await card.findAll('button').find(b => b.text().startsWith('Approve'))!.trigger('click'); await flushPromises()
  expect(calls(f, 'POST', '/api/standards/proposals/4/approve')).toHaveLength(1)
  expect(w.get('[data-testid="proposal-4"]').text()).toContain('standards/4-risk')
  expect(w.find('[data-testid="proposal-4"] button').exists()).toBe(false)
  w.unmount()
})

it('shows a refusal in words and offers reject', async () => {
  stubFetch((url, init) => {
    if (url === '/api/projects/7/standards') return { body: ok() }
    if (url === '/api/standards/proposals?project_id=7') return { body: { proposals: [proposal()] } }
    if (url === '/api/standards/proposals/4/reject' && init?.method === 'POST') return { status: 409, body: { detail: 'That proposal is not waiting for a decision.' } }
    return undefined
  })
  const w = mount(StandardsLine, { props: { projectId: 7 } }); await flushPromises()
  await w.findAll('button').find(b => b.text() === 'Reject')!.trigger('click'); await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('not waiting for a decision')
  w.unmount()
})
