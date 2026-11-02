import { describe, expect, it } from 'vitest'
import { iconFor, categoryFor } from '../lib/templateStore'

describe('teaching template identities', () => {
  it.each(['upubhub-class', 'upubhub-textbook', 'upubhub-lesson-plan'])('%s has its own image and teaching category', id => {
    expect(categoryFor(id)).toBe('Teaching')
    expect(iconFor(id)).toContain(id + '.webp')
  })
  it('keeps community placeholders and teaching images distinct', () => {
    expect(iconFor('community-example')).toBeNull()
    expect(categoryFor('community-example')).toBe('Template')
    expect(new Set(['upubhub-class', 'upubhub-textbook', 'upubhub-lesson-plan'].map(iconFor)).size).toBe(3)
  })
})
