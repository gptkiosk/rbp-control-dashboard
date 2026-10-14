import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { getJson, postJson } from '@/lib/api'
export interface AuthStatus {
  enabled: boolean
  user: { email: string; method: string; expires_at: number } | null
  local_recovery: boolean
}
export const useAuthStore = defineStore('auth', () => {
  const enabled = ref<boolean | null>(null)
  const user = ref<AuthStatus['user']>(null)
  const localRecovery = ref(false)
  const error = ref('')
  const access = computed(() => !error.value && (enabled.value === false || !!user.value))
  let timer: ReturnType<typeof setInterval> | null = null
  async function refresh() {
    try {
      const status = await getJson<AuthStatus>('/auth/status')
      if (typeof status.enabled !== 'boolean') throw new Error('Invalid sign-in status')
      enabled.value = status.enabled
      user.value = status.user
      localRecovery.value = status.local_recovery
      error.value = ''
    } catch {
      error.value = 'Could not check sign-in status. Retry when the dashboard is reachable.'
      user.value = null
    }
  }
  function expired() { user.value = null; enabled.value = true; void refresh() }
  async function logout() {
    try { await postJson('/auth/logout'); user.value = null; window.location.assign('/login') }
    catch { error.value = 'Sign-out could not complete. Retry when the dashboard is reachable.' }
  }
  function start() {
    if (timer) return
    void refresh()
    timer = setInterval(() => void refresh(), 60000)
    window.addEventListener('mcd:auth-expired', expired)
  }
  function stop() {
    if (timer) clearInterval(timer)
    timer = null
    window.removeEventListener('mcd:auth-expired', expired)
  }
  return { enabled, user, localRecovery, error, access, refresh, logout, start, stop }
})
