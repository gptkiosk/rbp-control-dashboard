import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useLogTail } from '@/composables/useLogTail'
import { stubFetch } from './helpers'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useLogTail', () => {
  it('appends text across polls using next_offset and stops once done', async () => {
    const chunks = [
      { text: 'hello ', next_offset: 6, done: false, stage: 'running' },
      { text: 'world', next_offset: 11, done: true, stage: 'succeeded' },
    ]
    let i = 0
    const f = stubFetch(() => ({ body: chunks[Math.min(i++, chunks.length - 1)] }))

    const tail = useLogTail(() => 7, 1000)
    await vi.advanceTimersByTimeAsync(0)
    expect(tail.text.value).toBe('hello ')
    expect(tail.done.value).toBe(false)

    await vi.advanceTimersByTimeAsync(1000)
    expect(tail.text.value).toBe('hello world')
    expect(tail.done.value).toBe(true)
    expect(tail.stage.value).toBe('succeeded')

    await vi.advanceTimersByTimeAsync(5000)
    expect(f).toHaveBeenCalledTimes(2)
    expect(f.mock.calls.map((c) => c[0])).toEqual(['/api/runs/7/log?offset=0', '/api/runs/7/log?offset=6'])
    tail.stop()
  })
})
