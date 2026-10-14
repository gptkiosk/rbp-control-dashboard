import { getCurrentInstance, onBeforeUnmount, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { getJson, type LogChunk, type RunStage } from '@/lib/api'
import { usePoll } from './usePoll'

/**
 * Tail a run's log: ask for `?offset=N`, append `text`, continue from `next_offset`, and stop
 * polling once the server says `done`. Changing the run id starts over for the new run.
 */
export function useLogTail(runId: MaybeRefOrGetter<number | null>, intervalMs = 1000) {
  const text = ref('')
  const done = ref(false)
  const stage = ref<RunStage | null>(null)
  const error = ref<string | null>(null)

  let offset = 0
  let gen = 0
  let busyGen = -1
  let poll: { stop: () => void } | null = null

  async function tick(): Promise<void> {
    const id = toValue(runId)
    const mine = gen
    if (id == null || done.value || busyGen === mine) return
    busyGen = mine
    try {
      const chunk = await getJson<LogChunk>(`/api/runs/${id}/log?offset=${offset}`)
      if (mine !== gen) return
      if (chunk.text) text.value += chunk.text
      offset = chunk.next_offset
      stage.value = chunk.stage
      error.value = null
      if (chunk.done) {
        done.value = true
        poll?.stop()
      }
    } catch (e) {
      if (mine === gen) error.value = e instanceof Error ? e.message : String(e)
    } finally {
      if (busyGen === mine) busyGen = -1
    }
  }

  function start(): void {
    poll?.stop()
    gen++
    offset = 0
    text.value = ''
    done.value = false
    stage.value = null
    error.value = null
    poll = usePoll(tick, intervalMs)
  }

  start()
  watch(() => toValue(runId), start)
  if (getCurrentInstance()) onBeforeUnmount(() => poll?.stop())

  return { text, done, stage, error, stop: () => poll?.stop() }
}
