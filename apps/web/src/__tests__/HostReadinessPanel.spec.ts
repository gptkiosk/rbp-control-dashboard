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
  check({ id: 'tools', label: 'Optional tools', status: 'info', detail: 'Missing: docker.', tools: [{ id: 'docker', installed: false, needed_for: 'containers' }] }),
] })
function setup(extra?: (u: string, init?: RequestInit) => { status?: number; body: unknown } | undefined) {
  const f = stubFetch((u, init) => (u.startsWith('/api/host/readiness') && !init?.method ? { body: bare() } : extra?.(u, init)))
  return { f, w: mount(HostReadinessPanel, { attachTo: document.body }) }
}
it('lists each check with its state, shows builders versus managers, and offers one named fix per gap', async () => {
  const { w } = setup(); await flushPromises()
  expect(w.get('[data-testid=readiness-summary]').text()).toContain('Ready to build: not yet')
  expect(w.get('[data-check=workspace]').text()).toContain('needs attention')
  expect(w.get('[data-check=agents]').text()).toContain('openclaw (not installed)')
  expect(w.get('[data-check=agents]').text()).toContain('hermes · manager')
  expect(w.get('[data-check=tools]').text()).toContain('docker (missing)')
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
