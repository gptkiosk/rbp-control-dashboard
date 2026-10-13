import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { usePoll } from '@/composables/usePoll'

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
}

describe('usePoll', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setHidden(false)
  })

  afterEach(() => {
    vi.useRealTimers()
    setHidden(false)
  })

  function mountPoller(fn: () => unknown, ms = 1000) {
    return mount(
      defineComponent({
        setup() {
          usePoll(fn, ms)
          return () => h('div')
        },
      }),
    )
  }

  it('calls immediately, then on the interval', async () => {
    const fn = vi.fn()
    const w = mountPoller(fn)
    expect(fn).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(3000)
    expect(fn).toHaveBeenCalledTimes(4)
    w.unmount()
  })

  it('skips ticks while the document is hidden', async () => {
    const fn = vi.fn()
    const w = mountPoller(fn)
    setHidden(true)
    await vi.advanceTimersByTimeAsync(3000)
    expect(fn).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('clears its timer on unmount', async () => {
    const fn = vi.fn()
    const w = mountPoller(fn)
    expect(vi.getTimerCount()).toBe(1)
    w.unmount()
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(5000)
    expect(fn).toHaveBeenCalledTimes(1)
  })
})
