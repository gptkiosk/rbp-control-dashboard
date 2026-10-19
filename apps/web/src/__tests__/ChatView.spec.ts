import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import ChatView from '@/views/ChatView.vue'
import NewChatDialog from '@/components/NewChatDialog.vue'
import type { ChatMessage, ChatThread, ChatThreadDetail } from '@/lib/api'
import { agent, calls, headerOf, stubFetch, type Reply } from './helpers'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

function thread(over: Partial<ChatThread> = {}): ChatThread {
  return {
    id: 1, agent: 'hermes', agent_target: null, title: 'Live memory test', model: null, mode: 'read',
    working_dir: '/ws/scratch', session_id: null, created_at: 1_000, last_activity_at: 1_100, busy: false,
    last_message: { role: 'assistant', text: 'PELICAN', status: 'done' }, ...over,
  }
}

function msg(over: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 1, thread_id: 1, role: 'assistant', text: 'Hello', status: 'done', approval_reasons: [], approved_at: null,
    run_id: null, model: null, input_tokens: null, output_tokens: null, cost_usd: null, duration_s: null,
    created_at: 1_000, ...over,
  }
}

/** A tiny in-memory chat server: tests mutate `state` and the stub answers from it. */
function server(initial: { threads?: ChatThread[]; messages?: ChatMessage[] } = {}) {
  const state = {
    threads: initial.threads ?? [thread()],
    messages: initial.messages ?? [],
  }
  const detail = (id: number): ChatThreadDetail | null => {
    const t = state.threads.find((x) => x.id === id)
    return t ? { ...t, messages: state.messages.filter((m) => m.thread_id === id) } : null
  }
  const extra: { handler?: (u: string, init?: RequestInit) => Reply | undefined } = {}
  const f = stubFetch((u, init) => {
    const own = extra.handler?.(u, init)
    if (own) return own
    const method = init?.method ?? 'GET'
    if (method === 'GET' && u === '/api/chat/threads') return { body: { threads: state.threads } }
    const one = /^\/api\/chat\/threads\/(\d+)$/.exec(u)
    if (method === 'GET' && one) {
      const d = detail(Number(one[1]))
      return d ? { body: d } : { status: 404, body: { detail: 'no such thread' } }
    }
    if (method === 'GET' && u.startsWith('/api/runs/')) {
      return { body: { text: 'reading the repo\n', next_offset: 17, done: false, stage: 'running' } }
    }
    return undefined
  })
  return { state, f, on: (h: NonNullable<typeof extra.handler>) => (extra.handler = h) }
}

async function mountChat(srv: ReturnType<typeof server>, url = '/chat') {
  const router = createAppRouter(createMemoryHistory())
  router.push(url)
  await router.isReady()
  const w = mount(ChatView, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return { w, router, ...srv }
}

describe('Chat view', () => {
  it('lists threads with agent chip, Coordinator chip, preview and a busy dot', async () => {
    const srv = server({
      threads: [
        thread(),
        thread({ id: 2, agent: 'claude', title: 'Refactor', busy: true, last_message: { role: 'user', text: 'do it', status: 'running' } }),
      ],
    })
    const { w } = await mountChat(srv)
    const items = w.findAll('.thread')
    expect(items).toHaveLength(2)
    expect(items[0]!.text()).toContain('Live memory test')
    expect(items[0]!.text()).toContain('Hermes')
    expect(items[0]!.text()).toContain('Coordinator')
    expect(items[0]!.text()).toContain('PELICAN')
    expect(items[0]!.find('[data-testid="busy-dot"]').exists()).toBe(false)
    expect(items[1]!.text()).not.toContain('Coordinator')
    expect(items[1]!.text()).toContain('You: do it')
    expect(items[1]!.find('[data-testid="busy-dot"]').exists()).toBe(true)
    expect(w.text()).toContain('New chat')
    w.unmount()
  })

  it('opens a thread: messages, model/tokens meta, and "not reported" for nulls', async () => {
    const srv = server({
      messages: [
        msg({ id: 1, role: 'user', text: 'What is the secret word?' }),
        msg({ id: 2, text: 'PELICAN', model: 'claude-x', input_tokens: 1234, output_tokens: 56, cost_usd: 0.0123, duration_s: 3.7 }),
        msg({ id: 3, text: 'Again', model: null, input_tokens: null, output_tokens: null, cost_usd: null, duration_s: null }),
      ],
    })
    const { w, router } = await mountChat(srv)
    await w.get('[data-thread-id="1"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.thread).toBe('1')
    expect(w.get('h2').text()).toBe('Live memory test')
    expect(w.get('[data-testid="session-id"]').text()).toBe('new session')
    expect(w.get('[data-testid="working-dir"]').text()).toBe('/ws/scratch')
    expect(w.text()).toContain('default')

    const bubbles = w.findAll('article.msg')
    expect(bubbles.map((b) => b.attributes('data-role'))).toEqual(['user', 'assistant', 'assistant'])
    expect(bubbles[0]!.find('[data-testid="message-meta"]').exists()).toBe(false)

    const full = bubbles[1]!.get('[data-testid="message-meta"]').text()
    expect(full).toContain('claude-x')
    expect(full).toContain('1,234')
    expect(full).toContain('56')
    expect(full).toContain('$0.0123')
    expect(full).toContain('3.7 s')
    expect(full).not.toContain('not reported')

    const empty = bubbles[2]!.get('[data-testid="message-meta"]')
    expect(empty.findAll('[data-missing="true"]')).toHaveLength(5)
    expect(empty.text()).toContain('not reported')
    w.unmount()
  })

  it('opens the thread from a deep link (?thread=)', async () => {
    const srv = server({ messages: [msg({ id: 1, text: 'deep linked' })] })
    const { w } = await mountChat(srv, '/chat?thread=1')
    expect(w.text()).toContain('deep linked')
    expect(w.get('[data-thread-id="1"]').attributes('aria-current')).toBe('true')
    w.unmount()
  })

  it('sends the text with the guard header and clears the composer', async () => {
    const srv = server()
    srv.on((u, init) => {
      if (u === '/api/chat/threads/1/messages' && init?.method === 'POST') {
        const m = msg({ id: 7, role: 'user', text: 'hello agent', status: 'done' })
        srv.state.messages.push(m)
        return { status: 201, body: m }
      }
      return undefined
    })
    const { w, f } = await mountChat(srv, '/chat?thread=1')
    await w.get('#composer-text').setValue('  hello agent ')
    await w.get('form.composer').trigger('submit')
    await flushPromises()

    const post = calls(f, 'POST', '/api/chat/threads/1/messages')[0]!
    expect(headerOf(post[1], 'X-Mac-Control')).toBe('1')
    expect(JSON.parse(String(post[1]?.body))).toEqual({ text: 'hello agent' })
    expect((w.get('#composer-text').element as HTMLTextAreaElement).value).toBe('')
    expect(w.text()).toContain('hello agent')
    w.unmount()
  })

  it('shows reasons and Approve for a pending_approval reply, and Approve calls the endpoint', async () => {
    const srv = server()
    srv.on((u, init) => {
      if (u === '/api/chat/threads/1/messages' && init?.method === 'POST') {
        const m = msg({
          id: 9, role: 'user', text: 'rm -rf the build dir', status: 'pending_approval',
          approval_reasons: ['Deletes files outside the working directory'],
        })
        srv.state.messages.push(m)
        return { status: 201, body: m }
      }
      if (u === '/api/chat/messages/9/approve' && init?.method === 'POST') {
        const m = srv.state.messages.find((x) => x.id === 9)!
        m.status = 'running'
        m.run_id = 31
        return { body: m }
      }
      return undefined
    })
    const { w, f } = await mountChat(srv, '/chat?thread=1')
    await w.get('#composer-text').setValue('rm -rf the build dir')
    await w.get('form.composer').trigger('submit')
    await flushPromises()

    const box = w.get('[data-testid="approval"]')
    expect(box.get('[data-testid="approval-reasons"]').text()).toContain('Deletes files outside the working directory')
    const buttons = box.findAll('button').map((b) => b.text())
    expect(buttons).toEqual(['Approve', 'Reject'])
    // The composer waits for the decision and says why.
    expect(w.get('#composer-text').attributes('disabled')).toBeDefined()
    expect(w.get('[data-testid="composer-reason"]').text()).toContain('waiting for your approval')

    await box.findAll('button')[0]!.trigger('click')
    await flushPromises()
    const approve = calls(f, 'POST', '/api/chat/messages/9/approve')
    expect(approve).toHaveLength(1)
    expect(headerOf(approve[0]![1], 'X-Mac-Control')).toBe('1')
    expect(w.find('[data-testid="approval"]').exists()).toBe(false)
    expect(w.find('[data-testid="chat-live"]').exists()).toBe(true)
    w.unmount()
  })

  it('Reject calls the reject endpoint', async () => {
    const srv = server({
      messages: [msg({ id: 4, role: 'user', text: 'risky', status: 'pending_approval', approval_reasons: ['Edit on main'] })],
    })
    srv.on((u, init) => {
      if (u === '/api/chat/messages/4/reject' && init?.method === 'POST') {
        srv.state.messages[0]!.status = 'cancelled'
        return { body: srv.state.messages[0] }
      }
      return undefined
    })
    const { w, f } = await mountChat(srv, '/chat?thread=1')
    await w.findAll('[data-testid="approval"] button')[1]!.trigger('click')
    await flushPromises()
    expect(calls(f, 'POST', '/api/chat/messages/4/reject')).toHaveLength(1)
    expect(w.get('article.msg').attributes('data-status')).toBe('cancelled')
    w.unmount()
  })

  it('disables the composer while busy, tails the run log, and Stop calls POST /stop', async () => {
    const srv = server({
      threads: [thread({ busy: true })],
      messages: [msg({ id: 5, role: 'user', text: 'long job', status: 'running', run_id: 21 })],
    })
    srv.on((u, init) => {
      if (u === '/api/chat/threads/1/stop' && init?.method === 'POST') return { body: { stopped: 21 } }
      return undefined
    })
    const { w, f } = await mountChat(srv, '/chat?thread=1')

    expect(w.get('#composer-text').attributes('disabled')).toBeDefined()
    expect(w.get('form.composer button[type="submit"]').attributes('disabled')).toBeDefined()
    expect(w.get('[data-testid="composer-reason"]').text()).toContain('answering')
    expect(w.get('[data-testid="chat-live-log"]').text()).toContain('reading the repo')
    expect(calls(f, 'GET', '/api/runs/21/log?offset=0').length).toBeGreaterThan(0)

    await w.get('[data-testid="chat-live"] button').trigger('click')
    await flushPromises()
    const stop = calls(f, 'POST', '/api/chat/threads/1/stop')
    expect(stop).toHaveLength(1)
    expect(headerOf(stop[0]![1], 'X-Mac-Control')).toBe('1')

    const del = w.findAll('button').find((b) => b.text().includes('Delete thread'))!
    expect(del.attributes('disabled')).toBeDefined()
    w.unmount()
  })

  it('Enter sends and Shift+Enter does not', async () => {
    const srv = server()
    srv.on((u, init) =>
      u === '/api/chat/threads/1/messages' && init?.method === 'POST'
        ? { status: 201, body: msg({ id: 8, role: 'user', text: 'one', status: 'done' }) }
        : undefined,
    )
    const { w, f } = await mountChat(srv, '/chat?thread=1')
    const box = w.get('#composer-text')
    await box.setValue('one')

    await box.trigger('keydown', { key: 'Enter', shiftKey: true })
    await flushPromises()
    expect(calls(f, 'POST', '/api/chat/threads/1/messages')).toHaveLength(0)
    expect((box.element as HTMLTextAreaElement).value).toBe('one')

    await box.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(calls(f, 'POST', '/api/chat/threads/1/messages')).toHaveLength(1)
    w.unmount()
  })

  it('shows a 409 detail inline and keeps the draft', async () => {
    const srv = server()
    srv.on((u, init) =>
      u === '/api/chat/threads/1/messages' && init?.method === 'POST'
        ? { status: 409, body: { detail: 'The agent is still answering' } }
        : undefined,
    )
    const { w } = await mountChat(srv, '/chat?thread=1')
    await w.get('#composer-text').setValue('too soon')
    await w.get('form.composer').trigger('submit')
    await flushPromises()
    expect(w.get('[data-testid="action-error"]').text()).toBe('The agent is still answering')
    expect((w.get('#composer-text').element as HTMLTextAreaElement).value).toBe('too soon')
    w.unmount()
  })

  it('styles failed and cancelled assistant messages and says copy is unavailable without a clipboard', async () => {
    const srv = server({
      messages: [
        msg({ id: 1, text: 'It broke', status: 'failed' }),
        msg({ id: 2, text: 'Stopped early', status: 'cancelled' }),
      ],
    })
    vi.stubGlobal('navigator', { ...navigator, clipboard: undefined })
    const { w } = await mountChat(srv, '/chat?thread=1')
    const bubbles = w.findAll('article.msg')
    expect(bubbles.map((b) => b.attributes('data-status'))).toEqual(['failed', 'cancelled'])
    expect(bubbles[0]!.text()).toContain('Failed')
    expect(bubbles[1]!.text()).toContain('Cancelled')

    await bubbles[0]!.get('button[aria-label="Copy message"]').trigger('click')
    await flushPromises()
    expect(bubbles[0]!.get('[data-testid="copy-unavailable"]').text()).toContain('not available')
    w.unmount()
  })

  it('copies the message text when the clipboard exists', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    const srv = server({ messages: [msg({ id: 1, text: 'copy me' })] })
    const { w } = await mountChat(srv, '/chat?thread=1')
    await w.get('button[aria-label="Copy message"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('copy me')
    expect(w.get('button[aria-label="Copy message"]').text()).toBe('Copied')
    w.unmount()
  })

  it('deletes a thread after confirm', async () => {
    const srv = server({ messages: [msg()] })
    srv.on((u, init) => (u === '/api/chat/threads/1' && init?.method === 'DELETE' ? { status: 204 } : undefined))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { w, f, router } = await mountChat(srv, '/chat?thread=1')
    await w.findAll('button').find((b) => b.text().includes('Delete thread'))!.trigger('click')
    await flushPromises()
    expect(calls(f, 'DELETE', '/api/chat/threads/1')).toHaveLength(1)
    expect(router.currentRoute.value.query.thread).toBeUndefined()
    w.unmount()
  })
})

describe('New chat dialog', () => {
  const AGENTS = [
    agent({ id: 'claude', name: 'Claude Code', suggested_models: ['claude-sonnet-5-5'] }),
    agent({ id: 'hermes', name: 'Hermes', role: 'manager', enforces_mode: false, notes: 'Advisory only.' }),
    agent({ id: 'openclaw', name: 'OpenClaw', available: false }),
  ]
  const WORKDIRS = [
    { path: '/ws/feature', branch: 'feature-x', root: '/ws' },
    { path: '/ws/main-repo', branch: 'main', root: '/ws' },
  ]

  async function open() {
    const f = stubFetch((u, init) => {
      if (u === '/api/agents') return { body: { agents: AGENTS } }
      if (u === '/api/workdirs') return { body: { workdirs: WORKDIRS } }
      if (u === '/api/chat/threads' && init?.method === 'POST') return { status: 201, body: thread({ id: 12 }) }
      return undefined
    })
    const w = mount(NewChatDialog, { attachTo: document.body })
    await flushPromises()
    return { w, f }
  }

  it('disables unavailable agents, warns for Edit on main, and notes advisory mode', async () => {
    const { w } = await open()
    const opt = w.findAll('#nchat-agent-native option').find((o) => o.text().includes('OpenClaw'))!
    expect(opt.attributes('disabled')).toBeDefined()
    await w.get('#nchat-dir-native').setValue('/ws/main-repo')
    expect(w.find('[data-testid="main-warning"]').exists()).toBe(false)
    await w.get('input[value="edit"]').setValue(true)
    expect(w.get('[data-testid="main-warning"]').text()).toContain('Edits on main')
    await w.get('#nchat-agent-native').setValue('hermes')
    expect(w.get('[data-testid="advisory-note"]').text()).toContain('Advisory only.')
    w.unmount()
  })

  it('POSTs agent, directory, mode and only the optional fields that were filled', async () => {
    const { w, f } = await open()
    await w.get('form').trigger('submit')
    await flushPromises()
    let post = calls(f, 'POST', '/api/chat/threads')[0]!
    expect(headerOf(post[1], 'X-Mac-Control')).toBe('1')
    expect(JSON.parse(String(post[1]?.body))).toEqual({ agent: 'hermes', model:'openrouter/free', working_dir: '/ws/feature', mode: 'read' })
    expect(w.emitted('created')).toHaveLength(1)

    await w.get('#nchat-agent-native').setValue('claude')
    await w.get('#nchat-title').setValue(' My chat ')
    await w.get('#nchat-model').setValue('claude-sonnet-5-5')
    await w.get('input[value="edit"]').setValue(true)
    await w.get('form').trigger('submit')
    await flushPromises()
    post = calls(f, 'POST', '/api/chat/threads')[1]!
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      agent: 'claude', working_dir: '/ws/feature', mode: 'edit', title: 'My chat', model: 'claude-sonnet-5-5',
    })
    w.unmount()
  })
})
