import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import GithubView from '@/views/GithubView.vue'
import ReportsView from '@/views/ReportsView.vue'
import { createAppRouter } from '@/router'
import { GUARD_HEADER } from '@/lib/api'
import type { OpsCollectorStatus, Report } from '@/lib/operations'
import { dailyFleetReports, duration, filterChecks, filterReports, linkFor, reportKind, worstSeverity } from '@/lib/opsHealth'
import { renderReport } from '@/lib/reportMarkdown'
import { calls, headerOf, stubFetch } from './helpers'

const fresh = { checked_at: 1000, stale: false, error: null }
const repos = ['example-repo', 'another-repo'].map(name => ({ name: `example-user/${name}`, url: `https://github.com/example-user/${name}`, private: true, archived: false, branch: 'main', description: 'Operations', updated_at: '2026-10-09T00:00:00Z' }))
const report = { id: 'a'.repeat(64), name: 'weekly/status.md', modified_at: 1000, size: 90, readable: true }
const nowS = Math.floor(Date.now() / 1000)
const fleet: Report = { id: 'c'.repeat(64), name: 'fleet-health/20261012-100000.md', modified_at: nowS - 3600, size: 120, readable: true, source: 'Ops report folder', source_id: 'ops' }
const archived: Report = { id: 'd'.repeat(64), name: 'historic-archive/old.md', title: 'Historic (archived) · old.md', modified_at: nowS - 90000, size: 50, readable: true, source: 'Ops report folder', source_id: 'ops' }
const idle: OpsCollectorStatus = { enabled: true, error: null, schedules: [], archive: null, sources: [], overall: 'ok', last_run: null, link: '/reports' }
const ops: OpsCollectorStatus = {
  enabled: true, error: null, overall: 'crit', link: '/reports', archive: null,
  schedules: [{ id: 'morning-health', label: 'Morning fleet health', enabled: false, every_s: null, at: '07:00', weekday: null, last_run: null, next_due: null }],
  last_run: { at: nowS - 60, checked: ['disk-data', 'jobs', 'agents'], cached: 0, changed: ['jobs'], report: fleet.name, schedule: null },
  sources: [
    { id: 'jobs', kind: 'jobs', status: 'crit', summary: '2 failed, 0 stuck runs, 0 approvals waiting too long', evidence: '1 awaiting approval', checked_at: nowS - 60, since: nowS - 1800, stale: false },
    { id: 'disk-data', kind: 'disk', status: 'ok', summary: '40% used', evidence: '100 GiB free', checked_at: nowS - 60, since: null, stale: false },
    { id: 'agents', kind: 'agents', status: 'missing', summary: null, evidence: null, checked_at: null, since: null, stale: true },
  ],
}

async function mountAt(component: typeof ReportsView, path: string) {
  const router = createAppRouter(createMemoryHistory())
  router.push(path)
  await router.isReady()
  return mount(component, { global: { plugins: [router] } })
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.innerHTML = '' })

describe('operations pages', () => {
  it('shows repositories, switches details, filters and retains stale work', async () => {
    stubFetch(url => url === '/api/github/repos' ? { body: { ...fresh, repos, limited: false } } : { body: { name: url, pulls: { ...fresh, items: [] }, issues: { ...fresh, stale: true, error: 'GitHub unavailable', items: [{ number: 7, title: 'Investigate', user: 'example-user', url: 'https://github.com/example-user/example-repo/issues/7', labels: ['ops'], updated_at: '2026-10-09T00:00:00Z', draft: false }] } } })
    const w = mount(GithubView); await flushPromises()
    expect(w.text()).toContain('2 repositories')
    expect(w.text()).toContain('No open pull requests')
    expect(w.text()).toContain('Showing the last successful result')
    await w.findAll('.repo-card')[1]!.trigger('click'); await flushPromises()
    expect(w.get('.detail-heading').text()).toContain('another-repo')
    await w.get('input[type="search"]').setValue('another')
    expect(w.findAll('.repo-card')).toHaveLength(1)
    expect(w.get('a[href$="/issues/7"]').attributes('rel')).toBe('noopener noreferrer')
    w.unmount()
  })
  it('shows missing reports without trying a file request', async () => {
    const fetch = stubFetch(url => url === '/api/ops-collectors' ? { body: idle } : { body: { reports: [], available: false, error: null, limited: false, root: '/ops-reports' } })
    const w = await mountAt(ReportsView, '/reports'); await flushPromises()
    expect(w.text()).toContain('No reports yet')
    expect(w.text()).toContain('/ops-reports')
    expect(fetch.mock.calls.every(([url]) => ['/api/reports', '/api/report-storage', '/api/ops-collectors'].includes(String(url)))).toBe(true)
    w.unmount()
  })
  it('renders the latest report and reports a deleted file without stale content from another report', async () => {
    const next = { ...report, id: 'b'.repeat(64), name: 'deleted.md' }
    stubFetch(url => url === '/api/reports' ? { body: { reports: [report, next], available: true, error: null, limited: false, root: '/reports' } } : url === '/api/ops-collectors' ? { body: idle } : url.endsWith(report.id) ? { body: { ...report, content: '# Healthy\n\n| Agent | Status |\n| --- | --- |\n| Hermes | Idle |', format: 'markdown' } } : { status: 404, body: { detail: 'Report is unavailable.' } })
    const w = await mountAt(ReportsView, '/reports'); await flushPromises()
    expect(w.get('.markdown-report h1').text()).toBe('Healthy')
    expect(w.find('.markdown-report table').exists()).toBe(true)
    await w.findAll('.report-row')[1]!.trigger('click'); await flushPromises()
    expect(w.text()).toContain('Report is unavailable.')
    expect(w.find('.markdown-report').exists()).toBe(false)
    w.unmount()
  })
  it('labels historical Hermes findings and shows readable source titles', async () => {
    const archivedHermes = { ...report, title: 'Morning Fleet Health Check', source: 'Hermes cron archive', source_id: 'hermes' }
    stubFetch(url => url === '/api/reports' ? { body: { reports: [archivedHermes], available: true, error: null, limited: false, root: '/reports' } } : url === '/api/ops-collectors' ? { body: idle } : { body: { ...archivedHermes, response_only: true, content: '# Recorded findings', format: 'markdown' } })
    const w = await mountAt(ReportsView, '/reports'); await flushPromises()
    expect(w.get('article h2').text()).toBe('Morning Fleet Health Check')
    expect(w.text()).toContain('Hermes cron archive')
    expect(w.text()).toContain('not current health')
    expect(w.text()).toContain('original job prompt is omitted')
    w.unmount()
  })
  it('ranks failing checks first, searches them and runs a guarded refresh', async () => {
    const fetch = stubFetch((url, init) => {
      if (url === '/api/ops-collectors/refresh' && init?.method === 'POST') return { body: ops }
      if (url === '/api/ops-collectors') return { body: ops }
      if (url === '/api/reports') return { body: { reports: [fleet], available: true, error: null, limited: false, root: '/reports' } }
      if (url === `/api/reports/${fleet.id}`) return { body: { ...fleet, content: '# Fleet health: crit', format: 'markdown' } }
      return undefined
    })
    const w = await mountAt(ReportsView, '/reports'); await flushPromises()
    const panel = w.get('.ops-health')
    expect(panel.text()).toContain('Critical')
    expect(panel.findAll('.check strong').map(n => n.text())).toEqual(['jobs', 'agents', 'disk-data'])
    expect(panel.text()).toContain('1 check has no recent result.')
    expect(panel.get('.check a[href="/tasks"]').text()).toBe('Open Tasks')
    expect(panel.get(`a[href="/reports?report=${fleet.id}"]`).text()).toContain('Open the latest fleet health report')
    expect(panel.text()).toContain('Fleet health reports per day, last 7 days')
    await panel.get('input[type="search"]').setValue('disk')
    expect(panel.findAll('.check')).toHaveLength(1)
    await panel.get('input[type="search"]').setValue('')
    await panel.get('button').trigger('click'); await flushPromises()
    const [[, init]] = calls(fetch, 'POST', '/api/ops-collectors/refresh')
    expect(headerOf(init, GUARD_HEADER)).toBe('1')
    expect(panel.text()).not.toContain('Operator sign-in is required')
    w.unmount()
  })
  it('explains that a refresh needs operator sign-in instead of failing silently', async () => {
    stubFetch((url, init) => {
      if (url === '/api/ops-collectors/refresh' && init?.method === 'POST') return { status: 403, body: { detail: 'Forbidden' } }
      if (url === '/api/ops-collectors') return { body: idle }
      if (url === '/api/reports') return { body: { reports: [], available: false, error: null, limited: false, root: '/reports' } }
      return undefined
    })
    const w = await mountAt(ReportsView, '/reports'); await flushPromises()
    await w.get('.ops-health button').trigger('click'); await flushPromises()
    expect(w.get('.ops-health [role="alert"]').text()).toBe('Operator sign-in is required to run checks now.')
    w.unmount()
  })
  it('labels archived copies, filters reports and opens the report named in the link', async () => {
    stubFetch(url => {
      if (url === '/api/reports') return { body: { reports: [fleet, archived], available: true, error: null, limited: false, root: '/reports' } }
      if (url === '/api/ops-collectors') return { body: idle }
      if (url === `/api/reports/${archived.id}`) return { body: { ...archived, content: '# Old run', format: 'markdown' } }
      if (url.startsWith('/api/reports/')) return { body: { ...fleet, content: '# Fleet', format: 'markdown' } }
      return undefined
    })
    const w = await mountAt(ReportsView, `/reports?report=${archived.id}`); await flushPromises()
    expect(w.get('article h2').text()).toBe('Historic (archived) · old.md')
    expect(w.text()).toContain('Archived copy · original unchanged')
    expect(w.text()).toContain('original file and its source are unchanged')
    expect(w.get(`a[href="/reports?report=${archived.id}"]`).text()).toBe('Link to this report')
    expect(w.findAll('.report-row')).toHaveLength(2)
    await w.get('.report-controls input[type="search"]').setValue('fleet')
    expect(w.findAll('.report-row')).toHaveLength(1)
    w.unmount()
  })
})
describe('untrusted report Markdown', () => {
  it('escapes HTML, rejects unsafe/relative links and prevents remote images', () => {
    const html = renderReport('<script>alert(1)</script>\n\n[bad](javascript:alert%281%29) [relative](/auth/logout) ![remote](https://example.com/tracker) [good](https://github.com/example-user/example-repo)')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('href="javascript:')
    expect(html).not.toContain('href="/auth/')
    expect(html).toContain('href="https://github.com/example-user/example-repo"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('[Image: remote]')
  })
})
describe('ops health logic', () => {
  const now = 1_000_000_000
  const checks = ops.sources
  it('searches checks case-insensitively and filters by severity', () => {
    expect(filterChecks(checks, 'DISK', 'all').map(s => s.id)).toEqual(['disk-data'])
    expect(filterChecks(checks, '', 'crit').map(s => s.id)).toEqual(['jobs'])
    expect(filterChecks(checks, 'awaiting', 'all').map(s => s.id)).toEqual(['jobs'])
  })
  it('counts fleet health reports per day and ignores archived and Hermes copies', () => {
    const hermes: Report = { ...fleet, id: 'e'.repeat(64), name: 'x.md', source_id: 'hermes', source: 'Hermes cron archive' }
    const reports = [{ ...fleet, modified_at: now - 100 }, { ...fleet, id: 'f'.repeat(64), modified_at: now - 2 * 86400 - 5 }, { ...archived, modified_at: now - 100 }, { ...hermes, modified_at: now - 100 }]
    expect(dailyFleetReports(reports, now)).toEqual([0, 0, 0, 0, 1, 0, 1])
  })
  it('describes durations and worst severity and routes release checks to Settings', () => {
    expect(duration(30)).toBe('< 1 min')
    expect(duration(600)).toBe('10 min')
    expect(duration(7200)).toBe('2 h')
    expect(duration(172800)).toBe('2 d')
    expect(worstSeverity([], 'crit')).toBe('crit')
    expect(worstSeverity(checks, 'ok')).toBe('crit')
    expect(linkFor('release')).toBe('/profile')
    expect(linkFor('service')).toBe('/services')
    expect(linkFor('memory')).toBe('/pi')
    expect(linkFor('command')).toBe('/reports')
  })
  it('classifies and searches reports by kind', () => {
    expect(reportKind(fleet)).toBe('fleet')
    expect(reportKind(archived)).toBe('archived')
    expect(filterReports([fleet, archived], 'old', 'archived').map(r => r.id)).toEqual([archived.id])
    expect(filterReports([fleet, archived], '', 'hermes')).toEqual([])
  })
})
