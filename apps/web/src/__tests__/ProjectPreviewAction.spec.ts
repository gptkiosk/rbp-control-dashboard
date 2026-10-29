import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ProjectPreviewAction from '@/components/ProjectPreviewAction.vue'
import type { Card } from '@/lib/api'
import { stubFetch } from './helpers'
afterEach(() => { vi.unstubAllGlobals() })
const card = { id: 31, blocked_by: [], project: { id: 2 } } as unknown as Card

it('says plainly when the last verifier run failed and that the story waits for a pass', async () => {
  // Pilot 2026-10-29: the verifier failed (exit 1) and the story still looked ready to accept.
  let ok = false
  stubFetch(() => ({ body: { available: true, kind: 'preview-verify', actions: ['verify'], running: false, state: null,
    last_verify: { ok, at: 1793277272, summary: 'x', output: ok ? '{"status": "passed"}' : "No such file or directory: 'node'" } } }))
  let w = mount(ProjectPreviewAction, { props: { card } })
  await flushPromises()
  expect(w.get('[data-testid=verify-result]').text()).toContain('cannot be accepted until it passes')
  expect(w.get('[data-testid=verify-result]').text()).toMatch(/failed \(.*2026.*\)/)                  // when it ran, so an old result is not mistaken for a new one
  expect(w.get('pre').text()).toContain("'node'")
  w.unmount(); ok = true
  w = mount(ProjectPreviewAction, { props: { card } })
  await flushPromises()
  expect(w.get('[data-testid=verify-result]').text()).toContain('passed')
  w.unmount()
})

it('disables the action and says why when the server would refuse it, though the board shows nothing blocking', async () => {
  // Pilot 2026-10-29: the server refused every press because of an earlier story, and the panel showed only the old result.
  stubFetch(() => ({ body: { available: true, kind: 'preview-verify', actions: ['verify'], running: false, state: null, last_verify: null,
    blocked_by: ['#17 Author the media inventory: latest run has not succeeded.'] } }))
  const w = mount(ProjectPreviewAction, { props: { card } })
  await flushPromises()
  expect(w.get('[data-testid=preview-blocked]').text()).toContain('#17 Author the media inventory')
  expect(w.get('button').attributes('disabled')).toBeDefined()
  w.unmount()
})
