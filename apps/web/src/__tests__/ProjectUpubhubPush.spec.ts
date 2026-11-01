import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ProjectUpubhubPush from '@/components/ProjectUpubhubPush.vue'
import type { Card } from '@/lib/api'
import { calls, stubFetch } from './helpers'
afterEach(() => { vi.unstubAllGlobals() })
const stubs = { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } }
const card = (title: string) => ({ id: 41, title, blocked_by: [], project: { id: 3 } }) as unknown as Card
const status = (over: Record<string, unknown> = {}) => ({ plan: { kind: 'class', title: 'Forces', lessons: 2, images: 1 }, blocked_by: [], token_saved: true,
  target: 'https://upubhub.com', problems: [], last: null, ...over })

it('never asks about other stories, including the final sign-off', async () => {
  const f = stubFetch(() => ({ body: status() }))
  for (const title of ['Write lesson 1', 'Approve the course for upubhub']) {
    const w = mount(ProjectUpubhubPush, { props: { card: card(title) }, ...stubs }); await flushPromises()
    expect(w.find('[data-testid=upubhub-push]').exists()).toBe(false)
    w.unmount()
  }
  expect(f).not.toHaveBeenCalled()
})

it('says what it waits for and keeps the button off until the sign-off, the token and the package are ready', async () => {
  stubFetch(() => ({ body: status({ blocked_by: ['#40 Approve the course for upubhub is not done.'], token_saved: false, problems: ['UPLOAD.md is missing.'] }) }))
  const w = mount(ProjectUpubhubPush, { props: { card: card('Push the course to upubhub') }, ...stubs }); await flushPromises()
  expect(w.get('[data-testid=push-blocked]').text()).toContain('final sign-off')
  expect(w.get('[data-testid=push-token]').text()).toContain('Also allow pushing classes')
  expect(w.get('[data-testid=push-problems]').text()).toContain('UPLOAD.md is missing.')
  expect(w.get('[data-action=upubhub-push]').attributes('disabled')).toBeDefined()
  expect(w.text()).toContain('private drafts and an invite-only, free class')
  w.unmount()
})

it('pushes and links to what landed on upubhub', async () => {
  let pushed = false
  const f = stubFetch((url, init) => {
    if (init?.method === 'POST') { pushed = true; return { body: {} } }
    return { body: status(pushed ? { last: { kind: 'class', pushed_at: '2026-11-01T10:00:00Z', textbook: { external_id: 'forces-textbook', url_path: '/dashboard/works/41', visibility: 'private' },
      lesson_plans: [], class: { external_id: 'forces', url_path: '/classes/12', visibility: 'invite_only', assignments: [{ external_id: '01', assessment: 'waiting' }] } } } : {}) }
  })
  const w = mount(ProjectUpubhubPush, { props: { card: card('Push the course to upubhub') }, ...stubs }); await flushPromises()
  await w.get('[data-action=upubhub-push]').trigger('click'); await flushPromises()
  expect(calls(f, 'POST', '/api/projects/3/stories/41/upubhub-push')).toHaveLength(1)
  const result = w.get('[data-testid=push-result]')
  expect(result.findAll('a').map(a => a.attributes('href'))).toEqual(['https://upubhub.com/dashboard/works/41', 'https://upubhub.com/classes/12'])
  expect(result.text()).toContain('invite only')
  expect(result.text()).toContain('wait for their lessons to pass moderation')
  expect(w.get('[data-action=upubhub-push]').text()).toContain('Push again')
  w.unmount()
})
