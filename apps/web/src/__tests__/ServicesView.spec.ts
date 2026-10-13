import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ServicesView from '@/views/ServicesView.vue'

afterEach(() => vi.unstubAllGlobals())

const svc = (over: Record<string, unknown>) => ({
  label: 'x', domain: 'gui', state: 'running', pid: 1, runs: 1, runs_24h: 0, allowed_runs_24h: 50,
  last_exit: '(never exited)', last_exit_code: null, flags: [], severity: 0,
  schedule: 'on demand / keep alive', path: '/p', program: '/bin/x', observed_at: 1, ...over,
})

describe('ServicesView', () => {
  it('renders crash-loop and signal-exit chips with severity markers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          crash_loop_threshold_24h: 50,
          services: [
            svc({ label: 'com.loopy', flags: ['crash_loop'], severity: 2, runs_24h: 120, state: 'waiting' }),
            svc({ label: 'com.killed', flags: ['last_exit_nonzero'], severity: 1, last_exit_code: -9, last_exit: 'signal 9' }),
            svc({ label: 'com.failed', flags: ['last_exit_nonzero'], severity: 1, last_exit_code: 1 }),
            svc({ label: 'com.fine' }),
          ],
        }),
      }),
    )
    const w = mount(ServicesView)
    await flushPromises()

    expect(w.text()).toContain("Crash loop = restarts in 24 h beyond what the job's schedule explains.")
    expect(w.text()).toContain('Crash loop')
    expect(w.text()).toContain('Stopped by signal 9')
    expect(w.text()).toContain('Last exit 1')
    expect(w.text()).toContain('120 / 50 allowed')

    const rows = w.findAll('tbody tr')
    expect(rows).toHaveLength(4)
    expect(rows[0]!.attributes('data-severity')).toBe('2')
    expect(rows[1]!.attributes('data-severity')).toBe('1')
    expect(w.findAll('th[scope="col"]').length).toBe(8)
    w.unmount()
  })

  it('shows the API error text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({ detail: 'launchctl failed' }) }),
    )
    const w = mount(ServicesView)
    await flushPromises()
    expect(w.get('[role="alert"]').text()).toContain('launchctl failed')
    w.unmount()
  })
})
