import { afterEach, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import LoadingCard from '@/components/LoadingCard.vue'

afterEach(() => { vi.useRealTimers() })

it('says what is loading at once and that it is still working after a few seconds', async () => {
  vi.useFakeTimers()
  const w = mount(LoadingCard, { props: { title: 'Opening Through the Little Door…', detail: 'Loading its plan.' } })
  expect(w.get('[role="status"]').attributes('aria-busy')).toBe('true')
  expect(w.text()).toContain('Opening Through the Little Door…')
  expect(w.find('[data-testid="loading-slow"]').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(4000)
  expect(w.get('[data-testid="loading-slow"]').text()).toContain('Still working')
  w.unmount()
})
