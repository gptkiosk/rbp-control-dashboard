import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ProjectPlanningProgress from '@/components/ProjectPlanningProgress.vue'
import { emptyProject, type Project, type ProjectTask } from '@/lib/projects'

const task = (card_id: number, role: string, agent: string, model: string): ProjectTask =>
  ({ card_id, node_key: '', role, revision: 4, column: 'done', title: role, run_id: card_id, run_stage: 'succeeded', agent, model })
const project = (planner: string, state: string, tasks: ProjectTask[], step: string | null = null) =>
  ({ id: 2, revision: 5, state, document: { ...emptyProject('/w'), planner_agent: planner }, tasks, memory: [], pipeline: step ? { step, card_id: tasks.at(-1)?.card_id ?? 0 } : null,
     error: null, updated_at: 1, workspaces: {}, artifacts: {} }) as unknown as Project
const stubs = { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } }

it('says the picked planner checks the plan when the planner is Automatic, and names the route each step ran on', () => {
  const w = mount(ProjectPlanningProgress, { props: { coordinator: 'hermes', project: project('auto', 'review', [
    task(11, 'coordinate', 'hermes', 'google/gemini-2.5-flash'), task(12, 'plan', 'codex', 'gpt-6.1-sol'),
    task(13, 'return plan', 'codex', 'gpt-6.1-sol'), task(14, 'return plan', 'codex', 'gpt-6.1-sol')]) }, ...stubs })
  const steps = w.findAll('.stages li').map(li => li.text())
  expect(steps[0]).toContain('Hermes · google/gemini-2.5-flash')
  expect(steps[2]).toContain('The planner the Coordinator picked reviews the map')
  expect(w.get('[data-ran-on="return"]').text()).toBe('Codex · gpt-6.1-sol')
})

it('says the Coordinator checks the plan when the project names its own planner, before the check has run', () => {
  const w = mount(ProjectPlanningProgress, { props: { coordinator: 'hermes', project: project('codex', 'planning', [task(11, 'coordinate', 'hermes', 'google/gemini-2.5-flash')], 'coordinate') }, ...stubs })
  expect(w.findAll('.stages li')[2]!.text()).toContain('The Coordinator reviews the map before returning it.')
  expect(w.find('[data-ran-on="return"]').exists()).toBe(false)
})
