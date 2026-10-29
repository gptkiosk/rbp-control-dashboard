import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CredentialsPanel from '@/components/CredentialsPanel.vue'
import { stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })
const keys = [
  { id: 'agent', label: 'An agent signed in on this Mac', level: 'required', purpose: 'Runs tasks.', obtain: 'Agents, then Agent tools.', scope: 'Sign in to one.', in_place: true, detail: 'claude, codex' },
  { id: 'fal', label: 'fal.ai key', level: 'optional', purpose: 'Video generation. Needs a key.', obtain: 'https://fal.ai/dashboard/keys', scope: 'API preset.', in_place: false, detail: 'not saved' },
  { id: 'github', label: 'GitHub access', level: 'optional', purpose: 'Branch grants.', obtain: 'Use gh.', scope: 'One branch.', in_place: null, detail: 'managed outside RCD' },
]
const props = (over: Record<string, unknown> = {}) => ({ credentials: [{ provider: 'openrouter', hint: '1234' }], secrets: { openrouter: '', discord: '', fal: '' }, busy: false, shareOn: false, spending: null, ...over })
const stubs = { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } }

it('shows every key as one card: whether it is in place, one line on what it is for, and where to get it', async () => {
  stubFetch(u => (u === '/api/keys' ? { body: { keys, basic_use_ready: true } } : undefined))
  const w = mount(CredentialsPanel, { props: props(), ...stubs }); await flushPromises()
  expect(w.get('[data-key="agent"]').text()).toContain('Required')
  expect(w.get('[data-key="agent"] [data-test="word"]').text()).toBe('ready')
  expect(w.get('[data-key="openrouter"] [data-test="word"]').text()).toBe('Saved ····1234')
  expect(w.get('[data-key="fal"] [data-test="word"]').text()).toBe('not set')
  expect(w.get('[data-key="fal"]').text()).toContain('Video generation.')            // the first sentence only
  expect(w.get('[data-key="fal"]').text()).not.toContain('Needs a key.')
  expect(w.find('[data-key="fal"] a[href="https://fal.ai/dashboard/keys"]').exists()).toBe(true)
  expect(w.find('[data-key="agent"] a[href^="http"]').exists()).toBe(false)           // plain text is never made a link
  expect(w.get('[data-key="github"]').text()).toContain('signed in with gh')
  w.unmount()
})

it('still lets a key be saved when the guide cannot be read, and says nothing is saved yet', async () => {
  stubFetch(() => undefined)
  const w = mount(CredentialsPanel, { props: props({ credentials: [] }), ...stubs }); await flushPromises()
  expect(w.findAll('input[type="password"]').map(i => i.attributes('aria-label'))).toEqual(['openrouter credential', 'fal credential', 'upubhub credential', 'discord credential'])
  expect(w.find('[data-key="agent"]').exists()).toBe(false)
  await w.get('[aria-label="fal credential"]').setValue('abc')
  expect(w.emitted('secret')![0]).toEqual(['fal', 'abc'])
  w.unmount()
})
