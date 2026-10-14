import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CardDetailPanel from '@/components/CardDetailPanel.vue'
import type { CardDetail } from '@/lib/api'
import { calls, card, headerOf, run, stubFetch } from './helpers'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

function mountPanel(detail: CardDetail, extra?: Parameters<typeof stubFetch>[0]) {
  const f = stubFetch((u, init) => {
    const own = extra?.(u, init)
    if (own) return own
    if (u === `/api/cards/${detail.id}` && (init?.method ?? 'GET') === 'GET') return { body: detail }
    if (u === '/api/cards') return { body: { cards: [detail, card({ id: 99, title: 'Prep' })] } }
    if (u === '/api/workdirs') return { body: { workdirs: [{ path: '/w', branch: null, root: '/' }] } }
    if (u.startsWith('/api/runs/') && u.includes('/log'))
      return {
        body: { text: '', next_offset: 0, done: true, stage: 'succeeded' },
      }
    return undefined
  })
  const w = mount(CardDetailPanel, {
    props: { cardId: detail.id },
    attachTo: document.body,
  })
  return { w, f }
}

const reviewCard = (): CardDetail => ({
  ...card({
    id: 5,
    column: 'review',
    needs_approval: true,
    approval_reasons: ['Edit mode on main'],
    approval_challenge: 'nonce-1',
    approval_pin: 'a'.repeat(64),
  }),
  runs: [],
})

describe('CardDetailPanel', () => {
  it('explains a normal CLI exit when the provider timed out', async () => {
    const detail: CardDetail = {
      ...card({ id: 5, column: 'failed' }),
      runs: [run({ id: 5, card_id: 5, agent: 'openclaw', stage: 'timeout', exit_code: 0,
        error: 'OpenClaw provider timed out: the model stopped responding before its idle limit.' })],
    }
    const { w } = mountPanel(detail)
    await flushPromises()
    expect(w.get('[data-testid="run-meta"]').text()).toContain('Timed out')
    expect(w.get('[data-testid="run-meta"]').text()).toContain('OpenClaw provider timed out')
    expect(w.get('[data-testid="exit-code-explanation"]').text()).toContain('CLI exited normally; the agent run did not succeed')
    w.unmount()
  })

  it('does not add failure guidance to a successful zero exit', async () => {
    const { w } = mountPanel({ ...card({ column: 'done' }), runs: [run({ stage: 'succeeded', exit_code: 0, error: null })] })
    await flushPromises()
    expect(w.find('[data-testid="exit-code-explanation"]').exists()).toBe(false)
    w.unmount()
  })

  it('shows Approve for a review card that needs approval and POSTs /approve', async () => {
    const { w, f } = mountPanel(reviewCard(), (u, init) =>
      u === '/api/cards/5/approve' && init?.method === 'POST'
        ? {
            body: card({
              id: 5,
              column: 'queued',
              needs_approval: true,
              approved_at: 9,
            }),
          }
        : undefined,
    )
    await flushPromises()
    expect(w.text()).toContain('Edit mode on main')
    const approve = w.findAll('button').find((b) => b.text() === 'Approve')
    expect(approve).toBeTruthy()
    await approve!.trigger('click')
    await flushPromises()

    const posts = calls(f, 'POST', '/api/cards/5/approve')
    expect(posts).toHaveLength(1)
    expect(headerOf(posts[0]![1], 'X-Mac-Control')).toBe('1')
    expect(JSON.parse(String(posts[0]![1]?.body))).toEqual({ challenge: 'nonce-1', pin: 'a'.repeat(64) })
    expect(w.get('[data-testid="panel-message"]').text()).toContain('Approved')
    w.unmount()
  })

  it('hides Approve when no approval is needed, and disables Edit and Delete while running', async () => {
    const running: CardDetail = {
      ...card({
        id: 6,
        column: 'running',
        last_run: run({
          id: 60,
          stage: 'running',
          ended_at: null,
          duration_s: null,
        }),
      }),
      runs: [
        run({
          id: 60,
          card_id: 6,
          stage: 'running',
          ended_at: null,
          duration_s: null,
          cost_usd: null,
          result_text: null,
        }),
      ],
    }
    const { w } = mountPanel(running)
    await flushPromises()
    const byText = (t: string) => w.findAll('button').find((b) => b.text() === t)
    expect(byText('Approve')).toBeUndefined()
    expect(byText('Edit')!.attributes('disabled')).toBeDefined()
    expect(byText('Delete')!.attributes('disabled')).toBeDefined()
    expect(byText('Run')!.attributes('disabled')).toBeDefined()
    expect(byText('Cancel run')).toBeTruthy()
    w.unmount()
  })

  it('cancels a running run after confirmation', async () => {
    const running: CardDetail = {
      ...card({ id: 6, column: 'running' }),
      runs: [
        run({
          id: 60,
          card_id: 6,
          stage: 'running',
          ended_at: null,
          duration_s: null,
        }),
      ],
    }
    const confirm = vi.fn().mockReturnValue(true)
    vi.stubGlobal('confirm', confirm)
    const { w, f } = mountPanel(running, (u, init) =>
      u === '/api/runs/60/cancel' && init?.method === 'POST' ? { body: { cancelled: 60 } } : undefined,
    )
    await flushPromises()
    await w
      .findAll('button')
      .find((b) => b.text() === 'Cancel run')!
      .trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalled()
    expect(calls(f, 'POST', '/api/runs/60/cancel')).toHaveLength(1)
    w.unmount()
  })

  it('does nothing when the confirmation is declined', async () => {
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(false))
    const { w, f } = mountPanel({
      ...card({ id: 8, column: 'done' }),
      runs: [],
    })
    await flushPromises()
    await w
      .findAll('button')
      .find((b) => b.text() === 'Delete')!
      .trigger('click')
    await flushPromises()
    expect(calls(f, 'DELETE', '/api/cards')).toHaveLength(0)
    w.unmount()
  })

  it('shows run metadata with "not reported" for null values', async () => {
    const detail: CardDetail = {
      ...card({ id: 7, column: 'done' }),
      runs: [
        run({
          id: 71,
          card_id: 7,
          model_reported: null,
          cost_usd: null,
          input_tokens: null,
          provider: null,
          session_id: null,
          exit_code: null,
        }),
        run({
          id: 70,
          card_id: 7,
          stage: 'failed',
          cost_usd: 0,
          input_tokens: 0,
          error: 'boom',
          result_text: 'Earlier result',
        }),
      ],
    }
    const { w } = mountPanel(detail)
    await flushPromises()
    const meta = w.get('[data-testid="run-meta"]')
    for (const label of [
      'Stage',
      'Model requested',
      'Model reported',
      'Provider',
      'Tokens in',
      'Tokens out',
      'Cost (USD)',
      'Duration',
      'Exit code',
      'Session ID',
      'Working dir',
      'Command',
      'Error',
    ]) {
      expect(meta.text()).toContain(label)
    }
    expect(meta.findAll('[data-missing="true"]').length).toBeGreaterThanOrEqual(5)
    expect(meta.text()).toContain('claude -p <prompt>')

    // newest first; pick the older run
    const buttons = w.findAll('button.run-btn')
    expect(buttons.map((b) => b.text())).toEqual([
      expect.stringContaining('#71'),
      expect.stringContaining('#70'),
    ])
    await buttons[1]!.trigger('click')
    await flushPromises()
    const meta2 = w.get('[data-testid="run-meta"]').text()
    expect(meta2).toContain('$0.0000')
    expect(meta2).toContain('boom')
    expect(w.get('[data-testid="run-result"]').text()).toBe('Earlier result')
    w.unmount()
  })

  it('saves only changed fields and says when approval was cleared', async () => {
    const approved: CardDetail = {
      ...card({
        id: 9,
        column: 'review',
        needs_approval: true,
        approved_at: 5,
        body: 'old',
      }),
      runs: [],
    }
    const { w, f } = mountPanel(approved, (u, init) =>
      u === '/api/cards/9' && init?.method === 'PATCH'
        ? {
            body: card({
              id: 9,
              column: 'review',
              needs_approval: true,
              approved_at: null,
              body: 'new prompt',
            }),
          }
        : undefined,
    )
    await flushPromises()
    await w
      .findAll('button')
      .find((b) => b.text() === 'Edit')!
      .trigger('click')
    await flushPromises()
    await w.get('#ed-body').setValue('new prompt')
    await w.get('form[aria-label="Edit card"]').trigger('submit')
    await flushPromises()

    const patch = calls(f, 'PATCH', '/api/cards/9')[0]!
    expect(JSON.parse(String(patch[1]?.body))).toEqual({ body: 'new prompt' })
    expect(w.get('[data-testid="panel-message"]').text()).toContain('cleared the approval')
    w.unmount()
  })

  it('moves a running human task to Done and hides agent run controls', async () => {
    const { w, f } = mountPanel(
      {
        ...card({
          id: 10,
          assignee_type: 'human',
          agent: null,
          working_dir: null,
          column: 'running',
        }),
        runs: [],
      },
      (u, init) =>
        u === '/api/cards/10' && init?.method === 'PATCH'
          ? {
              body: card({
                id: 10,
                column: 'done',
                assignee_type: 'human',
                agent: null,
              }),
            }
          : undefined,
    )
    await flushPromises()
    expect(w.findAll('button').some((b) => b.text() === 'Run')).toBe(false)
    expect(w.get('.move select').attributes('disabled')).toBeUndefined()
    await w.get('.move select').setValue('done')
    await flushPromises()
    expect(calls(f, 'PATCH', '/api/cards/10')[0]![1]?.body).toBe('{"column":"done"}')
    w.unmount()
  })

  it('adds and removes dependencies and shows cycle errors from the server', async () => {
    const { w, f } = mountPanel(
      {
        ...card({ id: 10, column: 'queued', depends_on: [8], blocked_by: [8] }),
        runs: [],
      },
      (u, init) => {
        if (u === '/api/cards/10/dependencies' && init?.method === 'POST')
          return {
            status: 422,
            body: { detail: 'Dependency would create a cycle' },
          }
        if (u === '/api/cards/10/dependencies/8' && init?.method === 'DELETE')
          return { body: card({ id: 10 }) }
        return undefined
      },
    )
    await flushPromises()
    expect(w.get('[data-testid="dependency-notice"]').text()).toContain(
      'will start when its blockers are Done',
    )
    await w.get('#dependency-id-native').setValue('99')
    await w.get('.dependency-add').trigger('submit')
    await flushPromises()
    expect(w.get('[data-testid="panel-message"]').text()).toContain('create a cycle')
    expect(JSON.parse(String(calls(f, 'POST', '/api/cards/10/dependencies')[0]![1]?.body))).toEqual({
      depends_on_id: 99,
    })
    await w.get('button[aria-label="Remove dependency #8"]').trigger('click')
    await flushPromises()
    expect(calls(f, 'DELETE', '/api/cards/10/dependencies/8')).toHaveLength(1)
    w.unmount()
  })

  it('moves a card via the keyboard-accessible Move to… select', async () => {
    const { w, f } = mountPanel({ ...card({ id: 10, column: 'backlog' }), runs: [] }, (u, init) =>
      u === '/api/cards/10' && init?.method === 'PATCH'
        ? { body: card({ id: 10, column: 'done' }) }
        : undefined,
    )
    await flushPromises()
    const select = w.get('.move select')
    expect(select.findAll('option').map((o) => o.text())).not.toContain('Running')
    await select.setValue('done')
    await flushPromises()
    expect(calls(f, 'PATCH', '/api/cards/10')[0]![1]?.body).toBe('{"column":"done"}')
    w.unmount()
  })
})
