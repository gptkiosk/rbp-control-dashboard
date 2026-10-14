import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { liveConnected, resetLiveStatus, useLiveStatus } from '@/composables/useLiveStatus'
import { usePolledJson } from '@/composables/usePolledJson'
import { calls, stubFetch } from './helpers'

class FakeEventSource {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2
  static all: FakeEventSource[] = []
  readyState = FakeEventSource.CONNECTING
  onerror: (() => void) | null = null
  closed = false
  private handlers = new Map<string, ((e: MessageEvent) => void)[]>()
  url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.all.push(this)
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.handlers.set(type, [...(this.handlers.get(type) ?? []), fn])
  }
  close() {
    this.closed = true
    this.readyState = FakeEventSource.CLOSED
  }
  send(type: string, data: unknown, id = '') {
    this.readyState = FakeEventSource.OPEN
    const e = { data: JSON.stringify(data), lastEventId: id } as MessageEvent
    for (const fn of this.handlers.get(type) ?? []) fn(e)
  }
  fail(state: number) {
    this.readyState = state
    this.onerror?.()
  }
  static last() {
    return FakeEventSource.all[FakeEventSource.all.length - 1]
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeEventSource.all = []
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => {
  resetLiveStatus()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useLiveStatus', () => {
  it('shares one stream, delivers events and closes after the last subscriber', () => {
    const a = vi.fn()
    const b = vi.fn()
    const sa = useLiveStatus(a)
    const sb = useLiveStatus(b)
    expect(FakeEventSource.all).toHaveLength(1)
    const es = FakeEventSource.last()
    expect(es.url).toBe('/api/events/stream')

    es.send('hello', { boot: 'b1', reset: true }, 'b1:0')
    expect(liveConnected.value).toBe(true)
    expect(a).toHaveBeenCalledWith(null)
    es.send('status', { type: 'card', card_id: 4, column: 'running' }, 'b1:1')
    expect(b).toHaveBeenLastCalledWith({ type: 'card', card_id: 4, column: 'running' })

    sa.stop()
    expect(es.closed).toBe(false)
    sb.stop()
    expect(es.closed).toBe(true)
    expect(liveConnected.value).toBe(false)
  })

  it('reconnects with its cursor and backoff after the browser gives up, and resets on a new boot', () => {
    const listener = vi.fn()
    useLiveStatus(listener)
    const first = FakeEventSource.last()
    first.send('hello', { boot: 'b1', reset: true }, 'b1:0')
    first.send('status', { type: 'run', run_id: 9, stage: 'running' }, 'b1:7')

    // The browser retries on its own while CONNECTING (dropped stream): no new source.
    first.fail(FakeEventSource.CONNECTING)
    expect(FakeEventSource.all).toHaveLength(1)
    expect(liveConnected.value).toBe(false)

    // CLOSED (e.g. 502 from a proxy while the API restarts): retry after 1s with the cursor.
    first.fail(FakeEventSource.CLOSED)
    vi.advanceTimersByTime(999)
    expect(FakeEventSource.all).toHaveLength(1)
    vi.advanceTimersByTime(1)
    const second = FakeEventSource.last()
    expect(second.url).toBe('/api/events/stream?last=b1%3A7')
    second.fail(FakeEventSource.CLOSED)
    vi.advanceTimersByTime(2000)
    const third = FakeEventSource.last()
    expect(FakeEventSource.all).toHaveLength(3)

    // A restarted API answers with reset: every subscriber refetches.
    listener.mockClear()
    third.send('hello', { boot: 'b2', reset: true }, 'b2:0')
    expect(listener).toHaveBeenCalledWith(null)
    expect(liveConnected.value).toBe(true)
  })

  it('backs off for 30s when the server is at its subscriber cap', () => {
    useLiveStatus(vi.fn())
    FakeEventSource.last().send('busy', { max_subscribers: 16 })
    vi.advanceTimersByTime(29_999)
    expect(FakeEventSource.all).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeEventSource.all).toHaveLength(2)
  })
})

describe('usePolledJson with live refresh', () => {
  it('refetches once per burst of matching events and polls slower while connected', async () => {
    const f = stubFetch(() => ({ body: { cards: [] } }))
    // Mounted, because usePoll only follows a changing interval inside a component.
    const wrapper = mount(
      defineComponent({
        setup() {
          usePolledJson('/api/cards', 3000, { match: (e) => e.type !== 'project' })
          return () => h('div')
        },
      }),
    )
    await vi.advanceTimersByTimeAsync(0)
    expect(calls(f, 'GET', '/api/cards')).toHaveLength(1)

    const es = FakeEventSource.last()
    es.send('hello', { boot: 'b1', reset: false }, 'b1:0')
    es.send('status', { type: 'project', project_id: 1 }, 'b1:1')
    await vi.advanceTimersByTimeAsync(200)
    expect(calls(f, 'GET', '/api/cards')).toHaveLength(1) // not matched

    es.send('status', { type: 'card', card_id: 1, column: 'running' }, 'b1:2')
    es.send('status', { type: 'run', run_id: 3, card_id: 1, stage: 'running' }, 'b1:3')
    es.send('status', { type: 'run_event', run_id: 3, kind: 'stage' }, 'b1:4')
    await vi.advanceTimersByTimeAsync(150)
    expect(calls(f, 'GET', '/api/cards')).toHaveLength(2) // one refetch, well within 2s

    // Connected: the 3s poll slows to 15s.
    await vi.advanceTimersByTimeAsync(14_000)
    expect(calls(f, 'GET', '/api/cards')).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(calls(f, 'GET', '/api/cards')).toHaveLength(3)

    // Stream lost: back to the 3s poll.
    es.fail(FakeEventSource.CONNECTING)
    await vi.advanceTimersByTimeAsync(3_000)
    expect(calls(f, 'GET', '/api/cards')).toHaveLength(4)

    wrapper.unmount()
    expect(es.closed).toBe(true)
  })
})
