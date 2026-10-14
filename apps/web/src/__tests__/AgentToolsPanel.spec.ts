import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import AgentToolsPanel from '@/components/AgentToolsPanel.vue'
import { calls, stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })

const LOGIN = {
  'claude-code': 'claude auth login', codex: 'codex login --device-auth', openclaw: 'openclaw onboard', hermes: 'hermes model', grok: 'grok login --device-code',
}
const tool = (id: string, name: string, over: Record<string, unknown> = {}) => ({
  id, name, pinned_version: '1.0.0', installed: false, installed_version: null, previous_version: null, installed_at: null,
  size_mb: 400, commands: [id], requires: ['node'], login: { command: LOGIN[id as keyof typeof LOGIN], note: `Sign in to ${name}.` }, path: null,
  actions: { install: [], update: null, remove: null, rollback: null }, ...over,
})
const status = (over: Record<string, unknown> = {}, tools = [tool('claude-code', 'Claude Code'), tool('codex', 'Codex CLI'), tool('openclaw', 'OpenClaw'), tool('hermes', 'Hermes'), tool('grok', 'Grok Build')]) => ({
  product: 'rcd', platform: 'linux-arm64', root: '/home/pi/.local/share/rcd-agent-tools', tools, runtimes: [],
  host: { os: 'Raspberry Pi OS', machine: 'aarch64', bits: 64, disk_free_mb: 20480, mem_total_mb: 3880, mem_available_mb: 3000 },
  system_packages: { apt_command: null, missing_required: [], missing_recommended: [], details: {}, note: '' },
  tx: null, last: null, running: false, log: [], notes: { hermes: 'Hermes installs its own toolchain.' }, catalog_checked: '2026-10-13', ...over,
})
const plan = (over: Record<string, unknown> = {}) => ({
  tool: 'codex', name: 'Codex CLI', action: 'install', from: null, to: '0.162.1', plan_sha256: 'f'.repeat(64),
  commands: ['download https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-arm64.tar.xz (29.4 MB) and check its sha256 6ad1325edbdb5649…', '/home/pi/.local/share/rcd-agent-tools/tools/node/current/bin/npm ci --ignore-scripts --no-audit --no-fund --no-progress --loglevel=error'],
  downloads: [{ url: 'https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-arm64.tar.xz', sha256: '6ad1325e'.padEnd(64, '0'), size: 30843004 }],
  runtimes: [{ id: 'node', name: 'Node.js', version: '24.21.0', action: 'install', from: null }], removes: [],
  unchanged: ['Dispatch routes and the free-only setting', 'Billing mode and prices'], login: { command: 'codex login --device-auth', note: 'x' },
  system_packages: { apt_command: null, missing_required: [], missing_recommended: [], note: '' },
  disk: { free_mb: 20480, required_mb: 620, min_free_mb: 2048, headroom_mb: 512 }, memory: { total_mb: 3880, available_mb: 3000, recommended_mb: 4096 },
  host: { os: 'Raspberry Pi OS', machine: 'aarch64', bits: 64 }, refusals: [], warnings: [], ...over,
})
const stubs = { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } }
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll('button').find(b => b.text() === text)!
const tick = async (ms = 0) => { await vi.advanceTimersByTimeAsync(ms); await nextTick() }

it('lists the five tools with Install buttons that show the pinned version, and starts nothing on its own', async () => {
  const f = stubFetch(url => url === '/api/agent-installs' ? { body: status() } : undefined)
  const w = mount(AgentToolsPanel, stubs); await flushPromises()
  expect(w.findAll('[data-tool]').map(e => e.attributes('data-tool'))).toEqual(['claude-code', 'codex', 'openclaw', 'hermes', 'grok'])
  expect(w.findAll('button').map(b => b.text())).toEqual(['Install 1.0.0', 'Install 1.0.0', 'Install 1.0.0', 'Install 1.0.0', 'Install 1.0.0'])
  expect(w.get('[data-test="host"]').text()).toContain('3.8 GB memory')
  expect(w.get('[data-test="host"]').text()).toContain('20.0 GB free disk')
  expect(f.mock.calls.map(([url, init]) => `${init?.method ?? 'GET'} ${url}`)).toEqual(['GET /api/agent-installs'])
  expect(w.text()).toContain('nothing here signs in to a tool or touches a key')
  w.unmount()
})

it('shows the confirmation with versions, sources, commands, disk, memory and what stays unchanged before anything runs', async () => {
  const f = stubFetch((url, init) => {
    if (url === '/api/agent-installs') return { body: status() }
    if (url === '/api/agent-installs/plan' && init?.method === 'POST') return { body: plan() }
    return undefined
  })
  const w = mount(AgentToolsPanel, stubs); await flushPromises()
  await w.get('[data-tool="codex"] [data-action="install"]').trigger('click'); await flushPromises()
  expect(JSON.parse(calls(f, 'POST', '/api/agent-installs/plan')[0]![1]!.body as string)).toEqual({ tool: 'codex', action: 'install' })
  const c = w.get('[data-test="confirm"]').text()
  expect(c).toContain('Install Codex CLI 0.162.1')
  expect(c).toContain('not installed → 0.162.1')
  expect(c).toContain('Node.js 24.21.0 (will be installed)')
  expect(c).toContain('npm ci --ignore-scripts')
  expect(c).toContain('https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-arm64.tar.xz')
  expect(c).toContain('20.0 GB free')
  expect(c).toContain('3.8 GB total')
  expect(c).toContain('Dispatch routes and the free-only setting')
  expect(c).toContain('codex login --device-auth')
  expect(calls(f, 'POST', '/api/agent-installs/run')).toHaveLength(0)
  expect(button(w, 'Install Codex CLI').attributes('disabled')).toBeDefined()   // needs the checkbox first
  w.unmount()
})

it('runs only the plan that was shown, after the checkbox, and reports the outcome', async () => {
  vi.useFakeTimers()
  let phase = 0
  const f = stubFetch((url, init) => {
    if (url === '/api/agent-installs/plan') return { body: plan() }
    if (url === '/api/agent-installs/run') return { status: 202, body: { started: 'install codex' } }
    if (url === '/api/agent-installs') {
      phase++
      if (phase === 1) return { body: status() }
      if (phase === 2) return { body: status({ tx: { id: 't', tool: 'codex', action: 'install', phase: 'installing the pinned npm packages' }, running: true }) }
      return { body: status({ last: { tx: 't', tool: 'codex', action: 'install', outcome: 'done', detail: 'Installed Codex CLI 0.162.1.' } }, [
        tool('claude-code', 'Claude Code'), tool('codex', 'Codex CLI', { installed: true, installed_version: '0.162.1', path: '/x/bin/codex', actions: { install: null, update: null, remove: [], rollback: null } }), tool('openclaw', 'OpenClaw'), tool('hermes', 'Hermes'), tool('grok', 'Grok Build')]) }
    }
    return undefined
  })
  const w = mount(AgentToolsPanel, stubs); await tick()
  await w.get('[data-tool="codex"] [data-action="install"]').trigger('click'); await tick()
  await w.get('input[type="checkbox"]').setValue(true)
  await button(w, 'Install Codex CLI').trigger('click'); await tick()
  expect(JSON.parse(calls(f, 'POST', '/api/agent-installs/run')[0]![1]!.body as string)).toEqual({
    tool: 'codex', action: 'install', plan_sha256: 'f'.repeat(64), confirm: true })
  await tick(3000)
  expect(w.get('[data-test="progress"]').text()).toContain('Install Codex CLI: installing the pinned npm packages.')
  await tick(3000)
  expect(w.find('[data-test="progress"]').exists()).toBe(false)
  expect(w.text()).toContain('Installed Codex CLI 0.162.1.')
  expect(w.text()).toContain('Installed 0.162.1')
  // the sign-in command is shown for the operator to run; the panel never runs it
  const login = w.get('[data-login="codex"]')
  expect(login.text()).toContain('codex login --device-auth')
  expect(login.text()).toContain('Private credentials')
  expect(calls(f, 'POST', '/api/agent-installs').map(([url]) => url)).toEqual(['/api/agent-installs/plan', '/api/agent-installs/run'])
  w.unmount()
})

it('turns every button off, with the reasons, when the host is refused', async () => {
  const reason = 'This is a 32-bit operating system (machine armv7l, 32-bit userland). These tools need 64-bit Raspberry Pi OS (aarch64).'
  const refused = ['claude-code', 'codex', 'openclaw', 'hermes', 'grok'].map(id => tool(id, id, { actions: { install: [reason, 'Only 1500 MB of disk is free where the tools are installed; at least 2048 MB is needed.'], update: null, remove: null, rollback: null } }))
  stubFetch(url => url === '/api/agent-installs' ? { body: status({}, refused) } : undefined)
  const w = mount(AgentToolsPanel, stubs); await flushPromises()
  expect(w.findAll('button').every(b => b.attributes('disabled') !== undefined)).toBe(true)
  expect(w.text()).toContain('32-bit operating system')
  expect(w.text()).toContain('at least 2048 MB is needed')
  w.unmount()
})

it('cannot confirm a plan that carries a refusal', async () => {
  const f = stubFetch((url, init) => {
    if (url === '/api/agent-installs') return { body: status() }
    if (url === '/api/agent-installs/plan') return { body: plan({ refusals: ['Only 1900 MB of disk is free where the tools are installed; at least 2048 MB is needed.'] }) }
    return undefined
  })
  const w = mount(AgentToolsPanel, stubs); await flushPromises()
  await w.get('[data-tool="codex"] [data-action="install"]').trigger('click'); await flushPromises()
  expect(w.get('[data-test="confirm"]').text()).toContain('at least 2048 MB is needed')
  expect(w.get('input[type="checkbox"]').attributes('disabled')).toBeDefined()
  expect(button(w, 'Install Codex CLI').attributes('disabled')).toBeDefined()
  expect(calls(f, 'POST', '/api/agent-installs/run')).toHaveLength(0)
  w.unmount()
})

it('offers Update, Roll back and Remove for an installed tool and names the version kept for roll back', async () => {
  const installed = tool('codex', 'Codex CLI', { installed: true, installed_version: '0.162.0', previous_version: '0.161.0', pinned_version: '0.162.1', path: '/x/bin/codex',
    actions: { install: null, update: [], remove: [], rollback: [] } })
  stubFetch(url => url === '/api/agent-installs' ? { body: status({}, [installed]) } : undefined)
  const w = mount(AgentToolsPanel, stubs); await flushPromises()
  expect(w.findAll('button').map(b => b.text()).filter(t => !t.startsWith('Copy'))).toEqual(['Upgrade 0.162.1', 'Roll back to 0.161.0', 'Remove'])
  expect(w.get('[data-test="state"]').text()).toContain('Installed 0.162.0. Latest verified: 0.162.1.')
  w.unmount()
})

it('shows the optional system packages as one copyable command and never offers to run it', async () => {
  stubFetch(url => url === '/api/agent-installs' ? { body: status({ system_packages: { apt_command: 'sudo apt install -y build-essential ffmpeg ripgrep', missing_required: [], missing_recommended: ['build-essential', 'ffmpeg', 'ripgrep'], details: { ripgrep: 'fast code search' }, note: 'n' } }) } : undefined)
  const w = mount(AgentToolsPanel, stubs); await flushPromises()
  expect(w.get('[data-test="apt"]').text()).toContain('sudo apt install -y build-essential ffmpeg ripgrep')
  expect(w.text()).toContain('The dashboard never runs this command')
  expect(w.findAll('button').map(b => b.text()).filter(t => /run|execute/i.test(t))).toEqual([])
  w.unmount()
})

it('says the operator must sign in when the API refuses, and shows a refusal from the host', async () => {
  stubFetch(() => ({ status: 403, body: { detail: 'Operator sign-in is required.' } }))
  const w = mount(AgentToolsPanel, stubs); await flushPromises()
  expect(w.text()).toContain('Operator sign-in is required to see or change agent tools.')
  expect(w.findAll('button')).toHaveLength(0)
  w.unmount()
})

it('shows a plan that changed since it was confirmed as a refusal and starts nothing', async () => {
  stubFetch((url, init) => {
    if (url === '/api/agent-installs') return { body: status() }
    if (url === '/api/agent-installs/plan') return { body: plan() }
    if (url === '/api/agent-installs/run') return { status: 409, body: { detail: { message: 'The plan changed since you confirmed it. Open the confirmation again.', problems: [] } } }
    return undefined
  })
  const w = mount(AgentToolsPanel, stubs); await flushPromises()
  await w.get('[data-tool="codex"] [data-action="install"]').trigger('click'); await flushPromises()
  await w.get('input[type="checkbox"]').setValue(true)
  await button(w, 'Install Codex CLI').trigger('click'); await flushPromises()
  expect(w.text()).toContain('The plan changed since you confirmed it.')
  expect(w.find('[data-test="progress"]').exists()).toBe(false)
  w.unmount()
})


it('recognizes native installs and offers only a reviewed upgrade, leaving Grok installable', async () => {
 const native=tool('codex','Codex CLI',{installed:true,installation_source:'native',installed_version:'0.162.0',pinned_version:'0.162.1',path:'/native/codex',actions:{install:null,update:[],remove:null,rollback:null}})
 stubFetch(url=>url==='/api/agent-installs'?{body:status({},[native,tool('grok','Grok Build')])}:undefined)
 const w=mount(AgentToolsPanel,stubs);await flushPromises()
 expect(w.text()).toContain('Installed 0.162.0 (native). Latest verified: 0.162.1.')
 expect(button(w,'Upgrade 0.162.1').exists()).toBe(true)
 expect(button(w,'Install 1.0.0').exists()).toBe(true)
 expect(w.findAll('button').some(b=>b.text()==='Remove')).toBe(false)
 w.unmount()
})

it('resumes an existing helper, updates its log, retries a failed read and retains the final log', async () => {
  vi.useFakeTimers()
  let reads = 0
  const f = stubFetch(url => {
    if (url !== '/api/agent-installs') return undefined
    reads++
    if (reads === 2) return { status: 503, body: { detail: 'Temporary connection failure' } }
    if (reads < 4) return { body: status({tx:{id:'existing',tool:'hermes',action:'install',phase:'installing'},running:true,log:[reads === 1 ? 'Starting Hermes' : 'Installing dependencies']}) }
    return {body:status({log:['Hermes installation complete'],last:{tx:'existing',tool:'hermes',action:'install',outcome:'done',detail:'Installed Hermes.'}})}
  })
  const w = mount(AgentToolsPanel, stubs); await tick()
  expect(w.get('.log').text()).toContain('Starting Hermes')
  await tick(3000)
  expect(w.text()).toContain('Retrying automatically')
  await tick(3000)
  expect(w.get('.log').text()).toContain('Installing dependencies')
  await tick(3000)
  expect(w.text()).toContain('Installed Hermes.')
  expect(w.get('.log').text()).toContain('Hermes installation complete')
  expect(w.find('[data-test="progress"]').exists()).toBe(false)
  expect(calls(f, 'POST', '/api/agent-installs/run')).toHaveLength(0)
  w.unmount()
  const stopped = reads; await tick(15000); expect(reads).toBe(stopped)
})
