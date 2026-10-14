import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppIcon from '@/components/AppIcon.vue'
import { ICONS, type IconName } from '@/icons/icons'

describe('AppIcon', () => {
  it('draws on a 16 grid with the Mission Control stroke style', () => {
    const svg = mount(AppIcon, { props: { name: 'overview' } }).get('svg')
    expect(svg.attributes('viewBox')).toBe('0 0 16 16')
    expect(svg.attributes('fill')).toBe('none')
    expect(svg.attributes('stroke')).toBe('currentColor')
    expect(svg.attributes('stroke-width')).toBe('1.5')
    expect(svg.attributes('stroke-linecap')).toBe('round')
    expect(svg.attributes('stroke-linejoin')).toBe('round')
  })

  it('is hidden from assistive tech without a label', () => {
    const svg = mount(AppIcon, { props: { name: 'cpu' } }).get('svg')
    expect(svg.attributes('aria-hidden')).toBe('true')
    expect(svg.attributes('focusable')).toBe('false')
    expect(svg.attributes('role')).toBeUndefined()
    expect(svg.attributes('aria-label')).toBeUndefined()
  })

  it('is an image with a name when given a label', () => {
    const svg = mount(AppIcon, { props: { name: 'alert', label: 'Crash loop' } }).get('svg')
    expect(svg.attributes('role')).toBe('img')
    expect(svg.attributes('aria-label')).toBe('Crash loop')
    expect(svg.attributes('aria-hidden')).toBeUndefined()
  })

  it('maps size to a class, defaulting to md', () => {
    expect(mount(AppIcon, { props: { name: 'plus' } }).get('svg').classes()).toContain('icon-md')
    expect(mount(AppIcon, { props: { name: 'plus', size: 'sm' } }).get('svg').classes()).toContain('icon-sm')
    expect(mount(AppIcon, { props: { name: 'plus', size: 'lg' } }).get('svg').classes()).toContain('icon-lg')
  })

  it('renders at least one child element for every icon name', () => {
    const names = Object.keys(ICONS) as IconName[]
    expect(names.length).toBeGreaterThanOrEqual(34)
    for (const name of names) {
      const svg = mount(AppIcon, { props: { name } }).get('svg')
      expect(svg.element.children.length, name).toBeGreaterThan(0)
      expect(svg.element.children.length, name).toBe(ICONS[name].length)
      for (const child of Array.from(svg.element.children)) {
        expect(child.namespaceURI, name).toBe('http://www.w3.org/2000/svg')
      }
    }
  })
})
