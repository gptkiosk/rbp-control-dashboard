import { ref } from 'vue'
import { defineStore } from 'pinia'

export type Theme = 'light' | 'dark'
export const THEME_KEY = 'mcd.theme.v1'
const valid = (value: string | null): value is Theme => value === 'light' || value === 'dark'

function preference(): Theme | null {
  try { const value = localStorage.getItem(THEME_KEY); return valid(value) ? value : null }
  catch { return null }
}
function deviceTheme(): Theme {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export const useThemeStore = defineStore('theme', () => {
  let explicit = preference()
  const mode = ref<Theme>(explicit ?? deviceTheme())
  let media: MediaQueryList | undefined
  let started = false

  function apply(value: Theme) {
    mode.value = value
    document.documentElement.dataset.theme = value
    document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', value)
    const background = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()
    if (background) document.querySelector('meta[name="theme-color"]')?.setAttribute('content', background)
  }
  function choose(value: Theme | 'system') {
    explicit = value === 'system' ? null : value
    apply(explicit ?? deviceTheme())
    try { if (explicit) localStorage.setItem(THEME_KEY, explicit); else localStorage.removeItem(THEME_KEY) } catch { /* Browser storage optional. */ }
  }
  function toggle() {
    explicit = mode.value === 'dark' ? 'light' : 'dark'
    apply(explicit)
    try { localStorage.setItem(THEME_KEY, explicit) } catch { /* Theme works without browser storage. */ }
  }
  function systemChanged() { if (!explicit) apply(deviceTheme()) }
  function storageChanged(event: StorageEvent) {
    if (event.key !== THEME_KEY && event.key !== null) return
    explicit = event.key === null ? null : valid(event.newValue) ? event.newValue : null
    apply(explicit ?? deviceTheme())
  }
  function start() {
    if (started) return
    started = true
    apply(mode.value)
    window.addEventListener('storage', storageChanged)
    if (typeof window.matchMedia === 'function') {
      media = window.matchMedia('(prefers-color-scheme: light)')
      if (media.addEventListener) media.addEventListener('change', systemChanged)
      else media.addListener?.(systemChanged)
    }
  }
  function stop() {
    window.removeEventListener('storage', storageChanged)
    if (media?.removeEventListener) media.removeEventListener('change', systemChanged)
    else media?.removeListener?.(systemChanged)
    media = undefined
    started = false
  }
  return { mode, toggle, choose, start, stop }
})
