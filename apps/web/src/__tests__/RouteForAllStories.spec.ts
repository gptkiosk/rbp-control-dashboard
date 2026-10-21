import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RouteForAllStories from '@/components/RouteForAllStories.vue'
import { stubFetch } from './helpers'

afterEach(() => { vi.unstubAllGlobals() })
const opt = (agent: string, model: string, price_class: string, allowed = true) => ({ agent, model, price_class, allowed, installed: true, cost: '' })
const info = { policy: { enabled: false, apply_to_stories: false, routes: [] }, options: [
  opt('openclaw', 'vendor/a:free', 'free'), opt('claude', 'claude-haiku-5-5', 'subscription'), opt('codex', 'gpt-6-luna', 'subscription'),
  opt('openclaw', 'vendor/unpriced:free', 'unknown', false)] }

it('picks one main route and ordered backups for every story, subscription routes first, and hides routes that are not allowed', async () => {
  stubFetch(url => url === '/api/profile/route-reliability' ? { body: info } : undefined)
  const w = mount(RouteForAllStories, { props: { busy: false } }); await flushPromises()
  const options = w.findAll('[data-test="main"] option').map(o => o.text())
  expect(options.slice(1)).toEqual(['Claude · claude-haiku-5-5 (subscription)', 'Codex · gpt-6-luna (subscription)', 'OpenClaw · vendor/a:free (free)'])
  expect(w.get('[data-action="route-all"]').attributes('disabled')).toBeDefined()
  await w.get('[data-test="main"]').setValue('claude|claude-haiku-5-5')
  const boxes = () => w.findAll('.backups input[type="checkbox"]')
  expect(boxes()).toHaveLength(2)                                       // the main route is not offered as its own backup
  await boxes()[1]!.setValue(true); await boxes()[0]!.setValue(true)     // free first, then Codex: the order is the click order
  expect(w.findAll('.order').map(o => o.text())).toEqual(['2', '1'])
  await w.get('[data-action="route-all"]').trigger('click')
  expect(w.emitted('apply')![0]).toEqual([{ agent: 'claude', model: 'claude-haiku-5-5' }, [{ agent: 'openclaw', model: 'vendor/a:free' }, { agent: 'codex', model: 'gpt-6-luna' }]])
  w.unmount()
})
