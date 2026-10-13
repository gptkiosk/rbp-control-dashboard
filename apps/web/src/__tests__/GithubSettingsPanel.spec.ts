import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import GithubSettingsPanel from '@/components/GithubSettingsPanel.vue'
import GithubView from '@/views/GithubView.vue'
import { stubFetch, calls, headerOf } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const migration = { state: 'migration_required', configured: false, message: 'GitHub is optional.' }
const ready = { state: 'ready', configured: true, enabled: true, account: 'example-user', repos: ['example-user/example-repo'], public_only: true, poll_seconds: 1800, version: 1, secrets_stored: false }

const choice = (name: string, extra: Record<string, unknown> = {}) => ({ name, description: null, private: false, archived: false, updated_at: null, branch: 'main', ...extra })
const listing = { owner: 'example-user', repos: [choice('example-user/example-repo', { description: 'The main one' }), choice('example-user/secret', { private: true }), choice('example-user/old', { archived: true })], limited: false, private_included: true }
const profileOk = { status: 404, body: {} }
const route = (table: Record<string, unknown>) => (url: string, init?: RequestInit) => {
  const key = `${init?.method ?? 'GET'} ${url}`
  return key in table ? { body: table[key] } : url === '/api/profile' ? profileOk : { status: 404, body: { detail: 'unexpected ' + key } }
}
const boxes = (w: ReturnType<typeof mount>) => w.findAll('fieldset.repo-list input[type="checkbox"]')

it('migrates explicitly from a ticked list and never sends a token', async () => {
  const f = stubFetch(route({ 'GET /api/github/status': migration, 'GET /api/github/account-repos?owner=example-user': listing,
    'POST /api/github/migrate': { ...ready, login: { available: true, account: 'example-user' } } }))
  const w = mount(GithubSettingsPanel); await flushPromises()
  expect(w.text()).toContain('optional and not set up yet')
  expect(w.text()).toContain('Profile > Contribution settings > Private contributions')
  expect(w.find('textarea').exists()).toBe(false)                                              // no typed list any more
  expect(w.text()).toContain('Enter the account above')
  const account = w.get('input[placeholder="your-github-login"]')
  await account.setValue('example-user'); await account.trigger('blur'); await flushPromises()
  expect(calls(f, 'GET', '/api/github/account-repos?owner=example-user')).toHaveLength(1)
  expect(boxes(w)).toHaveLength(3); expect(w.text()).toContain('The main one'); expect(w.text()).toContain('private'); expect(w.text()).toContain('archived')
  await w.get('form').trigger('submit'); await flushPromises()
  expect(calls(f, 'POST', '/api/github/migrate')).toHaveLength(0)
  expect(w.text()).toContain('Choose at least one repository.')
  await boxes(w)[0]!.setValue(true)
  await w.get('select').setValue('1800')
  await w.get('form').trigger('submit'); await flushPromises()
  const [, init] = calls(f, 'POST', '/api/github/migrate')[0]!
  expect(JSON.parse(init!.body as string)).toEqual({ version: 1, enabled: true, account: 'example-user', repos: ['example-user/example-repo'], public_only: false, poll_seconds: 1800 })
  expect(headerOf(init, 'X-Mac-Control')).toBe('1')
  expect(w.text()).toContain('Active gh login: example-user')
  expect(w.emitted('changed')).toHaveLength(1)
  w.unmount()
})

it('pre-ticks the saved repositories, keeps one that is not in the list and lets the operator untick it', async () => {
  stubFetch(route({ 'GET /api/github/status': { ...ready, repos: ['example-user/example-repo', 'other/elsewhere'] }, 'GET /api/github/account-repos?owner=example-user': listing }))
  const w = mount(GithubSettingsPanel); await flushPromises()
  const checked = boxes(w).filter(b => (b.element as HTMLInputElement).checked).map(b => (b.element as HTMLInputElement).value)
  expect(checked.sort()).toEqual(['example-user/example-repo', 'other/elsewhere'])
  expect(w.text()).toContain('other/elsewhere'); expect(w.text()).toContain('not in example-user’s list')
  expect(w.text()).toContain('2 selected')
  await w.findAll('button').find(b => b.text() === 'Clear')!.trigger('click')
  expect(w.text()).toContain('0 selected')
  w.unmount()
})

it('filters a long list, selects what is shown and adds a repository by name with validation', async () => {
  const many = Array.from({ length: 12 }, (_, i) => choice(`example-user/repo-${String(i).padStart(2, '0')}`, { description: i === 3 ? 'special thing' : null }))
  const f = stubFetch(route({ 'GET /api/github/status': { ...ready, repos: [] }, 'GET /api/github/account-repos?owner=example-user': { ...listing, repos: many, limited: true },
    'PUT /api/github/config': { ...ready, repos: ['example-user/repo-03', 'octo/cat'] } }))
  const w = mount(GithubSettingsPanel); await flushPromises()
  expect(boxes(w)).toHaveLength(12); expect(w.text()).toContain('newest 100 repositories')
  await w.get('input[type="search"]').setValue('special'); expect(boxes(w)).toHaveLength(1)
  await w.findAll('button').find(b => b.text() === 'Select shown')!.trigger('click')
  await w.get('input[aria-label="Repository name"]').setValue('not valid')
  await w.findAll('button').find(b => b.text() === 'Add')!.trigger('click')
  expect(w.text()).toContain('Use the owner/name form')
  await w.get('input[aria-label="Repository name"]').setValue('octo/cat')
  await w.findAll('button').find(b => b.text() === 'Add')!.trigger('click')
  expect(w.text()).toContain('2 selected')
  await w.get('form').trigger('submit'); await flushPromises()
  expect(JSON.parse(calls(f, 'PUT', '/api/github/config')[0]![1]!.body as string).repos).toEqual(['example-user/repo-03', 'octo/cat'])
  w.unmount()
})

it('says why the list could not load and still allows adding by name', async () => {
  stubFetch((url) => url === '/api/github/status' ? { body: ready } : url.startsWith('/api/github/account-repos') ? { status: 404, body: { detail: 'No GitHub account or organisation named example-user is visible to this login.' } } : profileOk)
  const w = mount(GithubSettingsPanel); await flushPromises()
  expect(w.text()).toContain('No GitHub account or organisation named example-user')
  expect(w.text()).toContain('You can still add a repository by name below')
  expect(w.text()).toContain('example-user/example-repo')                                  // the saved one is still shown and can be removed
  w.unmount()
})

it('turns GitHub off and refreshes only on request, and explains operator denial', async () => {
  const f = stubFetch((url, init) => url === '/api/github/status' ? { body: ready } : url.startsWith('/api/github/account-repos') ? { body: listing } : url === '/api/github/refresh' ? { body: {} } : url === '/api/github/config' && init?.method === 'PUT' ? { body: { state: 'disabled', configured: false, enabled: false, account: 'example-user', repos: ['example-user/example-repo'], public_only: true, poll_seconds: 1800 } } : { status: 401, body: {} })
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
