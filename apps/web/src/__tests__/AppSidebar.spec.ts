import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import AppSidebar from '@/components/AppSidebar.vue'
import { createAppRouter } from '@/router'
import { navIcon, navItems } from '@/router/routes'

describe('AppSidebar icons', () => {
  it('renders one decorative svg per nav item, matching the route icon', async () => {
    const router = createAppRouter(createMemoryHistory())
    router.push('/')
    await router.isReady()
    const w = mount(AppSidebar, { props: { open: true }, global: { plugins: [router] } })

    const links = w.findAll('nav a')
    expect(links).toHaveLength(navItems.length)
    links.forEach((a, i) => {
      expect(a.findAll('svg')).toHaveLength(1)
      expect(a.get('svg').attributes('aria-hidden')).toBe('true')
      expect(a.get('svg').attributes('data-icon')).toBe(navItems[i]!.icon)
      expect(a.text()).toBe(navItems[i]!.label)
    })
    expect(w.findAll('nav svg')).toHaveLength(navItems.length)
  })

  it('shares the icon through route metadata', () => {
    const router = createAppRouter(createMemoryHistory())
    for (const item of navItems) {
      expect(router.resolve(item.path).meta.icon).toBe(item.icon)
      expect(navIcon(item.name)).toBe(item.icon)
    }
  })
})
