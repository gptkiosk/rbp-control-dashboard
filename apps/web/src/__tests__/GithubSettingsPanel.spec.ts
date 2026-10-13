import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import GithubSettingsPanel from '@/components/GithubSettingsPanel.vue'
import GithubView from '@/views/GithubView.vue'
import { stubFetch, calls, headerOf } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const migration = { state: 'migration_required', configured: false, message: 'GitHub is optional.' }
const ready = { state: 'ready', configured: true, enabled: true, account: 'example-user', repos: ['example-user/example-repo'], public_only: true, poll_seconds: 1800, version: 1, secrets_stored: false }

it('migrates explicitly with a reviewed allowlist and never sends a token', async () => {
  const f = stubFetch((url, init) => url === '/api/github/status' ? { body: migration } : url === '/api/github/migrate' && init?.method === 'POST' ? { body: { ...ready, login: { available: true, account: 'example-user' } } } : url === '/api/profile' ? { status: 401, body: {} } : undefined)
  const w = mount(GithubSettingsPanel); await flushPromises()
  expect(w.text()).toContain('optional and not set up yet')
  expect(w.text()).toContain('Profile > Contribution settings > Private contributions')
  await w.get('input[placeholder="your-github-login"]').setValue('example-user')
  await w.get('textarea').setValue('example-user/example-repo\nnot a repo')
  await w.get('form').trigger('submit'); await flushPromises()
  expect(calls(f, 'POST', '/api/github/migrate')).toHaveLength(0)
  expect(w.text()).toContain('is not in owner/name form')
  await w.get('textarea').setValue('example-user/example-repo')
  await w.get('select').setValue('1800')
  await w.get('form').trigger('submit'); await flushPromises()
  const [, init] = calls(f, 'POST', '/api/github/migrate')[0]!
  expect(JSON.parse(init!.body as string)).toEqual({ version: 1, enabled: true, account: 'example-user', repos: ['example-user/example-repo'], public_only: false, poll_seconds: 1800 })
  expect(headerOf(init, 'X-Mac-Control')).toBe('1')
  expect(w.text()).toContain('Active gh login: example-user')
  expect(w.emitted('changed')).toHaveLength(1)
  w.unmount()
})

it('turns GitHub off and refreshes only on request, and explains operator denial', async () => {
  const f = stubFetch((url, init) => url === '/api/github/status' ? { body: ready } : url === '/api/github/refresh' ? { body: {} } : url === '/api/github/config' && init?.method === 'PUT' ? { body: { state: 'disabled', configured: false, enabled: false, account: 'example-user', repos: ['example-user/example-repo'], public_only: true, poll_seconds: 1800 } } : { status: 401, body: {} })
  const w = mount(GithubSettingsPanel); await flushPromises()
  expect(w.text()).toContain('1 repositories')
  expect(calls(f, 'POST', '/api/github/refresh')).toHaveLength(0)
  const buttons = w.findAll('button')
  await buttons.find(b => b.text() === 'Refresh now')!.trigger('click'); await flushPromises()
  expect(calls(f, 'POST', '/api/github/refresh')).toHaveLength(1)
  await buttons.find(b => b.text() === 'Turn off')!.trigger('click'); await flushPromises()
  expect(JSON.parse(calls(f, 'PUT', '/api/github/config')[0]![1]!.body as string).enabled).toBe(false)
  expect(w.text()).toContain('No background checks will run')
  w.unmount()
  stubFetch((url, init) => url === '/api/github/status' ? { body: ready } : init?.method === 'PUT' ? { status: 403, body: { detail: 'x' } } : { status: 401, body: {} })
  const denied = mount(GithubSettingsPanel); await flushPromises()
  await denied.get('form').trigger('submit'); await flushPromises()
  expect(denied.text()).toContain('Operator sign-in is required')
  expect(denied.get('button.primary').attributes('disabled')).toBeDefined()
  denied.unmount()
})

it('shows a friendly optional setup prompt instead of an unavailable error in the GitHub view', async () => {
  stubFetch(() => ({ body: { repos: [], limited: false, checked_at: null, stale: false, error: null, setup: migration } }))
  const w = mount(GithubView, { global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } } }); await flushPromises()
  expect(w.text()).toContain('Set up GitHub (optional)')
  expect(w.text()).toContain('Nothing is checked in the background')
  expect(w.text()).toContain('Private contributions')
  expect(w.text()).not.toContain('unavailable')
  expect(w.find('.notice-warn').exists()).toBe(false)
  expect(w.get('a[href="/profile#github-settings"]').text()).toContain('Open GitHub settings')
  w.unmount()
})
