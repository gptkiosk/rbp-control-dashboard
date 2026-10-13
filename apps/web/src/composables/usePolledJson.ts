import { getCurrentInstance, onBeforeUnmount, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { ApiError, getJson } from '@/lib/api'
import { usePoll } from './usePoll'
import { liveConnected, useLiveStatus, type StatusEvent } from './useLiveStatus'

/** Refetch when a matching live status event arrives; poll at `slowMs` while the stream is up. */
export interface LiveRefresh {
  match: (event: StatusEvent) => boolean
  slowMs?: number
}

const LIVE_DEBOUNCE_MS = 150
const LIVE_SLOW_MS = 15000

/**
 * Poll a JSON endpoint. `pending` is true while the API answers 503 (it has
 * nothing to report yet); `error` holds any other failure while the last good
 * `data` stays on screen. Changing `path` clears the data and refetches.
 *
 * With `live`, matching status events refetch within LIVE_DEBOUNCE_MS (a burst of
 * events from one commit costs one request) and polling slows to `slowMs` while the
 * stream is connected. Polling stays the fallback when the stream is down.
 */
export function usePolledJson<T>(
  path: MaybeRefOrGetter<string>,
  intervalMs: MaybeRefOrGetter<number>,
  live?: LiveRefresh,
) {
  const data = shallowRef<T | null>(null)
  const error = ref<string | null>(null)
  const pending = ref(false)
  const loaded = ref(false)
  let seq = 0

  async function load(): Promise<void> {
    const mine = ++seq
    try {
      const result = await getJson<T>(toValue(path))
      if (mine !== seq) return
      data.value = result
      error.value = null
      pending.value = false
    } catch (e) {
      if (mine !== seq) return
      if (e instanceof ApiError && e.status === 503) {
        pending.value = true
        error.value = null
      } else {
        pending.value = false
        error.value = e instanceof Error ? e.message : String(e)
      }
    } finally {
      if (mine === seq) loaded.value = true
    }
  }

  const interval = live
    ? () => (liveConnected.value ? Math.max(toValue(intervalMs), live.slowMs ?? LIVE_SLOW_MS) : toValue(intervalMs))
    : intervalMs
  const poll = usePoll(load, interval)

  if (live) {
    let timer: ReturnType<typeof setTimeout> | null = null
    useLiveStatus((event) => {
      if (timer !== null || (event && !live.match(event))) return
      timer = setTimeout(() => {
        timer = null
        if (!document.hidden) poll.refresh() // a hidden tab refetches when it becomes visible
      }, LIVE_DEBOUNCE_MS)
    })
    if (getCurrentInstance()) onBeforeUnmount(() => timer !== null && clearTimeout(timer))
  }

  watch(
    () => toValue(path),
    () => {
      data.value = null
      error.value = null
      pending.value = false
      loaded.value = false
      poll.refresh()
    },
  )

  return { data, error, pending, loaded, refresh: poll.refresh }
}
