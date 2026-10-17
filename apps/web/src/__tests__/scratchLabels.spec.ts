import { expect, it } from 'vitest'
import { directoryDetailFor, directoryLabel } from '@/lib/selectLabels'

it('labels the scratch area as the recommended private folder and leaves every other folder alone', () => {
  const scratch = '/Users/me/.mac-control/workspaces'
  expect(directoryLabel(scratch, scratch)).toContain('Scratch folder')
  expect(directoryDetailFor(scratch, null, scratch)).toContain('No repository, branch or grant')
  expect(directoryLabel('/Users/me/Bamcio-Workspace/site', scratch)).toBe('site')
  expect(directoryDetailFor('/Users/me/site', 'main', scratch)).toBe('main · /Users/me/site')
  expect(directoryLabel(scratch)).toBe('workspaces')                      // no scratch root configured: nothing special
})
