import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AppFooter from '@/components/AppFooter.vue'

afterEach(() => vi.unstubAllGlobals())

describe('AppFooter', () => {
  it('renders the copyright line and the release label', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          version: '0.1.0', environment: 'local', commit_sha: 'b2bf245', has_migrations: false, owner: 'Example Organization',
        }),
      }),
    )
    const w = mount(AppFooter)
    await flushPromises()
    expect(w.get('.copyright').text()).toBe(`© ${new Date().getFullYear()} Raspberry Pi Control Dashboard · Example Organization`)
    expect(w.get('[data-testid="release-label"]').text()).toContain('v0.1.0 • local • ')
    expect(w.get('[data-testid="release-label"]').text()).toContain('b2bf245')
  })

  it('still renders the copyright when the release call fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const w = mount(AppFooter)
    await flushPromises()
    expect(w.text()).toContain('Raspberry Pi Control Dashboard · RCD')
    expect(w.find('[data-testid="release-label"]').exists()).toBe(false)
  })
})
