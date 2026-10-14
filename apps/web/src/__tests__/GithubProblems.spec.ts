import { afterEach, expect, it, vi } from 'vitest'
import { problemLine } from '@/lib/operations'

afterEach(() => vi.restoreAllMocks())

it('says what is wrong with each repository in plain words', () => {
  expect(problemLine({ name: 'gptkiosk/rpd-control-dashboard', reason: 'not_found', hint: 'gptkiosk/rbp-control-dashboard' }))
    .toBe('gptkiosk/rpd-control-dashboard was not found for this GitHub login. Check the spelling in Settings > GitHub. Did you mean gptkiosk/rbp-control-dashboard?')
  expect(problemLine({ name: 'a/b', reason: 'not_found' })).not.toContain('Did you mean')
  expect(problemLine({ name: 'a/b', reason: 'denied' })).toContain('refused access to a/b')
  expect(problemLine({ name: 'a/b', reason: 'unavailable' })).toContain('could not be read right now')
})
