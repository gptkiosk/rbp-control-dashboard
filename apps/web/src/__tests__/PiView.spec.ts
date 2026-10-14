import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import PiView from '@/views/PiView.vue'
import { throttlingStatus, undervoltageStatus } from '@/lib/piHealth'

// uPlot reads matchMedia when its module loads; jsdom does not provide it.
vi.hoisted(() => {
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})

afterEach(() => vi.unstubAllGlobals())

const current = {
  ts: 1, cpu_pct: 12.5, mem_used: 1.5 * 1024 ** 3, mem_total: 4 * 1024 ** 3, swap_used: 0, swap_total: 512 * 1024 ** 2,
  disk_used: 20 * 1024 ** 3, disk_total: 64 * 1024 ** 3, cpu_temp: 61.3, sample_age_s: 4,
  mem_used_pct: 37.5, swap_used_pct: 0, disk_used_pct: 31.3, disk_days_to_full: null,
  platform: 'linux', throttled: false, throttle_flags: [] as string[],
}

function respond(body: unknown, status = 200) {
  return { ok: status < 300, status, json: async () => body }
}

const requested: string[] = []

function stubApi(metrics: unknown) {
  requested.length = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    requested.push(url)
    if (url.startsWith('/api/metrics/current')) return respond(metrics)
    if (url.startsWith('/api/metrics/series')) return respond({ range: '1h', step_s: 10, series: { ts: [] } })
    if (url.startsWith('/api/processes/top')) return respond({ apps: [{ app: 'python3', cpu_pct: 3, rss: 1e8, count: 2 }] })
    if (url.startsWith('/api/tailscale')) return respond({ error: 'not installed' })
    if (url.startsWith('/api/updates')) return respond({ updates: [], checked_at: 1 })
    return respond({ detail: 'nope' }, 404)
  }))
}

async function mountPi() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/pi')
  await router.isReady()
  const w = mount(PiView, { global: { plugins: [router, createPinia()] } })
  await flushPromises()
  return w
}

describe('PiView', () => {
  it('is titled Pi health and shows the Pi tiles with live values', async () => {
    stubApi(current)
    const w = await mountPi()
    expect(w.get('h1').text()).toBe('Pi health')
    expect(w.get('[data-testid="tile-temp"]').text()).toContain('61.3 °C')
    expect(w.get('[data-testid="tile-throttling"]').text()).toContain('None')
    expect(w.get('[data-testid="tile-undervoltage"]').text()).toContain('None')
    expect(w.get('[data-testid="tile-cpu"]').text()).toContain('12.5%')
    expect(w.get('[data-testid="tile-memory"]').text()).toContain('37.5%')
    expect(w.get('[data-testid="tile-swap"]').text()).toContain('0 B')
    expect(w.get('[data-testid="tile-disk"]').text()).toContain('31.3%')
    expect(w.get('[data-testid="tile-disk"]').text()).toContain('SD / NVMe')
    w.unmount()
  })

  it('shows active under-voltage and throttling since boot', async () => {
    stubApi({ ...current, throttle_flags: ['under_voltage', 'previously_throttled'] })
    const w = await mountPi()
    expect(w.get('[data-testid="tile-undervoltage"]').text()).toContain('Active')
    expect(w.get('[data-testid="tile-throttling"]').text()).toContain('Since boot')
    w.unmount()
  })

  it('requests only Pi series and no Mac-only charts', async () => {
    stubApi(current)
    const w = await mountPi()
    const series = requested.find((u) => u.startsWith('/api/metrics/series'))!
    expect(series).toContain('cpu_temp')
    expect(series).not.toMatch(/gpu|power|ecpu|pcpu/)
    expect(w.text()).not.toMatch(/GPU|E-cores|P-cores|Power|\bMac\b/)
    w.unmount()
  })
})

describe('piHealth flags', () => {
  it('separates active, past and unreported states', () => {
    expect(throttlingStatus({ throttle_flags: ['frequency_capped'] })).toMatchObject({ tone: 'danger', value: 'Active', detail: 'Frequency capped' })
    expect(undervoltageStatus({ throttle_flags: ['previously_under_voltage'] })).toMatchObject({ tone: 'warn', value: 'Since boot' })
    expect(undervoltageStatus({ throttle_flags: ['frequency_capped'] })).toMatchObject({ tone: 'ok', value: 'None' })
    expect(throttlingStatus({})).toMatchObject({ tone: 'muted', value: 'Not reported' })
  })
})
