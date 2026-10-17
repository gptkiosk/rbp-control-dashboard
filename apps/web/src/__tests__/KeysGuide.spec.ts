import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import KeysGuide from '@/components/KeysGuide.vue'
import { stubFetch } from './helpers'
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })
const keys = [
  { id: 'agent', label: 'An agent signed in on this Mac', level: 'required', purpose: 'Runs tasks.', obtain: 'Agents, then Agent tools.', scope: 'Sign in to one.', in_place: true, detail: 'claude' },
  { id: 'fal', label: 'fal.ai key', level: 'optional', purpose: 'Video generation.', obtain: 'https://fal.ai/dashboard/keys', scope: 'API preset.', in_place: false, detail: 'not saved' },
  { id: 'github', label: 'GitHub access', level: 'optional', purpose: 'Branch grants.', obtain: 'Use gh.', scope: 'One branch.', in_place: null, detail: 'managed outside MCD' },
]
it('says what basic use needs, labels every key and shows whether it is in place', async () => {
  stubFetch(u => (u === '/api/keys' ? { body: { keys, basic_use: ['agent'], basic_use_ready: true } } : undefined))
  const w = mount(KeysGuide)
  await flushPromises()
  expect(w.text()).toContain('Basic use needs one thing')
  expect(w.text()).toContain('You have that.')
  expect(w.get('[data-key=agent]').text()).toContain('Required for basic use')
  expect(w.get('[data-key=fal]').text()).toContain('Optional')
  expect(w.get('[data-key=fal]').text()).toContain('Not in place')
  expect(w.get('[data-key=github]').text()).toContain('managed outside MCD')
  expect(w.get('[data-key=fal] a').attributes('href')).toBe('https://fal.ai/dashboard/keys')
  expect(w.find('[data-key=agent] a').exists()).toBe(false)           // plain text is never made a link
  w.unmount()
})
it('says plainly when no agent is available', async () => {
  stubFetch(u => (u === '/api/keys' ? { body: { keys, basic_use: ['agent'], basic_use_ready: false } } : undefined))
  const w = mount(KeysGuide)
  await flushPromises()
  expect(w.text()).toContain('None is available yet')
  w.unmount()
})
