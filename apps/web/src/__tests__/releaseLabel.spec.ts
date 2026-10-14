import { describe, expect, it } from 'vitest'
import { releaseLabel } from '@/lib/releaseLabel'

const base = { version: '0.1.0', environment: 'local', commit_sha: 'b2bf245deadbeef', has_migrations: false }

describe('releaseLabel', () => {
  it('is empty without a release', () => {
    expect(releaseLabel(null, 'abc1234')).toBe('')
    expect(releaseLabel(undefined, '')).toBe('')
  })

  it('shows just the api sha when the web sha is empty', () => {
    expect(releaseLabel(base, '')).toBe('v0.1.0 • local • b2bf245')
  })

  it('shows "unknown" for a missing or unknown api sha', () => {
    expect(releaseLabel({ ...base, commit_sha: 'unknown' }, '')).toBe('v0.1.0 • local • unknown')
    expect(releaseLabel({ ...base, commit_sha: null }, '')).toBe('v0.1.0 • local • unknown')
    expect(releaseLabel({ ...base, commit_sha: undefined }, '4594185')).toBe(
      'v0.1.0 • local • api unknown · web 4594185',
    )
  })

  it('shows both shas when the web sha is present', () => {
    expect(releaseLabel(base, '4594185')).toBe('v0.1.0 • local • api b2bf245 · web 4594185')
  })

  it('still shows both shas when they match', () => {
    expect(releaseLabel({ ...base, commit_sha: '4594185' }, '4594185')).toBe(
      'v0.1.0 • local • api 4594185 · web 4594185',
    )
  })

  it('appends the migrations marker', () => {
    expect(releaseLabel({ ...base, has_migrations: true }, '')).toBe('v0.1.0 • local • b2bf245 • migrations')
    expect(releaseLabel({ ...base, has_migrations: true }, '4594185')).toBe(
      'v0.1.0 • local • api b2bf245 · web 4594185 • migrations',
    )
  })

  it('says so when the running build differs from its commit', () => {
    expect(releaseLabel({ ...base, dirty: true }, 'b2bf245')).toBe('v0.1.0 • local • api b2bf245 · web b2bf245 • modified')
    expect(releaseLabel({ ...base, dirty: false }, '')).toBe('v0.1.0 • local • b2bf245')
  })
})
