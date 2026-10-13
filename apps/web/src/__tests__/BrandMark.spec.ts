import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import BrandMark from '@/components/BrandMark.vue'

describe('BrandMark', () => {
  it('is decorative and gives every instance its own gradient id', () => {
    const a = mount(BrandMark)
    const b = mount(BrandMark)
    expect(a.get('svg').attributes('aria-hidden')).toBe('true')
    const idA = a.get('linearGradient').attributes('id')
    const idB = b.get('linearGradient').attributes('id')
    expect(idA).not.toBe(idB)
    expect(a.get('rect').attributes('fill')).toBe(`url(#${idA})`)
  })
})
