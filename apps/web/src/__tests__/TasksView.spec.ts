import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import TasksView from '@/views/TasksView.vue'
import type { Card } from '@/lib/api'
import { calls, card, headerOf, run, stubFetch } from './helpers'

beforeEach(() => localStorage.clear())

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

async function mountBoard(cards: Card[], extra?: Parameters<typeof stubFetch>[0], url = '/tasks') {
  const f = stubFetch((u, init) => {
    const own = extra?.(u, init)
    if (own) return own
    if (u.startsWith('/api/cards') && (init?.method ?? 'GET') === 'GET') return { body: { cards } }
    return undefined
  })
  const router = createAppRouter(createMemoryHistory())
  router.push(url)
  await router.isReady()
  const w = mount(TasksView, {
    global: { plugins: [router] },
    attachTo: document.body,
  })
  await flushPromises()
  return { w, f, router }
}

const COLUMN_ORDER = ['running', 'review', 'queued', 'backlog', 'failed', 'done']

describe('Tasks board', () => {
  it('shows a condensed model per task: what ran, else what was asked for, a dash for a human task', async () => {
    const { w } = await mountBoard([
      card({ id: 1, column: 'backlog', title: 'Asked', agent: 'openclaw', model: 'openrouter/thinkingmachines/inkling:free' }),
      card({ id: 2, column: 'backlog', title: 'Ran', agent: 'claude', model: 'claude-haiku-5-5',
        last_run: run({ stage: 'succeeded', model_requested: 'claude-haiku-5-5', model_reported: 'claude-opus-5-5' }) }),
      card({ id: 3, column: 'backlog', title: 'Mine', agent: null, assignee_type: 'human', model: null }),
    ])
    const cell = (id: number) => w.get(`[data-card-id="${id}"] [data-col="model"]`)
    expect(cell(1).text()).toBe('inkling \u00b7 free')
    expect(cell(1).get('.model').attributes('title')).toBe('openrouter/thinkingmachines/inkling:free')
    expect(cell(2).text()).toBe('claude-opus-5-5')
    expect(cell(3).text()).toBe('\u2014')
    expect(w.findAll('[role="columnheader"]').some((h) => h.text() === 'Model')).toBe(true)
  })

  it('groups cards into the six columns, in order, with counts', async () => {
    const { w } = await mountBoard([
      card({ id: 1, column: 'backlog', title: 'B1' }),
      card({ id: 2, column: 'backlog', title: 'B2' }),
      card({
        id: 3,
        column: 'running',
        title: 'R1',
        last_run: run({ stage: 'running', ended_at: null, duration_s: null }),
      }),
      card({ id: 4, column: 'review', title: 'V1', needs_approval: true }),
      card({ id: 5, column: 'done', title: 'D1' }),
      card({ id: 6, column: 'failed', title: 'F1' }),
      card({ id: 7, column: 'done', title: 'D2' }),
    ])
    const cols = w.findAll('section.group')
    expect(cols.map((c) => c.attributes('data-column'))).toEqual(COLUMN_ORDER)
    expect(cols.map((c) => c.get('h2').text())).toEqual([
      'IN PROGRESS',
      'NEEDS APPROVAL',
      'QUEUED',
      'BACKLOG',
      'FAILED',
      'DONE',
    ])
    expect(cols.map((c) => c.get('[data-testid="count"]').text())).toEqual(['1', '1', '0', '2', '1', '2'])
    expect(cols[1]!.text()).toContain('Waiting for your approval')
    expect(cols[3]!.findAll('.task-row .open').map((a) => a.text())).toEqual(['B1', 'B2'])
    w.unmount()
  })

  it('shows compact row fields, tags, blockers, attribution and a live timer', async () => {
    const { w } = await mountBoard([
      card({
        id: 1,
        agent: 'hermes',
        created_by: 'hermes',
        tags: ['ops'],
        depends_on: [8],
        blocked_by: [8],
        priority: 'high',
        due_date: '2026-10-20',
        estimate_minutes: 90,
      }),
      card({ id: 2, column: 'running', assignee_type: 'human', agent: null }),
      card({
        id: 3,
        column: 'running',
        last_run: run({
          stage: 'running',
          started_at: Math.floor(Date.now() / 1000) - 12,
          ended_at: null,
          duration_s: null,
        }),
      }),
    ])
    const first = w.get('[data-card-id="1"]').text()
    for (const text of ['Hermes', 'via Hermes', 'ops', 'Blocked by #8', 'High', '1h 30m', 'Oct 20'])
      expect(first).toContain(text)
    expect(w.get('[data-card-id="2"]').text()).toContain('You')
    expect(w.get('[data-card-id="3"] [data-testid="elapsed"]').text()).toMatch(/^1[2-4] s$/)
    w.unmount()
  })

  it('remembers filters, hidden lanes and collapsed groups across remounts', async () => {
    const rows = [
      card({ id: 1, title: 'Human prep', assignee_type: 'human', agent: null }),
      card({ id: 2, title: 'Agent prep', column: 'queued' }),
    ]
    const { w } = await mountBoard(rows)
    await w.get('input[type="search"]').setValue('Human')
    expect(w.findAll('.task-row')).toHaveLength(1)
    await w.get('[data-group="backlog"] [data-testid="group-toggle"]').trigger('click')
    await w.get('.lanes input[type="checkbox"]').setValue(false)
    w.unmount()
    const { w: next } = await mountBoard(rows)
    expect((next.get('input[type="search"]').element as HTMLInputElement).value).toBe('Human')
    expect(next.find('[data-group="running"]').exists()).toBe(false)
    expect(next.get('[data-group="backlog"]').attributes('data-collapsed')).toBe('true')
    await next
      .findAll('button')
      .find((b) => b.text() === 'Clear filters')!
      .trigger('click')
    expect(next.text()).toContain('2 of 2 tasks')
    next.unmount()
  })

  it('combines agent, priority, tag, creator and blocker filters, while allowing alternatives', async () => {
    const { w } = await mountBoard([
      card({
        id: 1,
        agent: 'hermes',
        created_by: 'hermes',
        priority: 'high',
        tags: ['ops'],
        blocked_by: [9],
      }),
      card({ id: 2, agent: 'codex', created_by: 'hermes', priority: 'high', tags: ['ops'], blocked_by: [9] }),
      card({
        id: 3,
        agent: 'hermes',
        created_by: 'operator',
        priority: 'high',
        tags: ['ops'],
        blocked_by: [9],
      }),
      card({ id: 4, agent: 'hermes', created_by: 'hermes', priority: 'low', tags: ['ops'], blocked_by: [9] }),
      card({ id: 5, agent: 'hermes', created_by: 'hermes', priority: 'high', tags: ['ops'] }),
    ])
    await w.get('input[value="high"]').setValue(true)
    await w.get('input[value="ops"]').setValue(true)
    const hermes = w.findAll('input[value="hermes"]')
    await hermes[0]!.setValue(true)
    await hermes[1]!.setValue(true)
    await w
      .findAll('input[type="checkbox"]')
      .find((el) => el.element.parentElement?.textContent?.includes('Blocked only'))!
      .setValue(true)
    expect(w.findAll('.task-row').map((r) => r.attributes('data-card-id'))).toEqual(['1'])
    await w.get('input[value="codex"]').setValue(true)
    expect(w.findAll('.task-row').map((r) => r.attributes('data-card-id'))).toEqual(['1', '2'])
    w.unmount()
  })

  it('allows dragging a human task out of In progress and quick-adds human tasks', async () => {
    const { w, f } = await mountBoard(
      [card({ id: 1, assignee_type: 'human', agent: null, column: 'running' })],
      (u, init) => {
        if (u === '/api/cards/1' && init?.method === 'PATCH')
          return {
            body: card({
              id: 1,
              assignee_type: 'human',
              agent: null,
              column: 'done',
            }),
          }
        if (u === '/api/cards' && init?.method === 'POST')
          return {
            status: 201,
            body: card({ id: 9, assignee_type: 'human', agent: null }),
          }
        return undefined
      },
    )
    expect(w.get('[data-card-id="1"]').attributes('draggable')).toBe('true')
    await w.get('[data-card-id="1"]').trigger('dragstart')
    await w.get('[data-group="done"]').trigger('drop')
    await flushPromises()
    expect(calls(f, 'PATCH', '/api/cards/1')[0]![1]?.body).toBe('{"column":"done"}')
    await w.get('[data-group="backlog"] [data-testid="quick-add"]').trigger('click')
    await w.get('[data-testid="quick-add-input"]').setValue('Review result')
    await w.get('[data-testid="quick-add-input"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(JSON.parse(String(calls(f, 'POST', '/api/cards')[0]![1]?.body))).toEqual({
      title: 'Review result',
      assignee_type: 'human',
    })
    w.unmount()
  })

  it('does not make a running card draggable, nor the Running column a drop target', async () => {
    const { w } = await mountBoard([
      card({ id: 1, column: 'backlog' }),
      card({
        id: 2,
        column: 'running',
        last_run: run({ stage: 'running', ended_at: null, duration_s: null }),
      }),
    ])
    expect(w.get('[data-card-id="2"]').attributes('draggable')).toBe('false')
    expect(w.get('[data-card-id="1"]').attributes('draggable')).toBe('true')

    await w.get('[data-card-id="1"]').trigger('dragstart')
    const over = (col: string) => {
      const ev = new Event('dragover', { bubbles: true, cancelable: true })
      w.get(`[data-column="${col}"]`).element.dispatchEvent(ev)
      return ev.defaultPrevented
    }
    expect(over('running')).toBe(false)
    expect(over('queued')).toBe(true)
    w.unmount()
  })

  it('PATCHes {column} on drop and explains when the server sent the card to review', async () => {
    const landed = card({
      id: 1,
      column: 'review',
      needs_approval: true,
      approval_reasons: ['Edit mode on main', 'Budget above $5'],
    })
    const { w, f } = await mountBoard([card({ id: 1, column: 'backlog', title: 'Risky' })], (u, init) =>
      u === '/api/cards/1' && init?.method === 'PATCH' ? { body: landed } : undefined,
    )
    await w.get('[data-card-id="1"]').trigger('dragstart')
    await w.get('[data-column="queued"]').trigger('drop')
    await flushPromises()

    const patches = calls(f, 'PATCH', '/api/cards/1')
    expect(patches).toHaveLength(1)
    expect(patches[0]![1]?.body).toBe('{"column":"queued"}')
    expect(headerOf(patches[0]![1], 'X-Mac-Control')).toBe('1')
    const notice = w.get('[data-testid="board-notice"]')
    expect(notice.text()).toContain('Needs your approval: Edit mode on main; Budget above $5')
    w.unmount()
  })

  it('shows the server detail inline when a move is refused', async () => {
    const { w } = await mountBoard([card({ id: 1, column: 'backlog', title: 'Stuck' })], (u, init) =>
      init?.method === 'PATCH'
        ? { status: 409, body: { detail: 'a running card cannot be moved' } }
        : undefined,
    )
    await w.get('[data-card-id="1"]').trigger('dragstart')
    await w.get('[data-column="done"]').trigger('drop')
    await flushPromises()
    const notice = w.get('[data-testid="board-notice"]')
    expect(notice.attributes('role')).toBe('alert')
    expect(notice.text()).toContain('a running card cannot be moved')
    w.unmount()
  })

  it('opens the card detail from ?card= and closes back to the board', async () => {
    const detail = { ...card({ id: 4, title: 'Deep link' }), runs: [] }
    const { w, router } = await mountBoard(
      [card({ id: 4, title: 'Deep link' })],
      (u) => (u === '/api/cards/4' ? { body: detail } : undefined),
      '/tasks?card=4',
    )
    expect(w.get('[role="dialog"]').text()).toContain('Deep link')
    await w.get('button[aria-label="Close card"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.card).toBeUndefined()
    expect(w.find('[role="dialog"]').exists()).toBe(false)
    w.unmount()
  })
})

it('shows an obvious output approval button and formats its stage',async()=>{
 const {w}=await mountBoard([card({id:5,column:'review',project:{id:1,node_key:'inventory',role:'story'},last_run:run({stage:'awaiting_approval'})})])
 const row=w.get('[data-card-id="5"]')
 expect(row.text()).toContain('Awaiting output approval')
 expect(row.findAll('button').find(b=>b.text()==='Approve & continue')!.exists()).toBe(true)
 w.unmount()
})

it('surfaces a ready project operator decision in Needs approval without mutating its backlog state',async()=>{
 const ready=card({id:6,column:'backlog',assignee_type:'human',agent:null,project:{id:1,node_key:'decision',role:'story'}})
 const blocked=card({id:9,column:'backlog',assignee_type:'human',agent:null,project:{id:1,node_key:'facts',role:'story'},blocked_by:[8]})
 const {w}=await mountBoard([ready,blocked])
 expect(w.get('section.group[data-column="review"] [data-card-id="6"]').text()).toContain('Record decision')
 expect(w.get('section.group[data-column="backlog"] [data-card-id="9"]').text()).not.toContain('Record decision')
 expect(ready.column).toBe('backlog');w.unmount()
})
