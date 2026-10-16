import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import GithubActionsPanel from '@/components/GithubActionsPanel.vue'
import ProjectGitAccess from '@/components/ProjectGitAccess.vue'
import { stubFetch, calls } from './helpers'

afterEach(() => vi.unstubAllGlobals())

const repoAction = { id: 'a1', fingerprint: 'f'.repeat(64), state: 'draft', preview: { kind: 'repository', repo: 'me/site', destination: 'https://github.com/me/site',
  payload: { name: 'site', description: 'A site', private: true, auto_init: true } } }

it('shows the exact request, and runs it once only after the operator confirms', async () => {
  let pending = [repoAction]
  const f = stubFetch((url, init) => {
    if (url === '/api/github/actions') return { body: { actions: pending, writes_enabled: true } }
    if (url === '/api/github/actions/a1/run' && init?.method === 'POST') { pending = []; return { body: { state: 'succeeded', result: { html_url: 'https://github.com/me/site' } } } }
    return undefined
  })
  const w = mount(GithubActionsPanel); await flushPromises()
  const card = w.get('[data-testid="action-a1"]')
  expect(card.text()).toContain('Create a private repository')
  expect(card.text()).toContain('always private')
  expect(card.get('pre').text()).toContain('"private": true')
  const run = card.get('button')
  expect(run.attributes('disabled')).toBeDefined()
  await card.get('input[type="checkbox"]').setValue(true)
  await run.trigger('click'); await flushPromises()
  const sent = calls(f, 'POST', '/api/github/actions/a1/run')
  expect(sent).toHaveLength(1)
  expect(JSON.parse(String(sent[0]![1]!.body))).toEqual({ fingerprint: 'f'.repeat(64), confirm: true })
  expect(w.get('[data-testid="action-done"] a').attributes('href')).toBe('https://github.com/me/site')
  expect(w.text()).toContain('Nothing is waiting.')
  w.unmount()
})

it('cannot run anything while GitHub writes are off and links only to github.com', async () => {
  stubFetch(url => url === '/api/github/actions' ? { body: { actions: [repoAction], writes_enabled: false } } : undefined)
  const w = mount(GithubActionsPanel); await flushPromises()
  expect(w.get('[data-testid="writes-off"]').text()).toContain('MAC_CONTROL_GITHUB_WRITES_ENABLED')
  expect(w.get('input[type="checkbox"]').attributes('disabled')).toBeDefined()
  expect(w.get('button').attributes('disabled')).toBeDefined()
  w.unmount()
})

it('grants exactly one project branch after confirmation, and names the branch before anything is sent', async () => {
  const f = stubFetch((url, init) => {
    if (url === '/api/projects/5/git-grant' && !init?.method) return { body: { clones: [] } }
    if (url === '/api/github/status') return { body: { repos: ['me/other', 'me/site'] } }
    if (url === '/api/projects/5/git-grant' && init?.method === 'POST') return { status: 201, body: { clones: [{ dir: 'site', repo: 'me/site', branch: 'project-5/setup' }] } }
    return undefined
  })
  const w = mount(ProjectGitAccess, { props: { projectId: 5 } }); await flushPromises()
  expect(w.get('[data-testid="git-branch"]').text()).toContain('project-5/setup')
  expect(w.text()).toContain('main branch can never be named')
  const submit = w.get('button[type="submit"]')
  expect(submit.attributes('disabled')).toBeDefined()
  expect(calls(f, 'POST', '/api/projects/5/git-grant')).toHaveLength(0)
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('form').trigger('submit'); await flushPromises()
  const sent = calls(f, 'POST', '/api/projects/5/git-grant')
  expect(JSON.parse(String(sent[0]![1]!.body))).toEqual({ repo: 'me/site', dir: 'site', slug: 'setup', confirm: true })
  expect(w.get('[data-testid="git-clones"]').text()).toContain('project-5/setup')
  w.unmount()
})
