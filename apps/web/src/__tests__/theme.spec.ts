import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { useThemeStore, THEME_KEY } from '@/stores/theme'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

let light = false
let changed: (() => void) | undefined
let store: ReturnType<typeof useThemeStore> | undefined
beforeEach(() => {
  localStorage.clear()
  light = false
  changed = undefined
  document.documentElement.removeAttribute('data-theme')
  vi.stubGlobal('matchMedia', () => ({ matches: light,
    addEventListener: (_event: string, listener: () => void) => { changed = listener },
    removeEventListener: vi.fn(),
  }))
  setActivePinia(createPinia())
})
afterEach(() => { store?.stop(); store = undefined; localStorage.clear(); vi.unstubAllGlobals() })

describe('App appearance', () => {
  it('applies the saved or device theme before the app loads, including unavailable storage', () => {
    const source = readFileSync('public/assets/theme-init.js', 'utf8')
    for (const [stored, deviceLight, expected] of [['dark', true, 'dark'], ['light', false, 'light'], ['invalid', true, 'light'], [null, false, 'dark']] as const) {
      const root = { dataset: {} as Record<string, string> }
      runInNewContext(source, { document: { documentElement: root }, window: { matchMedia: () => ({ matches: deviceLight }) },
        localStorage: { getItem: (key: string) => { expect(key).toBe(THEME_KEY); if (stored === null) throw new Error('blocked'); return stored } } })
      expect(root.dataset.theme).toBe(expected)
    }
  })
  it('follows the device until an explicit choice, then preserves the choice across visits', () => {
    store = useThemeStore(); store.start()
    expect(store.mode).toBe('dark')
    light = true; changed?.()
    expect(document.documentElement.dataset.theme).toBe('light')
    store.toggle()
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    changed?.()
    expect(store.mode).toBe('dark')
    store.stop()
    setActivePinia(createPinia())
    store = useThemeStore(); store.start()
    expect(store.mode).toBe('dark')
  })
  it('synchronizes browser tabs and follows the device again after clearing the preference', () => {
    store = useThemeStore(); store.start()
    window.dispatchEvent(new StorageEvent('storage', { key: THEME_KEY, newValue: 'light' }))
    expect(store.mode).toBe('light')
    window.dispatchEvent(new StorageEvent('storage', { key: THEME_KEY, newValue: null }))
    expect(store.mode).toBe('dark')
  })
  it('still toggles when storage is blocked and labels the next action accessibly', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    store = useThemeStore(); store.start()
    const wrapper = mount(ThemeToggle)
    expect(wrapper.get('button').attributes('aria-label')).toBe('Switch to light mode')
    await wrapper.get('button').trigger('click')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(wrapper.get('button').attributes('aria-label')).toBe('Switch to dark mode')
    wrapper.unmount()
    vi.restoreAllMocks()
  })
})
