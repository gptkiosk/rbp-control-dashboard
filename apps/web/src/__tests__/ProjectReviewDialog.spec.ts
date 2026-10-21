import { afterEach, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ProjectReviewDialog from '@/components/ProjectReviewDialog.vue'
import { stubFetch } from './helpers'

afterEach(() => { document.body.innerHTML = '' })

const story = (key: string, over: Record<string, unknown> = {}) => ({ key, kind: 'story', title: 'Story ' + key, description: 'd', acceptance: 'done', scope: 'files', parent: null, depends_on: [], assignee: 'openclaw', model: 'openrouter/x:free', agent_target: '', mode: 'edit', rationale: '', x: 0, y: 0, fallbacks: [], routes: [], ...over })
const base = (over: Record<string, unknown> = {}) => ({
  mode: 'submit', projectId: 5, revision: 6, title: 'Site', workingDir: '/work/site', planningBias: 50, plannerAgent: 'hermes', plannerModel: 'x', dispatchMode: 'sequential',
  delegator: 'Hermes', stories: [story('a'), story('b', { depends_on: ['a'] })], titles: { a: 'Story a' }, needsPaidWork: false, standardsCheck: null, error: '', busy: false,
  coordination: true, paidPlanner: false, paidWork: false, fresh: false, ...over,
})
const open = (props: Record<string, unknown>) => { stubFetch(() => ({ body: { advice: [] } })); return mount(ProjectReviewDialog, { props: props as never, attachTo: document.body }) }
const dlg = () => document.body.querySelector('[role=dialog]') as HTMLElement
const confirmButton = () => [...dlg().querySelectorAll('button')].find(b => /Submit approved revision|Start planning/.test(b.textContent ?? ''))! as HTMLButtonElement

it('shows the facts, a short explanation and one action row instead of a wall of text', () => {
  const w = open(base())
  const t = dlg().textContent ?? ''
  expect(t).toContain('Review project submission'); expect(t).toContain('/work/site'); expect(t).toContain('One story at a time, in dependency order')
  expect(dlg().querySelector('.actions')).not.toBeNull()
  expect([...dlg().querySelectorAll('.actions button')].map(b => b.textContent?.trim())).toEqual(['Back to map', 'Submit approved revision'])
  expect(dlg().querySelectorAll('details')).toHaveLength(2)                                   // stories and billing are folded away
  w.unmount()
})

it('lists what the standards check found, once each, and will not submit until they are fixed', () => {
  const problems = ["h1: area 'business-logic' is not one of this repository's areas", 'x: risk low is below the standards minimum high for area tests-only']
  const w = open(base({ standardsCheck: { source: 'repository', property: 'site', problems, areas: ['tests-only', 'user-interface'] } }))
  const result = dlg().querySelector('[data-testid=standards-result]')!
  expect(result.textContent).toContain('2 things need fixing')
  expect([...result.querySelectorAll('li')].map(l => l.textContent)).toEqual(problems)
  expect(result.textContent).toContain('Areas these standards list: tests-only, user-interface.')
  expect(confirmButton().disabled).toBe(true)                                                 // even with the approval ticked
  w.unmount()
  const ok = open(base({ standardsCheck: { source: 'repository', problems: [], areas: [] } }))
  expect(dlg().querySelector('[data-testid=standards-result]')!.textContent).toContain('passes')
  expect(confirmButton().disabled).toBe(false)
  ok.unmount()
})

it('offers to plan from scratch, and sends nothing until the approval is ticked', async () => {
  const w = open(base({ mode: 'plan', coordination: false }))
  expect(dlg().textContent).toContain('Plan from scratch')
  expect(dlg().querySelector('[data-testid=standards-result]')).toBeNull()                   // the standards check belongs to submission
  expect(confirmButton().disabled).toBe(true)
  const box = dlg().querySelector('[data-testid=plan-fresh]') as HTMLInputElement
  box.click(); await w.vm.$nextTick()
  expect(w.emitted('update:fresh')![0]).toEqual([true])
  w.unmount()
})

it('shows a multi-line server refusal one line at a time', () => {
  const w = open(base({ error: 'This plan breaks the repository standards (site):\n- a: bad\n- b: bad' }))
  const alert = dlg().querySelector('[role=alert]') as HTMLElement
  expect(alert.textContent).toContain('- a: bad'); expect(alert.textContent).toContain('- b: bad')
  w.unmount()
})

it('offers Fix automatically when the server can fix the problems, and lists what it changed', async () => {
  const problems = ['deploy-verify: risk low is below the standards minimum high for area infrastructure-and-deployment']
  const w = open(base({ standardsCheck: { source: 'starter', problems, areas: [], fixable: 1 } }))
  const fix = dlg().querySelector('[data-action=standards-fix]') as HTMLButtonElement
  expect(fix.textContent).toContain('Fix automatically (1)')
  fix.click(); await w.vm.$nextTick()
  expect(w.emitted('fix')).toHaveLength(1)
  await w.setProps({ standardsCheck: { source: 'starter', problems: [], areas: [], fixable: 0 }, fixed: ['deploy-verify: risk low raised to high, the minimum for area infrastructure-and-deployment'] } as never)
  expect(dlg().querySelector('[data-testid=standards-fixed]')!.textContent).toContain('raised to high')
  expect(dlg().querySelector('[data-action=standards-fix]')).toBeNull()
  expect(confirmButton().disabled).toBe(false)
  w.unmount()
})


it('shows the dashboard-run repository setup as step 1, and the repository once it exists', async () => {
  const w = open(base({ repository: { name: 'twodoors-website', repo: '', folder: '', branch: '' } }))
  expect(dlg().querySelector('[data-testid=repo-step]')!.textContent).toContain('twodoors-website')
  expect(dlg().querySelector('[data-testid=repo-step]')!.textContent).toContain('before any story runs')
  await w.setProps({ repository: { name: 'twodoors-website', repo: 'gptkiosk/twodoors-website', folder: 'twodoors-website', branch: 'project-5/setup' } } as never)
  expect(dlg().querySelector('[data-testid=repo-step]')).toBeNull()
  expect(dlg().textContent).toContain('gptkiosk/twodoors-website · twodoors-website/ · project-5/setup')
  w.unmount()
})
