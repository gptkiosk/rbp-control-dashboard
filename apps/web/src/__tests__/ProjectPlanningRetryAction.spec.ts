import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ProjectPlanningRetryAction from '@/components/ProjectPlanningRetryAction.vue'
import type { Card } from '@/lib/api'
import { stubFetch } from './helpers'

afterEach(()=>vi.unstubAllGlobals())
it('lets the operator authorize a newly configured paid route on the same failed task',async()=>{
  const posts:unknown[]=[]
  const project={id:1,revision:2,state:'planning_failed',tasks:[{card_id:4,role:'plan',column:'failed',run_id:9,planning_retry_routes:[]}],
    route_reliability:{options:[{agent:'hermes',model:'vendor/paid',allowed:true,price_class:'paid',cost:'Provider API charges apply.'}],recommendations:[]}}
  stubFetch((url,init)=>{
    if(url==='/api/projects/1')return {body:project}
    if(url==='/api/projects/1/planning-tasks/4/retry'){posts.push(JSON.parse(String(init?.body)));return {body:{}}}
  })
  const card={id:4,column:'failed',agent:'hermes',model:'vendor/small:free',project:{id:1,role:'plan'},last_run:{id:9,stage:'failed'}} as unknown as Card
  const w=mount(ProjectPlanningRetryAction,{props:{card},global:{stubs:{RouterLink:true}}});await flushPromises()
  await w.get('[aria-label="Planning retry route"]').setValue('hermes|vendor/paid')
  const button=w.findAll('button').find(b=>b.text()==='Retry selected route')!
  expect(button.attributes('disabled')).toBeDefined()
  expect(w.text()).toContain('Provider API charges apply')
  await w.get('input[type="checkbox"]').setValue(true)
  await button.trigger('click');await flushPromises()
  expect(posts).toEqual([{revision:2,route:{agent:'hermes',model:'vendor/paid'},approve_api_planning:true}])
  expect(w.emitted('changed')).toHaveLength(1)
})
