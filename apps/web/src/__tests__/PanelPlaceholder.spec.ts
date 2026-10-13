import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PanelPlaceholder from '@/components/PanelPlaceholder.vue'

describe('PanelPlaceholder', () => {
  it('renders title, description and phase chip', () => {
    const wrapper = mount(PanelPlaceholder, {
      props: { title: 'Tasks', description: 'A task board for agents.', phase: '3' },
    })
    expect(wrapper.get('h1').text()).toBe('Tasks')
    expect(wrapper.text()).toContain('A task board for agents.')
    expect(wrapper.get('[data-testid="phase-chip"]').text()).toBe('Coming in Phase 3')
  })
})
