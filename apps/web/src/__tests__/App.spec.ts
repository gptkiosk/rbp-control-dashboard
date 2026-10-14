import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import App from '@/App.vue'
import { createAppRouter } from '@/router'

describe('App shell', () => {
  it('marks the active link, toggles the menu, and stops polling on unmount', async () => {
    vi.stubGlobal('fetch', vi.fn((path) => path === '/auth/status' ? Promise.resolve(new Response(JSON.stringify({ enabled: false, user: null, local_recovery: false }))) : Promise.reject(new Error('offline'))))
    const router = createAppRouter(createMemoryHistory())
    router.push('/tasks')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    const active = wrapper.findAll('nav[aria-label="Main"] a[aria-current="page"]')
    expect(active).toHaveLength(1)
    expect(active[0]!.text()).toBe('Tasks')
    expect(wrapper.text()).toContain('API unreachable')

    const btn = wrapper.get('button.menu-button')
    expect(btn.attributes('aria-expanded')).toBe('false')
    await btn.trigger('click')
    expect(btn.attributes('aria-expanded')).toBe('true')

    wrapper.unmount()
    vi.unstubAllGlobals()
  })
})
