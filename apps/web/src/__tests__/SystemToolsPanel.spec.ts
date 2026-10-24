import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import SystemToolsPanel from '@/components/SystemToolsPanel.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })
const row = (id: string, version: string | null, over: Record<string, unknown> = {}) => ({ id, needed_for: 'tests', installed: !!version, version, latest: null, outdated: null, path: version ? `/opt/homebrew/bin/${id}` : null, formulae: [id], stopped: false, ...over })
const mac = (over: Record<string, unknown> = {}) => ({
  platform: 'mac', tools: [row('python3', '3.14.6'), row('docker', null), row('gh', '2.93.0', { latest: '2.102.0', outdated: true })], missing: ['docker'], outdated: ['gh'], updates_checked: true, job: null,
  brew: { installed: true, path: '/opt/homebrew/bin/brew', version: '5.1.12', install_command: 'BREW-INSTALL-COMMAND', prerequisite: 'Homebrew installs these.' }, can_install_all: true, can_upgrade_all: true, ...over,
})
const job = (state: string, over: Record<string, unknown> = {}) => ({ id: 'j', action: 'brew_upgrade_all', label: 'Upgrading optional tools with Homebrew', state, started: 1, tail: ['$ brew update', 'done'], exit: state === 'failed' ? 3 : 0, ...over })
const stubs = { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } }
const tick = async (ms = 0) => { await vi.advanceTimersByTimeAsync(ms); await nextTick() }

it('lists each tool with its version and what is outdated, and offers Install (All) and Upgrade (All) with Homebrew', async () => {
  stubFetch(url => url.startsWith('/api/host/readiness/tools') ? { body: mac() } : undefined)
  const w = mount(SystemToolsPanel, stubs); await flushPromises()
  expect(w.get('[data-tool="gh"] [data-test="version"]').text()).toBe('2.93.0 → 2.102.0')
  expect(w.get('[data-tool="gh"] [data-test="word"]').text()).toBe('upgrade available')
  expect(w.get('[data-tool="docker"] [data-test="word"]').text()).toBe('missing')
  expect(w.get('[data-action="install-all"]').attributes('disabled')).toBeUndefined()
  expect(w.get('[data-tool="all"]').text()).toContain('1 missing · 1 to upgrade')
  w.unmount()
})

it('offers Install from Agent tools for a missing managed tool on a Mac and on Linux, and not for one that is present', async () => {
  const tools = [row('gitleaks', null), row('csstree-validator', null), row('node', null), row('python3', '3.14.6'), row('docker', null)]
  for (const platform of ['mac', 'linux'] as const) {
    stubFetch(url => url.startsWith('/api/host/readiness/tools') ? { body: mac({ platform, tools, missing: ['gitleaks', 'csstree-validator', 'node', 'docker'] }) } : undefined)
    const w = mount(SystemToolsPanel, stubs); await flushPromises()
    for (const id of ['gitleaks', 'csstree-validator', 'node']) expect(w.get(`[data-tool="${id}"]`).text()).toContain('Install from Agent tools')
    expect(w.get('[data-tool="docker"]').text()).not.toContain('Install from Agent tools')       // Docker is a system package, not an Agent tools install
    expect(w.get('[data-tool="python3"]').text()).not.toContain('Install from Agent tools')
    w.unmount()
  }
  stubFetch(url => url.startsWith('/api/host/readiness/tools') ? { body: mac({ tools: [row('gitleaks', '8.30.1')], missing: [] }) } : undefined)
  const present = mount(SystemToolsPanel, stubs); await flushPromises()
  expect(present.get('[data-tool="gitleaks"]').text()).not.toContain('Install from Agent tools')
  present.unmount()
})

it('puts the Homebrew prerequisite first and disables both bulk buttons until it is installed', async () => {
  stubFetch(url => url.startsWith('/api/host/readiness/tools') ? { body: mac({ brew: { installed: false, path: null, version: null, install_command: 'BREW-INSTALL-COMMAND', prerequisite: 'Homebrew installs these.' }, can_install_all: false, can_upgrade_all: false }) } : undefined)
  const w = mount(SystemToolsPanel, stubs); await flushPromises()
  expect(w.get('[data-tool="brew"]').text()).toContain('needed first')
  expect(w.get('[data-test="brew-command"]').text()).toBe('BREW-INSTALL-COMMAND')
  expect(w.get('[data-action="install-all"]').attributes('disabled')).toBeDefined()
  expect(w.get('[data-action="upgrade-all"]').attributes('disabled')).toBeDefined()
  w.unmount()
})

it('runs Upgrade (All) as one job with a progress bar and log, then reloads and runs the health check', async () => {
  vi.useFakeTimers()
  let state = 'running'
  const f = stubFetch((url, init) => {
    if (url === '/api/host/readiness/fix' && init?.method === 'POST') return { body: { message: 'Started: brew update.', job: job('running') } }
    if (url === '/api/host/readiness/job') return { body: { job: job(state) } }
    if (url === '/api/host/readiness/tools/health') return { body: { checks: [{ id: 'gh', ok: true, version: '2.102.0', next: [] }, { id: 'docker', ok: false, version: null, next: ['Docker is installed but its engine is not running.'] }] } }
    if (url.startsWith('/api/host/readiness/tools')) return { body: mac() }
    return undefined
  })
  const w = mount(SystemToolsPanel, stubs); await tick()
  await w.get('[data-action="upgrade-all"]').trigger('click'); await tick()
  expect(JSON.parse(String(calls(f, 'POST', '/api/host/readiness/fix')[0]![1]!.body))).toEqual({ action: 'brew_upgrade_all' })
  expect(w.find('[data-tool="all"] [role="progressbar"]').exists()).toBe(true)
  expect(w.get('[data-tool="all"] .log').text()).toContain('$ brew update')
  expect(w.get('[data-action="upgrade-all"]').attributes('disabled')).toBeDefined()             // one job at a time
  state = 'done'; await tick(2600); await tick()
  expect(w.text()).toContain('Finished: Upgrading optional tools with Homebrew')
  expect(calls(f, 'GET', '/api/host/readiness/tools/health')).toHaveLength(1)
  expect(w.get('[data-tool="all"] [data-test="health"]').text()).toContain('needs attention')
  expect(w.get('[data-tool="all"] [data-test="health"]').text()).toContain('docker: Docker is installed but its engine is not running.')
  w.unmount()
})

it('on Linux shows the apt command to copy and never offers to run it', async () => {
  stubFetch(url => url.startsWith('/api/host/readiness/tools') ? { body: { platform: 'linux', tools: [row('python3', '3.11.2'), row('ffmpeg', null)], missing: ['ffmpeg'], outdated: [], updates_checked: false, job: null, can_install_all: false, can_upgrade_all: false, apt_command: 'sudo apt-get update && sudo apt-get install -y ffmpeg' } } : undefined)
  const w = mount(SystemToolsPanel, stubs); await flushPromises()
  expect(w.get('[data-test="apt"]').text()).toContain('sudo apt-get install -y ffmpeg')
  expect(w.find('[data-action="install-all"]').exists()).toBe(false)
  expect(w.find('[data-tool="brew"]').exists()).toBe(false)
  w.unmount()
})
