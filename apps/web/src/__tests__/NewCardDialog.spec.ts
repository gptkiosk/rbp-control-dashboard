import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import NewCardDialog from '@/components/NewCardDialog.vue'
import { agent, calls, card, headerOf, stubFetch } from './helpers'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const AGENTS = [
  agent({
    id: 'claude',
    name: 'Claude Code',
    default_model: null,
    suggested_models: ['claude-sonnet-5-5'],
  }),
  agent({
    id: 'codex',
    name: 'Codex',
    default_model: 'gpt-5.6',
    suggested_models: [],
  }),
  agent({
    id: 'hermes',
    name: 'Hermes',
    role: 'manager',
    enforces_mode: false,
    notes: 'Management agent policy.',
  }),
  agent({ id: 'openclaw', name: 'OpenClaw', available: false }),
]
const WORKDIRS = [
  { path: '/ws/feature-repo', branch: 'feature-x', root: '/ws' },
  { path: '/ws/main-repo', branch: 'main', root: '/ws' },
  { path: '/ws/plain', branch: null, root: '/ws' },
]

async function open(extra?: Parameters<typeof stubFetch>[0]) {
  const f = stubFetch((u, init) => {
    const own = extra?.(u, init)
    if (own) return own
    if (u === '/api/agents') return { body: { agents: AGENTS } }
    if (u === '/api/workdirs') return { body: { workdirs: WORKDIRS } }
    return undefined
  })
  const w = mount(NewCardDialog, { attachTo: document.body })
  await flushPromises()
  return { w, f }
}

describe('NewCardDialog', () => {
  it('shows the Budget field only for Claude, and the OpenClaw id only for OpenClaw', async () => {
    const { w } = await open()
    await w.get('#nc-agent-native').setValue('claude')
    expect(w.find('#nc-budget').exists()).toBe(true)
    expect((w.get('#nc-budget').element as HTMLInputElement).value).toBe('1.00')
    await w.get('#nc-agent-native').setValue('codex')
    expect(w.find('#nc-budget').exists()).toBe(false)
    expect(w.find('#nc-target').exists()).toBe(false)
    expect(w.get('#nc-model').attributes('placeholder')).toBe('gpt-5.6')
    w.unmount()
  })

  it('disables agents that are not installed', async () => {
    const { w } = await open()
    const opt = w.findAll('#nc-agent-native option').find((o) => o.text().includes('OpenClaw'))!
    expect(opt.text()).toContain('(not installed)')
    expect(opt.attributes('disabled')).toBeDefined()
    w.unmount()
  })

  it('warns "Edits on main need your approval" for Edit + a main branch only', async () => {
    const { w } = await open()
    const warning = () => w.find('[data-testid="main-warning"]')
    await w.get('#nc-dir-native').setValue('/ws/main-repo')
    expect(warning().exists()).toBe(false) // still Read
    await w.get('input[value="edit"]').setValue(true)
    expect(warning().text()).toBe('Edits on main need your approval')
    await w.get('#nc-dir-native').setValue('/ws/feature-repo')
    expect(warning().exists()).toBe(false)
    await w.get('#nc-dir-native').setValue('/ws/main-repo')
    await w.get('input[value="read"]').setValue(true)
    expect(warning().exists()).toBe(false)
    w.unmount()
  })

  it('explains advisory Read/Edit for agents that do not enforce it', async () => {
    const { w } = await open()
    await w.get('#nc-agent-native').setValue('claude')
    expect(w.find('[data-testid="advisory-note"]').exists()).toBe(false)
    await w.get('#nc-agent-native').setValue('hermes')
    expect(w.get('[data-testid="advisory-note"]').text()).toContain('Management agent policy.')
    w.unmount()
  })

  it('POSTs the new card with the guard header and emits created', async () => {
    const { w, f } = await open((u, init) =>
      u === '/api/cards' && init?.method === 'POST'
        ? { status: 201, body: card({ id: 11, column: 'backlog' }) }
        : undefined,
    )
    await w.get('#nc-agent-native').setValue('claude')
    await w.get('#nc-title').setValue('  Write tests ')
    await w.get('#nc-body').setValue('Please')
    await w.get('#nc-timeout').setValue('10')
    await w.get('form').trigger('submit')
    await flushPromises()

    const post = calls(f, 'POST', '/api/cards')[0]!
    expect(headerOf(post[1], 'X-Mac-Control')).toBe('1')
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      title: 'Write tests',
      body: 'Please',
      agent: 'claude',
      working_dir: '/ws/feature-repo',
      mode: 'read',
      model: null,
      timeout_s: 600,
      budget_usd: 1,
      assignee_type: 'agent',
      priority: 'normal',
      due_date: null,
      estimate_minutes: null,
      tags: [],
      acceptance: null,
      depends_on: [],
    })
    expect(w.emitted('created')).toHaveLength(1)
    w.unmount()
  })

  it('creates a human task with definition of done and metadata, without agent settings', async () => {
    const { w, f } = await open((u, init) =>
      u === '/api/cards' && init?.method === 'POST'
        ? { status: 201, body: card({ assignee_type: 'human', agent: null }) }
        : undefined,
    )
    await w.get('#nc-assignee-native').setValue('human')
    expect(w.find('#nc-agent-native').exists()).toBe(false)
    await w.get('#nc-title').setValue('Verify release')
    await w.get('#nc-priority-native').setValue('high')
    await w.get('#nc-due').setValue('2026-10-20')
    await w.get('#nc-estimate').setValue('1.5')
    await w.get('#nc-tags').setValue('  Release  ')
    await w.get('#nc-tags').trigger('keydown', { key: 'Enter' })
    await w.get('#nc-acceptance').setValue('All acceptance checks passed')
    await w.get('form').trigger('submit')
    await flushPromises()
    const payload = JSON.parse(String(calls(f, 'POST', '/api/cards')[0]![1]?.body))
    expect(payload).toMatchObject({
      assignee_type: 'human',
      priority: 'high',
      due_date: '2026-10-20',
      estimate_minutes: 90,
      tags: ['release'],
      acceptance: 'All acceptance checks passed',
    })
    expect(payload).not.toHaveProperty('agent')
    expect(payload).not.toHaveProperty('working_dir')
    w.unmount()
  })

  it('shows the server 422 detail inline and stays open', async () => {
    const { w } = await open((u, init) =>
      u === '/api/cards' && init?.method === 'POST'
        ? {
            status: 422,
            body: { detail: 'working_dir is outside the allowed roots' },
          }
        : undefined,
    )
    await w.get('#nc-title').setValue('x')
    await w.get('#nc-body').setValue('y')
    await w.get('form').trigger('submit')
    await flushPromises()
    expect(w.get('[data-testid="submit-error"]').text()).toBe('working_dir is outside the allowed roots')
    expect(w.emitted('created')).toBeUndefined()
    w.unmount()
  })

  it('closes on Escape', async () => {
    const { w } = await open()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })
})
