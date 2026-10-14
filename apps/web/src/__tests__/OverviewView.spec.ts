import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import OverviewView from '@/views/OverviewView.vue'

afterEach(() => vi.unstubAllGlobals())

const current = {
  ts: 1, cpu_pct: 12.47, ecpu_pct: 19.8, pcpu_pct: 1.48, gpu_pct: 28.6, mem_used: 13714276352,
  mem_total: 17179869184, swap_used: 3688366080, swap_total: 4294967296, pressure_level: 1,
  disk_used: 1, disk_total: 2, net_rx_bps: 4139, net_tx_bps: 10599.9, cpu_temp: 34.39, gpu_temp: 32.74,
  sys_power: 3.37, cpu_power: 0.16, gpu_power: 0.28, ane_power: 0, ram_power: 0.27, fan_rpm: 1000,
  sample_age_s: 7, mem_used_pct: 79.8, swap_used_pct: 85.9, disk_used_pct: 53, pressure_label: 'normal',
  disk_days_to_full: null, macmon_status: 'running',
  platform: 'linux', throttled: false, throttle_flags: [] as string[],
}

function respond(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

function stubApi(metrics: ReturnType<typeof respond>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.startsWith('/api/metrics/current')) return metrics
      if (url.startsWith('/api/services')) {
        return respond(200, { services: [{ severity: 2 }, { severity: 0 }], crash_loop_threshold_24h: 50 })
      }
      if (url.startsWith('/api/updates')) {
        return respond(200, { updates: [{ label: 'a', requires_restart: true }, { label: 'b', requires_restart: false }], checked_at: 1 })
      }
      if (url.startsWith('/api/agents/usage')) return respond(200, { overview: [], sessions: [], coverage: {} })
      if (url === '/api/agents') return respond(200, { agents: [] })
      return respond(404, { detail: 'nope' })
    }),
  )
}

async function mountOverview() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/')
  await router.isReady()
  const w = mount(OverviewView, { global: { plugins: [router] } })
  await flushPromises()
  return w
}

describe('OverviewView', () => {
  it('shows "Collecting first samples…" on a 503', async () => {
    stubApi(respond(503, { detail: 'no samples yet' }))
    const w = await mountOverview()
    expect(w.text()).toContain('Collecting first samples…')
    expect(w.find('[data-testid="tile-cpu"]').exists()).toBe(false)
    expect(w.get('#overview-agents-title').text()).toBe('Agents')
    w.unmount()
  })

  it('renders the CPU tile and summaries on success', async () => {
    stubApi(respond(200, current))
    const w = await mountOverview()
    const cpu = w.get('[data-testid="tile-cpu"]')
    expect(cpu.text()).toContain('12.5%')
    expect(cpu.text()).not.toContain('E-cores')
    expect(w.get('[data-testid="tile-throttling"]').text()).toContain('None')
    expect(w.get('[data-testid="tile-undervoltage"]').text()).toContain('None')
    expect(w.get('[data-testid="tile-disk"]').text()).toContain('not filling')
    expect(w.get('[data-testid="tile-services"]').text()).toContain('1 need attention')
    expect(w.get('[data-testid="tile-updates"]').text()).toContain('1 need a restart')
    expect(w.get('[data-testid="sample-age"]').text()).toContain('7 s ago')
    w.unmount()
  })

  it('hides Mac-only tiles and the macmon note', async () => {
    stubApi(respond(200, { ...current, macmon_status: 'restarting' }))
    const w = await mountOverview()
    for (const id of ['tile-gpu', 'tile-power', 'tile-fan', 'macmon-status', 'pressure-chip']) {
      expect(w.find(`[data-testid="${id}"]`).exists()).toBe(false)
    }
    w.unmount()
  })

  it('flags active undervoltage and throttling from the Pi firmware flags', async () => {
    stubApi(respond(200, { ...current, throttle_flags: ['under_voltage', 'previously_throttled'] }))
    const w = await mountOverview()
    expect(w.get('[data-testid="tile-undervoltage"]').text()).toContain('Active')
    expect(w.get('[data-testid="tile-throttling"]').text()).toContain('Since boot')
    w.unmount()
  })

  it('says flags are not reported when the host sends none', async () => {
    const { throttle_flags: _f, throttled: _t, ...noFlags } = current
    stubApi(respond(200, noFlags))
    const w = await mountOverview()
    expect(w.get('[data-testid="tile-throttling"]').text()).toContain('Not reported')
    w.unmount()
  })
})
