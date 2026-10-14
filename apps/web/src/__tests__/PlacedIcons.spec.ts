import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CardDetailPanel from '@/components/CardDetailPanel.vue'
import CardTile from '@/components/CardTile.vue'
import ServicesView from '@/views/ServicesView.vue'
import type { CardDetail } from '@/lib/api'
import { card, run, stubFetch } from './helpers'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const icons = (root: { findAll: (s: string) => { attributes: (n: string) => string | undefined }[] }) =>
  root.findAll('svg').map((s) => s.attributes('data-icon'))

describe('placed icons', () => {
  it('puts a small alert icon on the crash-loop chip', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          crash_loop_threshold_24h: 50,
          services: [
            {
              label: 'com.loopy', domain: 'gui', state: 'waiting', pid: null, runs: 1, runs_24h: 120,
              allowed_runs_24h: 50, last_exit: '(never exited)', last_exit_code: null, flags: ['crash_loop'],
              severity: 2, schedule: 'on demand', path: '/p', program: '/bin/x', observed_at: 1,
            },
          ],
        }),
      }),
    )
    const w = mount(ServicesView)
    await flushPromises()
    expect(w.get('h1 svg').attributes('data-icon')).toBe('services')
    const chip = w.findAll('tbody .chip').find((c) => c.text() === 'Crash loop')!
    expect(chip.findAll('svg')).toHaveLength(1)
    expect(chip.get('svg').attributes('data-icon')).toBe('alert')
    expect(chip.get('svg').classes()).toContain('icon-sm')
    w.unmount()
  })

  it('shows a clock on the card face when a finished run has a duration', () => {
    const w = mount(CardTile, { props: { card: card({ column: 'done', last_run: run({ duration_s: 3.7 }) }) } })
    expect(icons(w)).toEqual(['clock'])
    expect(w.get('svg').classes()).toContain('icon-sm')
  })

  it('shows no clock on a card with no run', () => {
    const w = mount(CardTile, { props: { card: card() } })
    expect(w.findAll('svg')).toHaveLength(0)
  })

  it('decorates the detail buttons and run metadata labels', async () => {
    const detail: CardDetail = {
      ...card({ id: 5, column: 'review', needs_approval: true, approval_reasons: ['Edit mode on main'], last_run: run({ id: 50, stage: 'running', ended_at: null, duration_s: null }) }),
      runs: [run({ id: 50, card_id: 5, stage: 'running', ended_at: null, duration_s: null })],
    }
    stubFetch((u) => {
      if (u === '/api/cards/5') return { body: detail }
      if (u.startsWith('/api/runs/') && u.includes('/log')) return { body: { text: '', next_offset: 0, done: true, stage: 'running' } }
      return undefined
    })
    const w = mount(CardDetailPanel, { props: { cardId: 5 }, attachTo: document.body })
    await flushPromises()

    const button = (t: string) => w.findAll('button').find((b) => b.text() === t)!
    expect(button('Run').get('svg').attributes('data-icon')).toBe('run')
    expect(button('Cancel run').get('svg').attributes('data-icon')).toBe('stop')
    expect(button('Delete').get('svg').attributes('data-icon')).toBe('trash')
    expect(button('Approve').get('svg').attributes('data-icon')).toBe('approval')
    expect(w.get('#approval-h svg').attributes('data-icon')).toBe('approval')

    const meta = w.get('[data-testid="run-meta"]')
    const labelIcon = (label: string) =>
      meta.findAll('dt').find((d) => d.text() === label)!.get('svg').attributes('data-icon')
    expect(labelIcon('Duration')).toBe('clock')
    expect(labelIcon('Tokens in')).toBe('tokens')
    expect(labelIcon('Tokens out')).toBe('tokens')
    expect(labelIcon('Cost (USD)')).toBe('cost')
    expect(labelIcon('Model requested')).toBe('model')
    expect(labelIcon('Model reported')).toBe('model')
    w.unmount()
  })
})
