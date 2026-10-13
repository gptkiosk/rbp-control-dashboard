import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import McpView from '@/views/McpView.vue'
import RequestServerDialog from '@/components/RequestServerDialog.vue'
import type { McpAgentServers, McpChange, McpServer } from '@/lib/api'
import { calls, headerOf, stubFetch, type Reply } from './helpers'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

function srv(over: Partial<McpServer> = {}): McpServer {
  return {
    name: 'headroom', target: 'headroom mcp serve', transport: 'stdio', status: '✔ Connected', enabled: true,
    source: 'Claude Code config', removable: true, ...over,
  }
}

function change(over: Partial<McpChange> = {}): McpChange {
  return {
    id: 1, agent: 'codex', action: 'add', name: 'files',
    spec: { transport: 'stdio', command: 'npx', args: ['-y', 'files-mcp'], url: null, env_names: ['FILES_TOKEN'] },
    status: 'pending', output: null, note: null, created_at: 1_000, decided_at: null, ...over,
  }
}

const AGENTS: McpAgentServers[] = [
  {
    agent: 'claude',
    servers: [
      srv(),
      srv({ name: 'claude.ai Gmail', target: 'https://gmailmcp.example/mcp', transport: 'http', source: 'claude.ai account', removable: false }),
      srv({ name: 'flaky', status: '✘ Failed to connect' }),
    ],
    error: null,
    checked_at: 1_000,
  },
  {
    agent: 'codex',
    servers: [srv({ name: 'off', status: 'disabled', enabled: false, source: 'Codex config', env_names: ['A_KEY', 'B_KEY'] }), srv({ name: 'on', status: 'enabled' })],
    error: null,
    checked_at: 1_000,
  },
  { agent: 'hermes', servers: [], error: null, checked_at: 1_000 },
  { agent: 'openclaw', servers: [], error: 'openclaw config unreadable', checked_at: null },
]

function server(initial: { changes?: McpChange[]; envNames?: string[] } = {}) {
  const state = { changes: initial.changes ?? [], envNames: initial.envNames ?? [] }
  const extra: { handler?: (u: string, init?: RequestInit) => Reply | undefined } = {}
  const f = stubFetch((u, init) => {
    const own = extra.handler?.(u, init)
    if (own) return own
    const method = init?.method ?? 'GET'
    if (method === 'GET' && u.startsWith('/api/mcp/servers')) return { body: { agents: AGENTS } }
    if (method === 'GET' && u === '/api/mcp/changes') return { body: { changes: state.changes } }
    if (method === 'GET' && u === '/api/mcp/env-names') return { body: { names: state.envNames } }
    return undefined
  })
  return { state, f, on: (h: NonNullable<typeof extra.handler>) => (extra.handler = h) }
}

async function mountMcp(s: ReturnType<typeof server>) {
  const w = mount(McpView, { attachTo: document.body })
  await flushPromises()
  return { w, ...s }
}

describe('MCP view', () => {
  it('renders one section per agent with the standing rule and the right status chips', async () => {
    const { w, f } = await mountMcp(server())
    expect(w.get('[data-testid="mcp-note"]').text()).toBe(
      "Changes are requests. Nothing is written to an agent's configuration until you approve it.",
    )
    expect(calls(f, 'GET', '/api/mcp/servers?refresh=false')).toHaveLength(1)
    const sections = w.findAll('section.card[data-agent]')
    expect(sections.map((s) => s.get('h2').text())).toEqual(['Claude Code', 'Codex', 'Hermes', 'OpenClaw'])

    const claude = sections[0]!
    expect(claude.findAll('tbody tr')).toHaveLength(3)
    const headroom = claude.get('[data-server="headroom"]')
    expect(headroom.text()).toContain('headroom mcp serve')
    expect(headroom.text()).toContain('stdio')
    expect(headroom.text()).toContain('Claude Code config')
    const tone = (el: ReturnType<typeof claude.get>) => el.get('.chip').attributes('data-tone')
    expect(tone(headroom)).toBe('ok')
    expect(tone(claude.get('[data-server="flaky"]'))).toBe('danger')

    const codex = sections[1]!
    expect(tone(codex.get('[data-server="off"]'))).toBe('warn')
    expect(tone(codex.get('[data-server="on"]'))).toBe('ok')
    expect(codex.get('[data-server="off"]').text()).toContain('2 environment variables')

    expect(sections[2]!.text()).toContain('No MCP servers configured')
    expect(sections[3]!.get('[data-testid="agent-error"]').text()).toBe('openclaw config unreadable')
    w.unmount()
  })

  it('labels a claude.ai connector "Managed in claude.ai" with no Remove button', async () => {
    const { w } = await mountMcp(server())
    const gmail = w.get('[data-server="claude.ai Gmail"]')
    expect(gmail.text()).toContain('Managed in claude.ai')
    expect(gmail.find('button').exists()).toBe(false)
    expect(w.get('[data-server="headroom"]').find('button[aria-label="Remove headroom from Claude Code"]').exists()).toBe(true)
    w.unmount()
  })

  it('Remove creates a remove change request (and does not touch the server list)', async () => {
    const s = server()
    s.on((u, init) =>
      u === '/api/mcp/changes' && init?.method === 'POST'
        ? { status: 201, body: change({ id: 5, agent: 'claude', action: 'remove', name: 'headroom', spec: { transport: null, command: null, args: null, url: null, env_names: null } }) }
        : undefined,
    )
    const { w, f } = await mountMcp(s)
    await w.get('button[aria-label="Remove headroom from Claude Code"]').trigger('click')
    await flushPromises()

    const post = calls(f, 'POST', '/api/mcp/changes')
    expect(post).toHaveLength(1)
    expect(headerOf(post[0]![1], 'X-Mac-Control')).toBe('1')
    expect(JSON.parse(String(post[0]![1]?.body))).toEqual({ agent: 'claude', action: 'remove', name: 'headroom' })
    expect(w.get('[data-testid="mcp-notice"]').text()).toContain('nothing has been removed yet')
    w.unmount()
  })

  it('Refresh asks for ?refresh=true and shows a busy state until it answers', async () => {
    const { w, f } = await mountMcp(server())
    // Hold only the refresh response open so the busy state can be observed.
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const base = f.getMockImplementation()!
    f.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/mcp/servers?refresh=true') await gate
      return base(url, init)
    })

    await w.findAll('button').find((b) => b.text() === 'Refresh')!.trigger('click')
    expect(calls(f, 'GET', '/api/mcp/servers?refresh=true')).toHaveLength(1)
    const busy = w.findAll('button').find((b) => b.text().includes('Checking servers'))!
    expect(busy.attributes('disabled')).toBeDefined()
    expect(busy.get('svg').classes()).toContain('spin')
    expect(w.text()).toContain('This can take several seconds')

    release()
    await flushPromises()
    expect(w.text()).not.toContain('Checking servers')
    expect(w.findAll('button').find((b) => b.text() === 'Refresh')!.attributes('disabled')).toBeUndefined()
    w.unmount()
  })

  it('shows a pending change with Approve and Reject, and approving calls /approve after confirm', async () => {
    const s = server({ changes: [change()] })
    s.on((u, init) => {
      if (u === '/api/mcp/changes/1/approve' && init?.method === 'POST') {
        s.state.changes = [change({ status: 'applied', decided_at: 1_010, output: 'Added MCP server files to codex' })]
        return { body: s.state.changes[0] }
      }
      return undefined
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { w, f } = await mountMcp(s)

    const item = w.get('[data-change-id="1"]')
    expect(item.get('[data-testid="change-status"]').attributes('data-tone')).toBe('warn')
    expect(item.get('[data-testid="change-spec"]').text()).toContain('npx -y files-mcp')
    expect(item.get('[data-testid="change-env"]').text()).toContain('FILES_TOKEN')
    expect(item.findAll('button').map((b) => b.text())).toEqual(['Approve', 'Reject'])

    await item.findAll('button')[0]!.trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(1)
    const question = String(confirm.mock.calls[0]![0])
    expect(question).toContain('Add the MCP server "files"')
    expect(question).toContain('npx -y files-mcp')
    expect(question).toContain('FILES_TOKEN')
    expect(question).toContain("Codex's configuration")

    const approve = calls(f, 'POST', '/api/mcp/changes/1/approve')
    expect(approve).toHaveLength(1)
    expect(headerOf(approve[0]![1], 'X-Mac-Control')).toBe('1')

    const done = w.get('[data-change-id="1"]')
    expect(done.get('[data-testid="change-status"]').attributes('data-tone')).toBe('ok')
    expect(done.findAll('button')).toHaveLength(0)
    expect(done.get('[data-testid="change-output"]').text()).toBe('Added MCP server files to codex')
    w.unmount()
  })

  it('does not approve when the confirm is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { w, f } = await mountMcp(server({ changes: [change()] }))
    await w.get('[data-change-id="1"] button').trigger('click')
    await flushPromises()
    expect(calls(f, 'POST', '/api/mcp/changes/1/approve')).toHaveLength(0)
    w.unmount()
  })

  it('Reject calls /reject; statuses use the right tones; failed output is open', async () => {
    const s = server({
      changes: [
        change({ id: 4, status: 'failed', output: 'boom: exit 1', decided_at: 1_020 }),
        change({ id: 3, status: 'rejected', decided_at: 1_015 }),
        change({ id: 1 }),
      ],
    })
    s.on((u, init) => {
      if (u === '/api/mcp/changes/1/reject' && init?.method === 'POST') return { body: change({ id: 1, status: 'rejected', decided_at: 1_030 }) }
      return undefined
    })
    const { w, f } = await mountMcp(s)
    const tones = w.findAll('[data-testid="change-status"]').map((c) => c.attributes('data-tone'))
    expect(tones).toEqual(['danger', 'muted', 'warn'])
    expect(w.get('[data-change-id="4"] details').attributes('open')).toBeDefined()
    expect(w.get('[data-change-id="4"]').text()).toContain('boom: exit 1')

    await w.findAll('[data-change-id="1"] button')[1]!.trigger('click')
    await flushPromises()
    expect(calls(f, 'POST', '/api/mcp/changes/1/reject')).toHaveLength(1)
    w.unmount()
  })
})

describe('Request a server dialog', () => {
  async function open(envNames: string[] = ['GITHUB_TOKEN', 'OPENAI_KEY']) {
    const f = stubFetch((u, init) => {
      if (u === '/api/mcp/env-names') return { body: { names: envNames } }
      if (u === '/api/mcp/changes' && init?.method === 'POST') return { status: 201, body: change({ id: 9 }) }
      return undefined
    })
    const w = mount(RequestServerDialog, { attachTo: document.body })
    await flushPromises()
    return { w, f }
  }

  it('posts transport, command, args (one per line) and env_names for stdio', async () => {
    const { w, f } = await open()
    await w.get('#rs-agent-native').setValue('codex')
    await w.get('#rs-name').setValue(' files ')
    await w.get('#rs-command').setValue('npx')
    await w.get('#rs-args').setValue('-y\n\n  files-mcp  \r\n--root=/tmp\n')
    await w.get('input[value="GITHUB_TOKEN"]').setValue(true)
    await w.get('#rs-note').setValue('for the docs')
    await w.get('form').trigger('submit')
    await flushPromises()

    const post = calls(f, 'POST', '/api/mcp/changes')[0]!
    expect(headerOf(post[1], 'X-Mac-Control')).toBe('1')
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      agent: 'codex', action: 'add', name: 'files', transport: 'stdio', command: 'npx',
      args: ['-y', 'files-mcp', '--root=/tmp'], env_names: ['GITHUB_TOKEN'], note: 'for the docs',
    })
    expect(w.emitted('created')).toHaveLength(1)
    w.unmount()
  })

  it('sends only the url (no command, args or env) in http mode', async () => {
    const { w, f } = await open()
    await w.get('#rs-name').setValue('remote')
    await w.get('input[value="http"]').setValue(true)
    expect(w.find('#rs-command').exists()).toBe(false)
    await w.get('#rs-url').setValue('https://example.com/mcp')
    await w.get('form').trigger('submit')
    await flushPromises()
    expect(JSON.parse(String(calls(f, 'POST', '/api/mcp/changes')[0]![1]?.body))).toEqual({
      agent: 'claude', action: 'add', name: 'remote', transport: 'http', url: 'https://example.com/mcp',
    })
    w.unmount()
  })

  it('explains the .env file when there are no variable names, and shows a 422 inline', async () => {
    const f = stubFetch((u, init) => {
      if (u === '/api/mcp/env-names') return { body: { names: [] } }
      if (u === '/api/mcp/changes' && init?.method === 'POST') return { status: 422, body: { detail: 'name already exists' } }
      return undefined
    })
    const w = mount(RequestServerDialog, { attachTo: document.body })
    await flushPromises()
    expect(w.get('[data-testid="env-empty"]').text()).toContain('~/.mac-control/.env')
    expect(w.get('[data-testid="env-empty"]').text()).toContain('KEY=value')
    await w.get('#rs-name').setValue('x')
    await w.get('#rs-command').setValue('y')
    await w.get('form').trigger('submit')
    await flushPromises()
    expect(w.get('[data-testid="submit-error"]').text()).toBe('name already exists')
    expect(w.emitted('created')).toBeUndefined()
    expect(f).toBeDefined()
    w.unmount()
  })
})
