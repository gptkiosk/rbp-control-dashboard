import { ref } from 'vue'
import { defineStore } from 'pinia'

export const HEALTH_POLL_MS = 15_000

export interface HealthPayload {
  status: string
  version: string
  git_sha: string
  uptime_s: number
  data_dir_writable?: boolean
  web_built?: boolean
}

export type HealthState = 'unknown' | 'ok' | 'error'

export const useHealthStore = defineStore('health', () => {
  const state = ref<HealthState>('unknown')
  const version = ref('')
  const gitSha = ref('')
  const uptimeS = ref<number | null>(null)
  const lastChecked = ref<number | null>(null)

  let timer: ReturnType<typeof setInterval> | null = null

  async function refresh(): Promise<void> {
    try {
      const res = await fetch('/healthz', { cache: 'no-store' })
      if (!res.ok) throw new Error(`healthz returned ${res.status}`)
      const data = (await res.json()) as HealthPayload
      version.value = data.version
      gitSha.value = data.git_sha
      uptimeS.value = data.uptime_s
      state.value = data.status === 'ok' ? 'ok' : 'error'
    } catch {
      state.value = 'error'
      uptimeS.value = null
    } finally {
      lastChecked.value = Date.now()
    }
  }

  function start(): void {
    if (timer !== null) return
    void refresh()
    timer = setInterval(() => void refresh(), HEALTH_POLL_MS)
  }

  function stop(): void {
    if (timer === null) return
    clearInterval(timer)
    timer = null
  }

  return { state, version, gitSha, uptimeS, lastChecked, refresh, start, stop }
})
