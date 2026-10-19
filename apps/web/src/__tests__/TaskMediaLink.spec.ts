import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import TaskApprovalAction from '@/components/TaskApprovalAction.vue'
import { stubFetch } from './helpers'
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })
const card = (over: object) => ({ id: 193, title: '4d. Generate media (human, MCD)', body: 'Generate stills and clips in MCD.', acceptance: '', column: 'backlog', assignee_type: 'human', blocked_by: [], approval_reasons: [],
  project: { id: 6, node_key: 's4d', role: 'story' }, last_run: null, ...over }) as never
const cost = { remaining_usd: 3.2, remaining_items: 5, unpriced: 0, spent_usd: 1.1, spent_runs: 3 }
const summary = { published: 4, skipped: 1, pending: 5, total: 10, complete: false, text: 'Media: 4 of 10 slots published, 1 skipped (the site uses its fallback), 5 still undecided.' }
async function mountCard(c: unknown, available = true) {
  stubFetch((u) => (u === '/api/media/project/6' ? { body: available ? { available: true, working_dir: '/ws', summary, cost } : { available: false } } : undefined))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/')
  await router.isReady()
  const w = mount(TaskApprovalAction, { props: { card: c as never }, global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return w
}
it('sends the reviewer of a human media story straight to the media review, with where the slots stand', async () => {
  const w = await mountCard(card({}))
  const link = w.get('[data-testid=media-link]')
  expect(link.attributes('href')).toBe('/projects?project=6&view=media')
  expect(link.text()).toContain('Open media studio (4 of 10 published · about $3.20 left to make (5 items))')
  w.unmount()
})
it('shows the summary in the decision box and can use it as the decision', async () => {
  const w = await mountCard(card({}))
  await w.get('button.approval-button').trigger('click'); await flushPromises()
  const box = document.querySelector('[data-testid=media-box]') as HTMLElement
  expect(box.textContent).toContain('4 of 10 slots published')
  ;(box.querySelector('button') as HTMLButtonElement).click(); await flushPromises()
  expect((document.querySelector('textarea') as HTMLTextAreaElement).value).toBe(summary.text)
  w.unmount()
})
it('offers no media link on a story that is not about media or on a project without media slots', async () => {
  const other = await mountCard(card({ title: '6. Preview checkpoint and decision', body: 'Look at the pages.' }))
  expect(other.find('[data-testid=media-link]').exists()).toBe(false)
  other.unmount()
  const none = await mountCard(card({}), false)
  expect(none.find('[data-testid=media-link]').exists()).toBe(false)
  none.unmount()
})

it('shows the full callout with the money in plain words, and says nothing is generated until confirmed', async () => {
  const { default: MediaCallout } = await import('@/components/MediaCallout.vue')
  const router = createAppRouter(createMemoryHistory())
  await router.push('/'); await router.isReady()
  const w = mount(MediaCallout, { props: { media: { available: true, summary, cost }, link: '/projects?project=6&view=media' }, global: { plugins: [router] } })
  const text = w.get('[data-testid=media-callout]').text()
  expect(text).toContain('4 of 10 published')
  expect(text).toContain('Left to make')
  expect(text).toContain('about $3.20 · 5 items')
  expect(text).toContain('Spent so far')
  expect(text).toContain('about $1.10')
  expect(text).toContain('spends from your fal account')
  expect(text).toContain('Nothing is generated until you confirm there')
  expect(w.get('[data-testid=media-link]').attributes('href')).toBe('/projects?project=6&view=media')
  await w.setProps({ media: { available: true, summary, cost: { ...cost, remaining_items: 0, remaining_usd: 0, spent_runs: 0, spent_usd: 0 } } })
  expect(w.text()).toContain('nothing left')
  expect(w.text()).toContain('nothing yet')
  await w.setProps({ media: { available: false } })
  expect(w.find('[data-testid=media-callout]').exists()).toBe(false)
})
