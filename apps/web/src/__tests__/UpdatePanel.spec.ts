import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import UpdatePanel from '@/components/UpdatePanel.vue'
import { stubFetch, calls, headerOf } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })

const REPO = 'gptkiosk/rbp-control-dashboard'
const names: Record<string, string> = { v0: '0.9', v1: '1.0', v2: '1.1', v3: '1.2', v4: '1.3', v5: '1.4' }
const version = (id: string, over: Record<string, unknown> = {}) => ({ id, complete: true, version: names[id], channel: 'stable', change: 'upgrade', repository: REPO, authenticity: 'ssh-signature', staged_at: 1700000000, ...over })
const managed = (over: Record<string, unknown> = {}, install: Record<string, unknown> = {}) => ({
  kind: 'release', detail: 'packaged version 1.0', configured: true, problems: [], manual_instructions: [], blockers: [],
  install: {
    current: 'v1', previous: null, tx: null, last: null, needs_recovery: false,
    versions: [version('v1', { change: 'install' }), version('v2'), version('v3', { channel: 'dev' }), version('v4', { complete: false })],
    ...install,
  },
  ...over,
})
const candidate = (over: Record<string, unknown> = {}) => ({
  product: 'rcd', platform: 'linux-arm64', repository: REPO, channel: 'stable', tag: 'v1.1', version: '1.1',
  change: 'upgrade', prerelease: false, notes: 'Fixes <b>things</b>', html_url: `https://github.com/${REPO}/releases/tag/v1.1`,
  published_at: '2026-10-01T00:00:00Z', manifest_sha256: 'a'.repeat(64), archive_sha256: 'b'.repeat(64),
  assets: [{ kind: 'manifest', name: 'rcd-1.1-linux-arm64.manifest.json', size: 900 }], authenticity: 'unverified until downloaded and checked against the configured trust root',
  ...over,
})
const tick = async (ms = 0) => { await vi.advanceTimersByTimeAsync(ms); await nextTick() }
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll('button').find(b => b.text() === text)!

it('says what is available on an unmanaged host and offers no GitHub check, download, install or rollback', async () => {
  const f = stubFetch(url => url === '/api/updates' ? { body: { kind: 'dev', detail: 'this is a source checkout', configured: false, problems: [], manual_instructions: ['Automatic updates are off for this install.'] } } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).toContain('Managed updates are off: this is a source checkout.')
  expect(w.text()).toContain('Automatic updates are off for this install.')
  expect(w.findAll('button').map(b => b.text())).toEqual([])
  expect(w.find('a').exists()).toBe(false)
  expect(f.mock.calls.map(([url]) => url)).toEqual(['/api/updates'])
  w.unmount()
})

it('does not contact GitHub on mount: only the local status is read', async () => {
  const f = stubFetch(url => url === '/api/updates' ? { body: managed() } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  expect(f.mock.calls.map(([url, init]) => `${init?.method ?? 'GET'} ${url}`)).toEqual(['GET /api/updates'])
  expect(w.text()).not.toContain('Checked GitHub')
  w.unmount()
})

it('checks the RCD repository only when the operator asks, on the chosen channel, and downloads nothing', async () => {
  const f = stubFetch(url => {
    if (url === '/api/updates') return { body: managed() }
    if (url.startsWith('/api/updates/check')) return { body: { available: true, candidate: candidate(), installed: '1.0' } }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Check for updates').trigger('click'); await flushPromises()
  expect(calls(f, 'GET', '/api/updates/check')[0]![0]).toBe('/api/updates/check?channel=stable')
  expect(calls(f, 'POST', '/api/updates')).toHaveLength(0)
  expect(w.text()).toContain('Update available: 1.1')
  expect(w.text()).toContain(REPO)
  expect(w.text()).toContain('a'.repeat(64))
  expect(w.text()).toContain('unverified until downloaded')
  expect(w.text()).toContain('Fixes <b>things</b>')
  expect(w.find('pre.notes').text()).toBe('Fixes <b>things</b>')
  expect(w.find('b').exists()).toBe(false)
  expect(w.find('a[href^="https://github.com/gptkiosk/rbp-control-dashboard/"]').exists()).toBe(true)
  w.unmount()
})

it('sends the prerelease channel the operator selected', async () => {
  const f = stubFetch(url => {
    if (url === '/api/updates') return { body: managed() }
    if (url.startsWith('/api/updates/check')) return { body: { available: false, candidate: null, installed: '1.0' } }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  await w.get('[role="combobox"][aria-label="Update channel"]').trigger('click'); await flushPromises()
  await w.findAll('[role="option"]')[1]!.trigger('click'); await flushPromises()
  await button(w, 'Check for updates').trigger('click'); await flushPromises()
  expect(calls(f, 'GET', '/api/updates/check')[0]![0]).toBe('/api/updates/check?channel=prerelease')
  expect(w.text()).toContain('No newer prerelease release than the installed version.')
  w.unmount()
})

it('refuses a release that is not rcd from this repository and offers no download button', async () => {
  stubFetch(url => {
    if (url === '/api/updates') return { body: managed({}, { versions: [version('v1', { change: 'install' })] }) }
    if (url.startsWith('/api/updates/check')) return { body: { available: true, candidate: candidate({ product: 'mcd', repository: 'gptkiosk/mac-control-dashboard' }), installed: '1.0' } }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Check for updates').trigger('click'); await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('This release is not rcd from gptkiosk/rbp-control-dashboard, so it cannot be installed here.')
  expect(w.findAll('button').map(b => b.text())).not.toContain('Download and verify 1.1')
  w.unmount()
})

it('requires an explicit confirmation and an independently entered digest before downloading', async () => {
  let staged = false
  const f = stubFetch((url, init) => {
    if (url === '/api/updates') return { body: managed({}, staged ? { versions: [version('v1', { change: 'install' }), version('v2', { version: '1.1', repository: REPO })] } : {}) }
    if (url.startsWith('/api/updates/check')) return { body: { available: true, candidate: candidate(), installed: '1.0' } }
    if (url === '/api/updates/fetch' && init?.method === 'POST') { staged = true; return { status: 202, body: { started: 'fetch', poll: '/api/updates' } } }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Check for updates').trigger('click'); await flushPromises()
  await button(w, 'Download and verify 1.1').trigger('click'); await flushPromises()
  const go = w.get('.confirm').findAll('button')[0]!
  expect(go.attributes('disabled')).toBeDefined()
  expect(calls(f, 'POST', '/api/updates/fetch')).toHaveLength(0)
  await w.get('.confirm input[maxlength="64"]').setValue('c'.repeat(64))
  await w.get('.confirm input[type="checkbox"]').setValue(true)
  expect(w.get('.confirm').findAll('button')[0]!.attributes('disabled')).toBeUndefined()
  vi.useFakeTimers()
  await w.get('.confirm').findAll('button')[0]!.trigger('click'); await tick(0)
  const [, init] = calls(f, 'POST', '/api/updates/fetch')[0]!
  expect(JSON.parse(init!.body as string)).toEqual({ version: '1.1', channel: 'stable', confirm: true, manifest_sha256: 'c'.repeat(64) })
  expect(headerOf(init, 'X-Mac-Control')).toBe('1')
  await tick(2000)
  expect(w.text()).toContain('Verified and staged 1.1. It is not installed until you confirm the install below.')
  expect(button(w, 'Install 1.1').attributes('disabled')).toBeUndefined()
  w.unmount()
})

it('reports a download the server refuses, with its problems, and installs nothing', async () => {
  stubFetch((url, init) => {
    if (url === '/api/updates') return { body: managed({}, { versions: [version('v1', { change: 'install' })] }) }
    if (url.startsWith('/api/updates/check')) return { body: { available: true, candidate: candidate(), installed: '1.0' } }
    if (url === '/api/updates/fetch' && init?.method === 'POST') return { status: 502, body: { detail: { message: 'Could not check for updates.', problems: ['GitHub rate limit reached; resets at epoch 1700000000'] } } }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Check for updates').trigger('click'); await flushPromises()
  await button(w, 'Download and verify 1.1').trigger('click'); await flushPromises()
  await w.get('.confirm input[maxlength="64"]').setValue('d'.repeat(64))
  await w.get('.confirm input[type="checkbox"]').setValue(true)
  await w.get('.confirm').findAll('button')[0]!.trigger('click'); await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('GitHub rate limit reached')
  expect(w.findAll('button').map(b => b.text())).not.toContain('Install 1.1')
  w.unmount()
})

it('shows a staged-version list only for this repository, and never offers a dev build or partial package', async () => {
  stubFetch(url => url === '/api/updates' ? { body: managed({}, { versions: [
    version('v1', { change: 'install' }), version('v2'), version('v3', { channel: 'dev' }), version('v4', { complete: false }),
    version('v5', { channel: 'docs' }), version('v0', { repository: 'gptkiosk/mac-control-dashboard' }),
  ] }) } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).toContain('Running 1.0. 1 staged update is ready on this host.')
  expect(w.findAll('button').map(b => b.text())).toContain('Install 1.1')
  expect(w.findAll('button').map(b => b.text())).not.toContain('Install 1.2')
  expect(w.findAll('button').map(b => b.text())).not.toContain('Install 1.3')
  expect(w.text()).toContain('A development build. It is never offered as an update.')
  expect(w.text()).toContain('only partly staged')
  expect(w.text()).toContain('Channel “docs” is not an application release')
  expect(w.text()).toContain('It was built from gptkiosk/mac-control-dashboard, not gptkiosk/rbp-control-dashboard')
  expect(w.text()).toContain('Release notes: not included in this package.')
  w.unmount()
})

it('requires an explicit confirmation before posting the operator-only install', async () => {
  const f = stubFetch((url, init) => url === '/api/updates' ? { body: managed() } : url === '/api/updates/apply' && init?.method === 'POST' ? { status: 202, body: { started: 'apply' } } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Install 1.1').trigger('click'); await flushPromises()
  const confirm = w.get('.confirm')
  expect(confirm.text()).toContain('Replaces 1.0')
  const go = confirm.findAll('button')[0]!
  expect(go.attributes('disabled')).toBeDefined()
  await w.get('.confirm input[type="checkbox"]').setValue(true)
  expect(confirm.findAll('button')[0]!.attributes('disabled')).toBeUndefined()
  await confirm.findAll('button')[0]!.trigger('click'); await flushPromises()
  const [, init] = calls(f, 'POST', '/api/updates/apply')[0]!
  expect(JSON.parse(init!.body as string)).toEqual({ version_id: 'v2' })
  expect(headerOf(init, 'X-Mac-Control')).toBe('1')
  expect(w.text()).toContain('Install started on the host')
  w.unmount()
})

it('disables install and rollback while work is running and says to drain first', async () => {
  stubFetch(url => url === '/api/updates' ? { body: managed({ blockers: ['1 live agent run'] }, { previous: 'v0', versions: [version('v0', { change: 'upgrade' }), version('v1', { change: 'install' }), version('v2')] }) } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).toContain('Drain first. Nothing is stopped or cancelled for you.')
  expect(button(w, 'Install 1.1').attributes('disabled')).toBeDefined()
  expect(button(w, 'Roll back to 0.9').attributes('disabled')).toBeDefined()
  w.unmount()
})

it('shows the server refusal and the blockers it names, unpacked from the 409 body', async () => {
  stubFetch((url, init) => url === '/api/updates' ? { body: managed() } : url === '/api/updates/apply' && init?.method === 'POST' ? { status: 409, body: { detail: { message: 'Drain first. Nothing was stopped.', blockers: ['1 queued task'] } } } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Install 1.1').trigger('click'); await flushPromises()
  await w.get('.confirm input[type="checkbox"]').setValue(true)
  await w.get('.confirm').findAll('button')[0]!.trigger('click'); await flushPromises()
  expect(w.get('[role="alert"]').text()).toBe('Drain first. Nothing was stopped. 1 queued task')
  w.unmount()
})

it('follows progress through a service restart and reports the health result', async () => {
  vi.useFakeTimers()
  const idle = managed()
  const switching = managed({}, { tx: { id: 't2', kind: 'switch', phase: 'switching', target: 'v2' } })
  const committed = managed({ kind: 'release' }, { current: 'v2', previous: 'v1', last: { tx: 't2', kind: 'switch', outcome: 'committed', detail: 'ready', target: 'v2', from: 'v1', at: 1700000100 } })
  const replies = [{ body: idle }, { body: switching }, { status: 503, body: { detail: 'restarting' } }, { body: committed }]
  let reads = 0
  const f = stubFetch((url, init) => {
    if (url === '/api/updates/apply' && init?.method === 'POST') return { status: 202, body: { started: 'apply' } }
    if (url === '/api/updates') return replies[Math.min(reads++, replies.length - 1)]
    return undefined
  })
  const w = mount(UpdatePanel); await tick(0)
  await button(w, 'Install 1.1').trigger('click'); await tick(0)
  await w.get('.confirm input[type="checkbox"]').setValue(true)
  await w.get('.confirm').findAll('button')[0]!.trigger('click'); await tick(0)
  expect(calls(f, 'POST', '/api/updates/apply')).toHaveLength(1)
  await tick(2000); expect(w.text()).toContain('Switching versions')
  await tick(2000); expect(w.text()).toContain('Reconnecting to the service')
  await tick(2000)
  expect(w.text()).toContain('Now running 1.1. Health check: ready')
  expect(w.text()).not.toContain('Reconnecting')
  w.unmount()
})
