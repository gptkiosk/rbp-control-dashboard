import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { HEALTH_POLL_MS, useHealthStore } from '@/stores/health'

const payload = {
  status: 'ok',
  version: '0.1.0',
  git_sha: 'ab20698',
  uptime_s: 12.3,
  data_dir_writable: true,
  web_built: true,
}

function okResponse() {
  return { ok: true, status: 200, json: async () => payload } as Response
}

describe('health store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('sets ok state from a successful fetch', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse())
    vi.stubGlobal('fetch', fetchMock)
    const store = useHealthStore()
    await store.refresh()
    expect(fetchMock.mock.calls[0]![0]).toBe('/healthz')
    expect(store.state).toBe('ok')
    expect(store.version).toBe('0.1.0')
    expect(store.gitSha).toBe('ab20698')
    expect(store.uptimeS).toBe(12.3)
  })

  it('sets error state when fetch rejects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network down')))
    const store = useHealthStore()
    await store.refresh()
    expect(store.state).toBe('error')
  })

  it('sets error state on a non-ok HTTP response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502 } as Response))
    const store = useHealthStore()
    await store.refresh()
    expect(store.state).toBe('error')
  })

  it('polls on an interval and stop() clears it', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue(okResponse())
    vi.stubGlobal('fetch', fetchMock)
    const store = useHealthStore()

    store.start()
    store.start() // idempotent: no second timer
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(HEALTH_POLL_MS)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    store.stop()
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(HEALTH_POLL_MS * 3)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
