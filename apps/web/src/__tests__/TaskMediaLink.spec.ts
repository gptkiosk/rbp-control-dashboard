import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import TaskApprovalAction from '@/components/TaskApprovalAction.vue'
import { stubFetch } from './helpers'
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })
const card = (over: object) => ({ id: 193, title: '4d. Generate media (human, MCD)', body: 'Generate stills and clips in MCD.', acceptance: '', column: 'backlog', assignee_type: 'human', blocked_by: [], approval_reasons: [],
  project: { id: 6, node_key: 's4d', role: 'story' }, last_run: null, ...over }) as never
const summary = { published: 4, skipped: 1, pending: 5, total: 10, complete: false, text: 'Media: 4 of 10 slots published, 1 skipped (the site uses its fallback), 5 still undecided.' }
async function mountCard(c: unknown, available = true) {
  stubFetch((u) => (u === '/api/media/project/6' ? { body: available ? { available: true, working_dir: '/ws', summary } : { available: false } } : undefined))
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
  expect(link.text()).toContain('Open media review (4 of 10 published)')
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
