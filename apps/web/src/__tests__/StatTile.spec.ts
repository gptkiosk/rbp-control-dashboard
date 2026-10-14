import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import StatTile from '@/components/StatTile.vue'

describe('StatTile', () => {
  it('renders its icon beside the label when given one', () => {
    const w = mount(StatTile, { props: { label: 'CPU', value: '12%', icon: 'cpu' } })
    expect(w.findAll('svg')).toHaveLength(1)
    expect(w.get('h2 svg').attributes('data-icon')).toBe('cpu')
    expect(w.get('h2').text()).toBe('CPU')
  })

  it('renders no icon when none is given', () => {
    const w = mount(StatTile, { props: { label: 'CPU', value: '12%' } })
    expect(w.findAll('svg')).toHaveLength(0)
    expect(w.get('h2').classes()).not.toContain('has-icon')
  })
})
