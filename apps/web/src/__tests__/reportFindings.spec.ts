import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import FindingTaskDialog from '@/components/FindingTaskDialog.vue'
import { createAppRouter } from '@/router'
import { GUARD_HEADER } from '@/lib/api'
import { actionableFindings } from '@/lib/findings'
import { calls, headerOf, stubFetch } from './helpers'

const reportId = 'e'.repeat(64)
const content = [
  '# Fleet health',
  '',
  'Prose that names a route cannot create one. ## Not a heading',
  '## jobs - crit (2 failed runs)',
  '2 failed in the last 24 hours.',
  '',
  '## disk-data - ok (40% used)',
  'Healthy.',
  '',
  '## agents - warn (no recent result)',
  'Agents have not reported.',
].join('\n')

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.innerHTML = '' })

describe('report findings', () => {
  it('lists only warning and critical collector sections, with their evidence', () => {
    const findings = actionableFindings(content)
    expect(findings.map(f => [f.id, f.status, f.reason])).toEqual([
      ['jobs', 'crit', '2 failed runs'],
      ['agents', 'warn', 'no recent result'],
    ])
    expect(findings[0]!.evidence).toBe('2 failed in the last 24 hours.')
  })

  it('creates a Backlog draft through the guarded draft endpoint and links to it', async () => {
    const fetch = stubFetch((url, init) => {
      if (url === '/api/agents') return { body: { agents: [{ id: 'claude', name: 'Claude', role: 'worker', available: true, default_model: 'claude-haiku-5-5', suggested_models: [], enforces_mode: true, notes: '' }] } }
      if (url === '/api/workdirs') return { body: { workdirs: [{ path: '/work/repo', branch: 'feature', root: '/work' }] } }
      if (init?.method === 'POST') return { status: 201, body: { created: true, task: { id: 42, title: 'Investigate Ops finding: jobs' } } }
      return { status: 404, body: { detail: 'not found' } }
    })
    const router = createAppRouter(createMemoryHistory())
    router.push('/reports')
    await router.isReady()
    const w = mount(FindingTaskDialog, { props: { reportId, reportModified: 1000, finding: actionableFindings(content)[0]! }, global: { plugins: [router] } })
    await flushPromises()
    await w.get('form').trigger('submit')
    await flushPromises()

    const [, init] = calls(fetch, 'POST', `/api/reports/${reportId}/findings/jobs/draft`)[0]!
    expect(headerOf(init, GUARD_HEADER)).toBe('1')
    expect(JSON.parse(String(init?.body))).toEqual(expect.objectContaining({ report_id: reportId, finding_id: 'jobs', agent: 'claude', mode: 'read', working_dir: '/work/repo', timeout_s: 1800, budget_usd: 1 }))
    expect(w.text()).toContain('Task #42 was created in Backlog.')
    expect(w.get('a[href="/tasks?card=42"]').text()).toContain('Open task #42')
    w.unmount()
  })

  it('shows Open existing when the draft already exists instead of creating a second task', async () => {
    stubFetch((url, init) => {
      if (url === '/api/agents') return { body: { agents: [{ id: 'codex', name: 'Codex', role: 'worker', available: true, default_model: null, suggested_models: [], enforces_mode: true, notes: '' }] } }
      if (url === '/api/workdirs') return { body: { workdirs: [{ path: '/work/repo', branch: null, root: '/work' }] } }
      if (init?.method === 'POST') return { status: 201, body: { created: false, task: { id: 7, title: 'Investigate Ops finding: jobs' } } }
      return { status: 404, body: { detail: 'not found' } }
    })
    const router = createAppRouter(createMemoryHistory())
    router.push('/reports')
    await router.isReady()
    const w = mount(FindingTaskDialog, { props: { reportId, reportModified: 1000, finding: actionableFindings(content)[0]! }, global: { plugins: [router] } })
    await flushPromises()
    await w.get('form').trigger('submit')
    await flushPromises()
    expect(w.text()).toContain('A task already exists for this finding.')
    expect(w.get('a[href="/tasks?card=7"]').text()).toContain('Open existing task #7')
    w.unmount()
  })
})
