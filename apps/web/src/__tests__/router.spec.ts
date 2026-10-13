import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import { navItems } from '@/router/routes'

const NAMES = ['overview', 'pi', 'services', 'projects', 'tasks', 'agents', 'chat', 'mcp', 'github', 'reports', 'help', 'profile']

describe('router', () => {
  const router = createAppRouter(createMemoryHistory())

  it('has all twelve navigation routes, sign-in and the catch-all', () => {
    const names = router.getRoutes().map((r) => r.name)
    for (const n of NAMES) expect(names).toContain(n)
    expect(names).toContain('not-found')
    expect(names).toContain('login')
    expect(names).toContain('setup')
    expect(router.getRoutes()).toHaveLength(16)
  })

  it('redirects the old /mac path, keeping the hash', () => {
    const r = router.resolve('/mac#ts-title')
    expect(r.name).toBe('pi')
    expect(r.hash).toBe('#ts-title')
  })

  it('keeps sidebar order and paths', () => {
    expect(navItems.map((n) => n.name)).toEqual(NAMES)
    expect(navItems.map((n) => n.path)).toEqual([
      '/', '/pi', '/services', '/projects', '/tasks', '/agents', '/chat', '/mcp', '/github', '/reports', '/help', '/profile',
    ])
  })

  it('resolves unknown paths to not-found', () => {
    expect(router.resolve('/nope/at/all').name).toBe('not-found')
  })
})

import { pageTitle, APP_TITLE } from '@/router'

describe('page titles', () => {
  it('suffixes the section with RCD and falls back to the product name', () => {
    expect(pageTitle('Tasks')).toBe('Tasks · RCD')
    expect(pageTitle(undefined)).toBe(APP_TITLE)
    expect(APP_TITLE).toBe('Raspberry Pi Control Dashboard')
  })
})
