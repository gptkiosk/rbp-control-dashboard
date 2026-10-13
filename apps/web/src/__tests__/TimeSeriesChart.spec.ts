import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import TimeSeriesChart from '@/components/TimeSeriesChart.vue'
import { formatPct } from '@/lib/format'
import { createPinia, setActivePinia } from 'pinia'
import { useThemeStore } from '@/stores/theme'
import { flushPromises } from '@vue/test-utils'

const plotCalls = vi.hoisted(() => ({ create: vi.fn(), destroy: vi.fn() }))
vi.mock('uplot', () => ({ default: class {
  height = 220
  constructor(options: unknown, data: unknown) { plotCalls.create(options, data) }
  destroy() { plotCalls.destroy() }
  setData() {}
  setSize() {}
} }))

// uPlot reads matchMedia when its module loads; jsdom does not provide it.
vi.hoisted(() => {
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})

describe('TimeSeriesChart', () => {
  it('shows "No data yet" for an empty series', () => {
    const w = mount(TimeSeriesChart, {
      global: { plugins: [createPinia()] },
      props: { title: 'CPU %', series: { ts: [], cpu_pct: [] }, lines: [{ field: 'cpu_pct', label: 'CPU' }], format: formatPct },
    })
    expect(w.text()).toContain('No data yet')
    w.unmount()
  })

  it('shows "No data yet" when every value is null, and with no payload', () => {
    const w = mount(TimeSeriesChart, {
      global: { plugins: [createPinia()] },
      props: { title: 'GPU %', series: { ts: [1, 2], gpu_pct: [null, null] }, lines: [{ field: 'gpu_pct', label: 'GPU' }], format: formatPct },
    })
    expect(w.text()).toContain('No data yet')
    w.unmount()
    const w2 = mount(TimeSeriesChart, {
      global: { plugins: [createPinia()] },
      props: { title: 'GPU %', series: null, lines: [{ field: 'gpu_pct', label: 'GPU' }], format: formatPct },
    })
    expect(w2.text()).toContain('No data yet')
    w2.unmount()
  })

  it('recreates canvas colours on a theme switch while retaining the chart data', async () => {
    const pinia = createPinia(); setActivePinia(pinia)
    plotCalls.create.mockClear(); plotCalls.destroy.mockClear()
    const series = { ts: [1, 2], cpu_pct: [10, 20] }
    document.documentElement.style.setProperty('--series-1', '#4c9aff')
    const w = mount(TimeSeriesChart, { global: { plugins: [pinia] },
      props: { title: 'CPU %', series, lines: [{ field: 'cpu_pct', label: 'CPU' }], format: formatPct } })
    await flushPromises()
    expect(plotCalls.create.mock.calls[0]?.[0].series[1].stroke).toBe('#4c9aff')
    document.documentElement.style.setProperty('--series-1', '#175dba')
    useThemeStore().toggle()
    await flushPromises()
    expect(plotCalls.destroy).toHaveBeenCalledTimes(1)
    expect(plotCalls.create.mock.calls[1]?.[0].series[1].stroke).toBe('#175dba')
    expect(plotCalls.create.mock.calls[1]?.[1]).toEqual([[1, 2], [10, 20]])
    w.unmount()
    document.documentElement.style.removeProperty('--series-1')
    localStorage.clear()
  })
})
