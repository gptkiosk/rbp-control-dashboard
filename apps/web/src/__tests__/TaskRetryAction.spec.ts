import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TaskRetryAction from '@/components/TaskRetryAction.vue'
import { card, run, stubFetch, calls } from './helpers'
import { emptyProject, type Project } from '@/lib/projects'
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })
const failed = () => card({id:50,column:'failed',agent:'claude',model:'claude-opus-5-5',project:{id:2,node_key:'durable',role:'story'},last_run:run({id:51,card_id:50,stage:'failed',error:"You've hit your session limit"})})
function project(): Project { return {id:2,state:'active',revision:2,approved_revision:2,document:emptyProject(),pipeline:null,error:null,updated_at:1,tasks:[{card_id:50,node_key:'durable',role:'story',revision:2,column:'failed',title:'Durable',run_id:51,run_stage:'failed',retry_routes:[{agent:'claude',model:'claude-opus-5-5'},{agent:'codex',model:'gpt-6.1-sol'}]}],memory:[],workspaces:{},artifacts:{}} }
function setup(p=project(),c=failed()) {
  const f=stubFetch((url,init)=>url==='/api/projects/2' || init?.method==='POST' ? {body:p} : undefined)
  const w=mount(TaskRetryAction,{props:{card:c},attachTo:document.body})
  return {w,f}
}
it('queues the same story once without granting approvals or creating a replacement task',async()=>{
  const {w,f}=setup();await flushPromises()
  expect(w.text()).toContain('quota resets')
  await w.findAll('button')[0]!.trigger('click');await flushPromises()
  const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)
  expect(writes[0]![0]).toBe('/api/projects/2/stories/50/retry')
  expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2})
  expect(w.text()).toContain('Rerun queued')
  expect(w.findAll('button')[0]!.attributes('disabled')).toBeDefined()
  expect(w.emitted('changed')).toHaveLength(1);w.unmount()
})
it('only offers and submits the project’s approved fallback route',async()=>{
  const {w,f}=setup();await flushPromises()
  expect(w.findAll('button')).toHaveLength(3)
  expect(w.findAll('button')[1]!.text()).toContain('Codex · gpt-6.1-sol')
  await w.findAll('button')[1]!.trigger('click');await flushPromises()
  expect(JSON.parse(String(calls(f,'POST','/api/')[0]![1]?.body))).toEqual({revision:2,route:{agent:'codex',model:'gpt-6.1-sol'}})
  w.unmount()
})
it('refuses a stale task state instead of duplicating an active run',async()=>{
  const p=project();const {w,f}=setup(p);await flushPromises()
  p.tasks[0]!.column='running';p.tasks[0]!.run_id=52
  await w.findAll('button')[0]!.trigger('click');await flushPromises()
  expect(calls(f,'POST','/api/')).toHaveLength(0)
  expect(w.text()).toContain('task changed');w.unmount()
})
it('does not offer reruns for human decisions or active jobs and disables paused projects',async()=>{
  const p=project();p.state='paused';const {w,f}=setup(p);await flushPromises()
  expect(w.findAll('button')[0]!.attributes('disabled')).toBeDefined()
  expect(w.text()).toContain('Resume project')
  await w.setProps({card:{...failed(),column:'running'}})
  expect(w.find('button').exists()).toBe(false)
  await w.setProps({card:{...failed(),assignee_type:'human'}})
  expect(w.find('button').exists()).toBe(false)
  expect(calls(f,'POST','/api/')).toHaveLength(0);w.unmount()
})

const freeRoute = {agent:'openclaw' as const,model:'openrouter/example/code:free',agent_target:'mm-developer'}
it('Go Free selects only configured free routes and grants only the current run/story',async()=>{
  const p=project();p.tasks[0]!.free_retry_routes=[freeRoute]
  const {w,f}=setup(p);await flushPromises()
  await w.findAll('button').find(b=>b.text()==='Go Free!')!.trigger('click')
  expect(w.text()).toContain('No paid-model or Google BYOK fallback')
  await w.findAll('button').find(b=>b.text()==='Start free retry')!.trigger('click');await flushPromises()
  const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)
  expect(writes[0]![0]).toBe('/api/projects/2/stories/50/go-free')
  expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2,run_id:51,model:freeRoute.model,agent_target:'mm-developer'})
  expect(w.text()).toContain('Free-model retry queued');w.unmount()
})
it('Go Free refuses stale routes before submission and shows missing configuration',async()=>{
  const p=project();p.tasks[0]!.free_retry_routes=[freeRoute]
  const {w,f}=setup(p);await flushPromises()
  await w.findAll('button').find(b=>b.text()==='Go Free!')!.trigger('click')
  p.tasks[0]!.free_retry_routes=[]
  await w.findAll('button').find(b=>b.text()==='Start free retry')!.trigger('click');await flushPromises()
  expect(calls(f,'POST','/api/')).toHaveLength(0)
  expect(w.text()).toContain('no longer configured');w.unmount()
  const missing=setup();await flushPromises()
  expect(missing.w.findAll('button').find(b=>b.text()==='Go Free!')!.attributes('disabled')).toBeDefined()
  expect(missing.w.text()).toContain('configured OpenRouter :free model');missing.w.unmount()
})
it('Go Free stays hidden for failures unrelated to subscription limits',async()=>{
  const {w}=setup();await flushPromises()
  await w.setProps({card:{...failed(),last_run:run({id:51,stage:'failed',error:'test suite failed'})}});await flushPromises()
  expect(w.findAll('button').some(b=>b.text()==='Go Free!')).toBe(false);w.unmount()
})

const timedOut = () => card({id:50,column:'failed',agent:'openclaw',model:'openrouter/example/code:free',mode:'read',project:{id:2,node_key:'durable',role:'story'},last_run:run({id:51,card_id:50,stage:'failed',error:'OpenClaw provider timed out'})})
function setupFree(p: Project) {
  const f=stubFetch((url,init)=>url==='/api/projects/2' || init?.method==='POST' ? {body:p} : undefined)
  const w=mount(TaskRetryAction,{props:{card:timedOut()},attachTo:document.body})
  return {w,f}
}
const withWayOut = () => { const p=project(); const t=p.tasks[0]!; t.run_stage='failed'
  t.free_retry_routes=[{agent:'openclaw',model:'openrouter/other/model:free',agent_target:'mm-developer'}]
  t.low_cost_routes=[{agent:'claude',model:'claude-haiku-5-5'},{agent:'codex',model:'gpt-6-luna'}]
  t.paid_retry_routes=[{agent:'openclaw',model:'openrouter/google/gemini-2.5-flash',agent_target:'mm-developer'}]; return p }
it('a failed free-model task always offers a way out: wait and rerun, another free model, a subscription model, or paying',async()=>{
  const {w}=setupFree(withWayOut());await flushPromises()
  const labels=w.findAll('button').map(b=>b.text())
  expect(labels).toContain('Rerun task');expect(labels).toContain('Try another free model')
  expect(labels).toContain('Use Claude · claude-haiku-5-5 (subscription)');expect(labels).toContain('Use Codex · gpt-6-luna (subscription)');expect(labels).toContain('Pay for this task…')
  expect(w.text()).toContain('Rerun task</strong> again later'.replace('</strong>','')) ;w.unmount()
})
it('a subscription retry can switch a read-only task to edit mode only with an explicit acknowledgement',async()=>{
  const {w,f}=setupFree(withWayOut());await flushPromises()
  await w.findAll('button').find(b=>b.text().startsWith('Use Codex'))!.trigger('click')
  const boxes=()=>w.findAll('.free-choice input[type=checkbox]')
  expect(boxes()).toHaveLength(1);await boxes()[0]!.setValue(true)
  expect(boxes()).toHaveLength(2)
  expect(w.findAll('button').find(b=>b.text()==='Start retry')!.attributes('disabled')).toBeDefined()
  await boxes()[1]!.setValue(true)
  await w.findAll('button').find(b=>b.text()==='Start retry')!.trigger('click');await flushPromises()
  const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)
  expect(writes[0]![0]).toBe('/api/projects/2/stories/50/low-cost-retry')
  expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2,run_id:51,agent:'codex',edit_mode:true,acknowledge:true})
  expect(w.text()).toContain('your subscription');w.unmount()
})
it('paying needs an acknowledgement, names the limits, and grants only this run',async()=>{
  const {w,f}=setupFree(withWayOut());await flushPromises()
  await w.findAll('button').find(b=>b.text()==='Pay for this task…')!.trigger('click')
  expect(w.text()).toContain('API billing for this task only');expect(w.text()).toContain('budget caps')
  const start=()=>w.findAll('button').find(b=>b.text()==='Start paid retry')!
  expect(start().attributes('disabled')).toBeDefined()
  await w.get('.free-choice input[type=checkbox]').setValue(true)
  await start().trigger('click');await flushPromises()
  const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)
  expect(writes[0]![0]).toBe('/api/projects/2/stories/50/pay-retry')
  expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2,run_id:51,model:'openrouter/google/gemini-2.5-flash',agent_target:'mm-developer',acknowledge:true})
  w.unmount()
})

it('after a timeout every retry stays off until the timeout is acknowledged, and the acknowledgement travels with the request',async()=>{
  const p=withWayOut();p.tasks[0]!.run_stage='timeout'
  const f=stubFetch((url,init)=>url==='/api/projects/2' || init?.method==='POST' ? {body:p} : undefined)
  const card=timedOut();card.last_run!.stage='timeout'
  const w=mount(TaskRetryAction,{props:{card},attachTo:document.body});await flushPromises()
  expect(w.text()).toContain('timed out')
  const rerun=()=>w.findAll('button').find(b=>b.text()==='Rerun task')!
  expect(rerun().attributes('disabled')).toBeDefined()
  expect(w.findAll('button').find(b=>b.text()==='Pay for this task…')!.attributes('disabled')).toBeDefined()
  await w.get('.timeout-ack input[type=checkbox]').setValue(true)
  expect(rerun().attributes('disabled')).toBeUndefined()
  await rerun().trigger('click');await flushPromises()
  const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)
  expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2,acknowledge_timeout:true});w.unmount()
})
it('offers Accept anyway on the board for a story whose run reported unfinished work, and records the operator’s reason',async()=>{
  const p=project();p.tasks[0]!.run_id=51;p.tasks[0]!.incomplete_reason='The agent explicitly reported unfinished work.'
  const {w,f}=setup(p);await flushPromises()
  const btn=w.find('[data-testid=accept-anyway]');expect(btn.exists()).toBe(true)
  const ask=vi.spyOn(window,'prompt').mockReturnValueOnce('short').mockReturnValueOnce('The missing files are made by the media step, not this story.')
  await btn.trigger('click');await flushPromises()
  expect(calls(f,'POST','/api/')).toHaveLength(0)                                            // a reason under ten characters sends nothing
  expect(w.text()).toContain('at least ten characters')                                     // and says why
  await btn.trigger('click');await flushPromises()
  const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)
  expect(writes[0]![0]).toBe('/api/projects/2/stories/50/accept-despite-report')
  expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2,run_id:51,reason:'The missing files are made by the media step, not this story.'})
  expect(w.text()).toContain('Accepted');expect(w.emitted('changed')).toHaveLength(1);ask.mockRestore();w.unmount()
})
it('offers Accept anyway on a reviewed story whose succeeded run still reports unfinished work',async()=>{
  const p=project();Object.assign(p.tasks[0]!,{column:'review',run_stage:'succeeded',incomplete_reason:'The agent explicitly reported unfinished work.'})
  const reviewed=card({id:50,column:'review',agent:'claude',model:'claude-haiku-5-5',project:{id:2,node_key:'durable',role:'story'},last_run:run({id:51,card_id:50,stage:'succeeded'})})
  const {w,f}=setup(p,reviewed);await flushPromises()
  const ask=vi.spyOn(window,'prompt').mockReturnValueOnce('Quota and preview capture are dashboard-owned.')
  await w.find('[data-testid=accept-anyway]').trigger('click');await flushPromises()
  const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)                       // the fresh re-check accepts a reviewed story too
  expect(writes[0]![0]).toBe('/api/projects/2/stories/50/accept-despite-report')
  expect(w.text()).toContain('Accepted');ask.mockRestore();w.unmount()
})
it('does not offer Accept anyway for a crash or timeout, which left no report to accept',async()=>{
  const {w}=setup();await flushPromises()
  expect(w.find('[data-testid=accept-anyway]').exists()).toBe(false);w.unmount()
})
