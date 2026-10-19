import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import HostReadinessPanel from '@/components/HostReadinessPanel.vue'
import { stubFetch, calls } from './helpers'
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })
const check = (over: Record<string, unknown>) => ({ id: 'x', label: 'X', status: 'ok', detail: 'fine', fix: null, ...over })
const bare = () => ({ ready_to_build: false, ready_to_deliver: false, note: 'n', checks: [
  check({ id: 'workspace', label: 'Workspace folder', status: 'missing', detail: 'None exists.', fix: { action: 'create_workspace', label: 'Create /home/pi/Projects' } }),
  check({ id: 'git_identity', label: 'git identity', status: 'missing', detail: 'No name.', fix: { action: 'set_git_identity', label: 'Set the git identity', inputs: ['name', 'email'] } }),
  check({ id: 'github_ssh', label: 'GitHub access (SSH key)', status: 'missing', detail: 'Nothing can push.', fix: { action: 'make_github_key', label: 'Make a GitHub SSH key' } }),
  check({ id: 'agents', label: 'Agents that build', status: 'missing', detail: 'Only hermes.', agents: [{ id: 'openclaw', installed: false, writes_code: true }, { id: 'hermes', installed: true, writes_code: false }] }),
  check({ id: 'tools', label: 'Optional tools', status: 'info', detail: 'Missing: docker, gh, colima (stopped).', tools: [{ id: 'docker', installed: false, needed_for: 'containers', get: { kind: 'command', command: 'brew install colima docker docker-compose && colima start', note: 'Colima provides the Docker engine on a Mac.' } }, { id: 'gh', installed: false, needed_for: 'pull requests', get: { kind: 'agent_tools', tool: 'gh', note: 'Install the GitHub CLI from Agent tools.' } }, { id: 'colima', installed: false, stopped: true, needed_for: 'engine', get: { kind: 'command', command: 'colima start', note: 'Colima is not running.' } }] }),
] })
function setup(extra?: (u: string, init?: RequestInit) => { status?: number; body: unknown } | undefined) {
  const f = stubFetch((u, init) => (u.startsWith('/api/host/readiness') && !init?.method ? { body: bare() } : extra?.(u, init)))
  return { f, w: mount(HostReadinessPanel, { attachTo: document.body, global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } } }) }
}
it('lists each check with its state, shows builders versus coordinators, and offers one named fix per gap', async () => {
  const { w } = setup(); await flushPromises()
  expect(w.get('[data-testid=readiness-summary]').text()).toContain('Ready to build: not yet')
  expect(w.get('[data-check=workspace]').text()).toContain('needs attention')
  expect(w.get('[data-check=agents]').text()).toContain('openclaw (not installed)')
  expect(w.get('[data-check=agents]').text()).toContain('hermes · coordinator')
  expect(w.get('[data-check=tools]').text()).toContain('docker (missing)')
  expect(w.get('[data-check=tools]').text()).toContain('colima (stopped)')
  expect(w.get('[data-how=gh] a').attributes('href')).toBe('/profile#agent-tools')                        // gh: a link to install it from Agent tools
  expect(w.get('[data-how=docker] code').text()).toBe('brew install colima docker docker-compose && colima start')   // docker: a command to copy, never run by the dashboard
  expect(w.get('[data-how=colima] code').text()).toBe('colima start')
  expect(w.findAll('button').map(b => b.text())).toEqual(expect.arrayContaining(['Create /home/pi/Projects', 'Set the git identity', 'Make a GitHub SSH key']))
  w.unmount()
})
it('creates the workspace and tells the setup page to refresh', async () => {
  const { f, w } = setup((u, init) => u === '/api/host/readiness/fix' && init?.method === 'POST' ? { body: { message: 'Created /home/pi/Projects.', report: { ...bare(), checks: [check({ id: 'workspace', label: 'Workspace folder', detail: 'ok' })] } } } : undefined)
  await flushPromises()
  await w.findAll('button').find(b => b.text().startsWith('Create /home/pi'))!.trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/host/readiness/fix')[0]![1]?.body))).toEqual({ action: 'create_workspace' })
  expect(w.text()).toContain('Created /home/pi/Projects.'); expect(w.emitted('changed')).toHaveLength(1)
  w.unmount()
})
it('sends the git identity only when both fields are filled', async () => {
  const { f, w } = setup((u, init) => u === '/api/host/readiness/fix' && init?.method === 'POST' ? { body: { message: 'Commits will be made as Pi <pi@example.com>.', report: bare() } } : undefined)
  await flushPromises()
  const btn = () => w.findAll('button').find(b => b.text() === 'Set the git identity')!
  expect(btn().attributes('disabled')).toBeDefined()
  await w.get('[data-check=git_identity] input[autocomplete=name]').setValue('Pi'); expect(btn().attributes('disabled')).toBeDefined()
  await w.get('[data-check=git_identity] input[type=email]').setValue('pi@example.com'); expect(btn().attributes('disabled')).toBeUndefined()
  await btn().trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/host/readiness/fix')[0]![1]?.body))).toEqual({ action: 'set_git_identity', name: 'Pi', email: 'pi@example.com' })
  w.unmount()
})
it('shows the public key to add to GitHub after the key is made, never a private key, and can test it', async () => {
  const keyed = { ...bare(), checks: [check({ id: 'github_ssh', label: 'GitHub access (SSH key)', detail: 'A key exists.', fix: { action: 'test_github_ssh', label: 'Test GitHub access' }, public_key: 'ssh-ed25519 AAAAC3Nza host-dashboard' })] }
  const { f, w } = setup((u, init) => u === '/api/host/readiness/fix' && init?.method === 'POST' ? { body: { message: 'Made a new key.', report: keyed } } : undefined)
  await flushPromises()
  await w.findAll('button').find(b => b.text() === 'Make a GitHub SSH key')!.trigger('click'); await flushPromises()
  const area = w.get('textarea[aria-label="GitHub public key"]')
  expect((area.element as HTMLTextAreaElement).value).toBe('ssh-ed25519 AAAAC3Nza host-dashboard'); expect(area.attributes('readonly')).toBeDefined()
  expect(w.get('a[href="https://github.com/settings/ssh/new"]').attributes('rel')).toContain('noopener')
  expect(w.text()).not.toContain('PRIVATE KEY')
  await w.findAll('button').find(b => b.text() === 'Test GitHub access')!.trigger('click'); await flushPromises()
  expect(calls(f, 'POST', '/api/host/readiness/fix').map(c => JSON.parse(String(c[1]?.body)).action)).toEqual(['make_github_key', 'test_github_ssh'])
  w.unmount()
})
it('shows a refusal plainly and asks for the network test only on request', async () => {
  const { f, w } = setup((u, init) => u === '/api/host/readiness/fix' && init?.method === 'POST' ? { status: 409, body: { detail: 'GitHub did not accept the key yet.' } } : undefined)
  await flushPromises()
  await w.findAll('button').find(b => b.text() === 'Make a GitHub SSH key')!.trigger('click'); await flushPromises()
  expect(w.get('[role=alert]').text()).toContain('GitHub did not accept the key yet.')
  expect(calls(f, 'GET', '/api/host/readiness?network=true')).toHaveLength(0)
  await w.findAll('button').find(b => b.text() === 'Recheck with network test')!.trigger('click'); await flushPromises()
  expect(calls(f, 'GET', '/api/host/readiness?network=true')).toHaveLength(1)
  w.unmount()
})

it('installs a Mac tool with Homebrew, shows the running log in the panel, and rechecks when the job ends', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const report = () => ({ ready_to_build: true, ready_to_deliver: false, note: '', checks: [check({ id: 'tools', label: 'Optional tools', status: 'info', detail: 'Missing: ffmpeg.', fix: { action: 'brew_update', label: 'Update tools with Homebrew' }, tools: [{ id: 'ffmpeg', installed: false, needed_for: 'media', get: { kind: 'command', command: 'brew install ffmpeg', note: 'The dashboard does not run it.', fix: { action: 'brew_install', tool: 'ffmpeg', label: 'Install ffmpeg with Homebrew' } } }] })] })
  let polls = 0, reads = 0
  const f = stubFetch((u, init) => {
    if (u.startsWith('/api/host/readiness/fix') && init?.method === 'POST') return { body: { message: 'Started: brew install ffmpeg.', report: report(), job: { id: 'j1', action: 'brew_install', label: 'Installing ffmpeg with Homebrew', state: 'running', started: 1, tail: ['$ /opt/homebrew/bin/brew install ffmpeg'] } } }
    if (u === '/api/host/readiness/job') { polls++; return { body: { job: { id: 'j1', action: 'brew_install', label: 'Installing ffmpeg with Homebrew', state: polls < 2 ? 'running' : 'done', exit: polls < 2 ? null : 0, started: 1, tail: ['==> Pouring ffmpeg'] } } } }
    if (u.startsWith('/api/host/readiness') && !init?.method) { reads++; return { body: report() } }
    return undefined
  })
  const w = mount(HostReadinessPanel, { attachTo: document.body, global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } } })
  await flushPromises()
  expect(w.findAll('button').map(b => b.text())).toEqual(expect.arrayContaining(['Install ffmpeg with Homebrew', 'Update tools with Homebrew']))
  await w.findAll('button').find(b => b.text() === 'Install ffmpeg with Homebrew')!.trigger('click'); await flushPromises()
  expect(JSON.parse(String(calls(f, 'POST', '/api/host/readiness/fix')[0]![1]?.body))).toEqual({ action: 'brew_install', tool: 'ffmpeg' })
  expect(w.get('[data-testid=job]').text()).toContain('Installing ffmpeg with Homebrew')
  expect(w.findAll('button').find(b => b.text() === 'Install ffmpeg with Homebrew')!.attributes('disabled')).toBeDefined()   // one job at a time
  const before = reads
  await vi.advanceTimersByTimeAsync(2600); await flushPromises()
  expect(w.get('[data-testid=job]').text()).toContain('running')
  await vi.advanceTimersByTimeAsync(2600); await flushPromises()
  expect(w.get('[data-testid=job]').text()).toContain('finished'); expect(w.text()).toContain('Finished: Installing ffmpeg with Homebrew.')
  expect(reads).toBeGreaterThan(before)                                                                                          // the report is read again when the job ends
  expect(w.emitted('changed')!.length).toBeGreaterThanOrEqual(2)
  w.unmount(); vi.useRealTimers()
})
it('shows a failed job with its exit code and keeps the log', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const report = () => ({ ready_to_build: true, ready_to_deliver: false, note: '', checks: [check({ id: 'tools', label: 'Optional tools', status: 'info', detail: 'x', fix: { action: 'brew_update', label: 'Update tools with Homebrew' }, tools: [] })] })
  stubFetch((u, init) => {
    if (u.startsWith('/api/host/readiness/fix') && init?.method === 'POST') return { body: { message: 'Started.', report: report(), job: { id: 'j2', action: 'brew_update', label: 'Updating Homebrew tools', state: 'running', started: 1, tail: [] } } }
    if (u === '/api/host/readiness/job') return { body: { job: { id: 'j2', action: 'brew_update', label: 'Updating Homebrew tools', state: 'failed', exit: 1, started: 1, tail: ['Error: network down'] } } }
    if (u.startsWith('/api/host/readiness')) return { body: report() }
    return undefined
  })
  const w = mount(HostReadinessPanel, { attachTo: document.body, global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
  await flushPromises()
  await w.findAll('button').find(b => b.text() === 'Update tools with Homebrew')!.trigger('click'); await flushPromises()
  await vi.advanceTimersByTimeAsync(2600); await flushPromises()
  expect(w.get('[role=alert]').text()).toContain('failed (exit 1)'); expect(w.get('[data-testid=job] pre').text()).toContain('Error: network down')
  w.unmount(); vi.useRealTimers()
})
