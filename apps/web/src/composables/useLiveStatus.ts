import { getCurrentInstance, onBeforeUnmount, ref } from 'vue'

/** One change pushed by `GET /api/events/stream` (see apps/api/live_status.py). */
export interface StatusEvent {
  type: 'card' | 'run' | 'run_event' | 'project' | 'bulk'
  change?: string
  card_id?: number | null
  run_id?: number
  project_id?: number
  column?: string
  stage?: string
  state?: string
  kind?: string
  ts?: number
}

/** `null` means "something may have been missed": refetch everything. */
export type StatusListener = (event: StatusEvent | null) => void

const STREAM_PATH = '/api/events/stream'
const BACKOFF_MS = [1000, 2000, 5000, 10000, 15000]
const BUSY_RETRY_MS = 30000

/** True while the shared stream is open; views poll slower then. */
export const liveConnected = ref(false)

const listeners = new Set<StatusListener>()
let source: EventSource | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null
let failures = 0
let lastId = ''

function emit(event: StatusEvent | null): void {
  for (const listener of [...listeners]) {
    try {
      listener(event)
    } catch {
      /* one view's error must not stop the others */
    }
  }
}

function close(): void {
  source?.close()
  source = null
  liveConnected.value = false
  if (retryTimer !== null) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
}

function reconnectAfter(ms: number): void {
  close()
  retryTimer = setTimeout(() => {
    retryTimer = null
    open()
  }, ms)
}

function open(): void {
  if (source || listeners.size === 0 || typeof EventSource === 'undefined') return
  // A fresh EventSource cannot send Last-Event-ID, so the cursor goes in the query.
  const es = new EventSource(lastId ? `${STREAM_PATH}?last=${encodeURIComponent(lastId)}` : STREAM_PATH)
  source = es
  const track = (e: MessageEvent) => {
    if (e.lastEventId) lastId = e.lastEventId
  }
  es.addEventListener('hello', (e) => {
    const msg = e as MessageEvent
    track(msg)
    failures = 0
    liveConnected.value = true
    // reset: first connection, or the API restarted and its buffer is gone.
    if (JSON.parse(msg.data).reset) emit(null)
  })
  es.addEventListener('status', (e) => {
    track(e as MessageEvent)
    emit(JSON.parse((e as MessageEvent).data) as StatusEvent)
  })
  es.addEventListener('reset', (e) => {
    track(e as MessageEvent)
    emit(null)
  })
  es.addEventListener('busy', () => reconnectAfter(BUSY_RETRY_MS))
  es.onerror = () => {
    liveConnected.value = false
    // CONNECTING: the browser retries by itself (dropped stream, API restart).
    // CLOSED: it gave up (e.g. a proxy answered 502 while the API was down); retry with backoff.
    if (es.readyState === EventSource.CLOSED) {
      reconnectAfter(BACKOFF_MS[Math.min(failures++, BACKOFF_MS.length - 1)])
    }
  }
}

/**
 * Subscribe to live card, run and project changes. All subscribers in a tab share one
 * EventSource, which closes when the last one unmounts. Without EventSource support the
 * listener is simply never called and polling carries on.
 */
export function useLiveStatus(listener: StatusListener): { stop: () => void } {
  listeners.add(listener)
  open()
  function stop(): void {
    listeners.delete(listener)
    if (listeners.size === 0) close()
  }
  if (getCurrentInstance()) onBeforeUnmount(stop)
  return { stop }
}

/** Test hook: forget the shared stream state. */
export function resetLiveStatus(): void {
  close()
  listeners.clear()
  failures = 0
  lastId = ''
}
