import { getCurrentInstance, onBeforeUnmount, toValue, watch, type MaybeRefOrGetter } from 'vue'

/**
 * Call `fn` now, then every `intervalMs`. Ticks are skipped while the tab is
 * hidden and one fires as soon as it becomes visible again. The timer and the
 * listener are removed when the owning component unmounts.
 *
 * `fn` is responsible for its own error handling; a rejected promise from it is
 * swallowed here so one failed poll cannot raise an unhandled rejection.
 */
export function usePoll(fn: () => unknown, intervalMs: MaybeRefOrGetter<number>) {
  let timer: ReturnType<typeof setInterval> | null = null

  function run(): void {
    try {
      const out = fn()
      if (out && typeof (out as Promise<unknown>).catch === 'function') {
        void (out as Promise<unknown>).catch(() => {})
      }
    } catch {
      /* see doc comment */
    }
  }

  function clear(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function arm(): void {
    clear()
    timer = setInterval(() => {
      if (!document.hidden) run()
    }, toValue(intervalMs))
  }

  function onVisibility(): void {
    if (!document.hidden) run()
  }

  function stop(): void {
    clear()
    document.removeEventListener('visibilitychange', onVisibility)
  }

  run()
  arm()
  document.addEventListener('visibilitychange', onVisibility)

  if (getCurrentInstance()) {
    if (typeof intervalMs !== 'number') watch(() => toValue(intervalMs), arm)
    onBeforeUnmount(stop)
  }

  return { refresh: run, stop }
}
