import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ProjectSchedule from '@/components/ProjectSchedule.vue'

const schedule = { stories: 4, total_minutes: 225, critical_minutes: 135, speedup: 1.67, width: 3, critical_path: ['b', 'd'], problems: [] as string[], max_concurrent_runs: 2 }

it('shows nothing for a serial project', () => {
  expect(mount(ProjectSchedule, { props: { schedule: null } }).find('[data-testid=schedule]').exists()).toBe(false)
})

it('states the best case plainly, names the longest chain by title, and says when the run limit holds it back', () => {
  const w = mount(ProjectSchedule, { props: { schedule, titles: { b: 'Build art', d: 'Join all' } } })
  expect(w.get('[data-testid=schedule-summary]').text()).toContain('1.67× faster')
  expect(w.get('[data-testid=schedule-summary]').text()).toContain('2.3 h')
  expect(w.get('[data-testid=schedule-path]').text()).toContain('Build art → Join all')
  expect(w.get('[data-testid=schedule-limit]').text()).toContain('MAC_CONTROL_MAX_CONCURRENT_RUNS')
  expect(mount(ProjectSchedule, { props: { schedule: { ...schedule, max_concurrent_runs: 4 } } }).find('[data-testid=schedule-limit]').exists()).toBe(false)
})

it('lists what must be fixed before submission and points to the serial alternative', () => {
  const w = mount(ProjectSchedule, { props: { schedule: { ...schedule, problems: ['a and b can run at the same time but both change site/ and site/b'] } } })
  expect(w.get('[data-testid=schedule-problems]').text()).toContain('both change site/')
  expect(w.text()).toContain('Turn parallel build off')
})

it('shows how much the runs really overlapped once some have finished', () => {
  const w = mount(ProjectSchedule, { props: { schedule, timing: { runs: 5, busy_minutes: 210, elapsed_minutes: 130, overlap: 1.62 } } })
  expect(w.get('[data-testid=schedule-timing]').text()).toContain('210 min of agent work in 130 min elapsed')
  expect(w.get('[data-testid=schedule-timing]').text()).toContain('1.62×')
})
