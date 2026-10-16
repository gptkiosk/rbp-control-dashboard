import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import BugReportDialog from '@/components/BugReportDialog.vue'
import { useBugReportStore } from '@/stores/bugReport'
import { stubFetch, calls } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })

const REPO = 'gptkiosk/mac-control-dashboard'
const preview = (over: Record<string, unknown> = {}) => ({
  title: 'Delete is greyed out', body: '### What happened\nThe button is disabled.\n\n### Environment\n- Product: Mac Control Dashboard 0.5.5', scrubbed: ['what: 1 home paths'],
  url: `https://github.com/${REPO}/issues/new?labels=bug-report&title=x&body=y`, truncated: false, mode: 'direct', reason: 'r', repository: REPO, ...over,
})

async function open(mode: 'direct' | 'prefilled', previewBody: Record<string, unknown> = {}) {
  const pinia = createPinia(); setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory()); await router.push('/tasks'); await router.isReady()
  const f = stubFetch((url, init) => {
    if (url === '/api/bug-reports/capabilities') return { body: { repository: REPO, mode, reason: mode === 'direct' ? 'You will see the exact issue first.' : 'The report opens on GitHub for you to submit.' } }
    if (url === '/api/bug-reports/preview') return { body: preview({ mode, ...previewBody }) }
    if (url === '/api/bug-reports/file' && init?.method === 'POST') return { status: 201, body: { state: 'succeeded', url: `https://github.com/${REPO}/issues/42`, action_id: 'a' } }
    return undefined
  })
  const w = mount(BugReportDialog, { global: { plugins: [pinia, router] }, attachTo: document.body })
  useBugReportStore().show(); await flushPromises()
  return { w, f }
}
async function fillAndPreview(w: ReturnType<typeof mount>) {
  await w.get('input.input').setValue('Delete is greyed out')
  await w.get('textarea.input').setValue('The button is disabled.')
  await w.get('form').trigger('submit'); await flushPromises()
}

it('shows how the report will be sent and sends nothing until the person previews and confirms', async () => {
  const { w, f } = await open('direct')
  expect(w.text()).toContain('You will see the exact issue first.')
  expect(calls(f, 'POST', '/api/bug-reports/preview')).toHaveLength(0)
  await fillAndPreview(w)
  expect(w.get('[data-testid="bug-preview-body"]').text()).toContain('### Environment')
  expect(w.get('[data-testid="bug-scrubbed"]').text()).toContain('1 home paths')
  const send = w.findAll('button').find(b => b.text() === 'Send to GitHub')!
  expect(send.attributes('disabled')).toBeDefined()                                     // not until the box is ticked
  expect(calls(f, 'POST', '/api/bug-reports/file')).toHaveLength(0)
  await w.get('section.preview input[type="checkbox"]').setValue(true)
  await send.trigger('click'); await flushPromises()
  const sent = calls(f, 'POST', '/api/bug-reports/file')
  expect(sent).toHaveLength(1)
  expect(JSON.parse(String(sent[0]![1]!.body))).toMatchObject({ title: 'Delete is greyed out', confirm: true, page: '/tasks', include_environment: true })
  expect(w.text()).toContain('Your report was filed on GitHub')
  expect(w.get('a[href]').attributes('href')).toBe(`https://github.com/${REPO}/issues/42`)
  w.unmount()
})

it('opens a prefilled GitHub page where filing from the app is not available, and only for the official repository', async () => {
  const { w } = await open('prefilled')
  await fillAndPreview(w)
  const link = w.findAll('a').find(a => a.text() === 'Open GitHub to submit')!
  expect(link.attributes('href')).toMatch(new RegExp(`^https://github.com/${REPO}/issues/new\\?`))
  expect(link.attributes('target')).toBe('_blank'); expect(link.attributes('rel')).toContain('noopener')
  expect(w.findAll('button').some(b => b.text() === 'Send to GitHub')).toBe(false)
  w.unmount()
  const other = await open('prefilled', { url: 'https://evil.example/issues/new?x=1' })
  await fillAndPreview(other.w)
  expect(other.w.findAll('a').some(a => a.text() === 'Open GitHub to submit')).toBe(false)     // a link that is not the official repository is never offered
  other.w.unmount()
})

it('shows the server refusal and keeps the report so nothing is lost', async () => {
  const pinia = createPinia(); setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory()); await router.push('/'); await router.isReady()
  stubFetch(url => {
    if (url === '/api/bug-reports/capabilities') return { body: { repository: REPO, mode: 'direct', reason: 'r' } }
    if (url === '/api/bug-reports/preview') return { status: 422, body: { detail: 'Say what happened.' } }
    return undefined
  })
  const w = mount(BugReportDialog, { global: { plugins: [pinia, router] }, attachTo: document.body })
  useBugReportStore().show(); await flushPromises()
  await w.get('input.input').setValue('Title'); await w.get('textarea.input').setValue('x')
  await w.get('form').trigger('submit'); await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('Say what happened.')
  expect((w.get('input.input').element as HTMLInputElement).value).toBe('Title')
  w.unmount()
})
