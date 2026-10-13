import { afterEach, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import TaskApprovalAction from '@/components/TaskApprovalAction.vue'
import { card, run, stubFetch, calls } from './helpers'
import { emptyProject, type Project } from '@/lib/projects'
afterEach(()=>{ vi.unstubAllGlobals();document.body.innerHTML='' })
const completed=()=>card({id:5,column:'review',project:{id:1,node_key:'inventory',role:'story'},last_run:run({id:8,card_id:5,result_text:'Verified inventory; carried references recorded.'})})
function project(over: Partial<Project> = {}): Project { return {id:1,state:'active',revision:2,approved_revision:2,document:emptyProject(),pipeline:null,error:null,updated_at:1,tasks:[{card_id:5,node_key:'inventory',role:'story',revision:2,column:'review',title:'Inventory',run_id:8,run_stage:'succeeded'}],memory:[],workspaces:{},artifacts:{},...over} }
function setup(p=project(),files:string[]=[]) {
 const f=stubFetch((url,init)=>{
  if(url==='/api/projects/1')return {body:p}
  if(url.endsWith('/artifact'))return {body:{files,output:{sha256:'current-hash'}}}
  if(init?.method==='POST')return {body:p}
  return undefined
 })
 const w=mount(TaskApprovalAction,{props:{card:completed()},global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}},attachTo:document.body})
 return {w,f}
}
it('approves the displayed successful handoff in one click using the current output hash',async()=>{
 const {w,f}=setup();await w.get('button').trigger('click');await flushPromises()
 const writes=calls(f,'POST','/api/projects/1/stories/5/accept')
 expect(writes).toHaveLength(1)
 expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2,run_id:8,summary:'Verified inventory; carried references recorded.',snapshot:false,files:[],output_sha256:'current-hash'})
 expect(w.emitted('changed')).toHaveLength(1);w.unmount()
})
it('does not approve a newer run that the operator has not seen',async()=>{
 const p=project();p.tasks[0]!.run_id=9
 const {w,f}=setup(p);await w.get('button').trigger('click');await flushPromises()
 expect(calls(f,'POST','/api/')).toHaveLength(0);expect(w.text()).toContain('latest run changed');w.unmount()
})
it('retains explicit file review instead of snapshotting workspace changes',async()=>{
 const {w,f}=setup(project(),['code.py']);await w.get('button').trigger('click');await flushPromises()
 expect(calls(f,'POST','/api/')).toHaveLength(0);expect(w.text()).toContain('Review and select those files');w.unmount()
})
it('requires a written operator decision and never manufactures one',async()=>{
 const p=project();p.tasks[0]!.run_id=null;p.tasks[0]!.run_stage=null;p.tasks[0]!.column='backlog'
 const {w,f}=setup(p);await w.setProps({card:card({id:5,assignee_type:'human',agent:null,column:'backlog',project:{id:1,node_key:'decision',role:'story'},last_run:null})})
 await w.get('button').trigger('click');await flushPromises()
 const dialog=new DOMWrapper(document.querySelector('[role=dialog]')!)
 expect(dialog.get('button:last-child').attributes('disabled')).toBeDefined()
 expect(calls(f,'POST','/api/')).toHaveLength(0)
 await dialog.get('textarea').setValue('Operator chose a private snapshot; publication remains a separate gate.')
 await dialog.get('form').trigger('submit');await flushPromises()
 expect(JSON.parse(String(calls(f,'POST','/api/')[0]![1]?.body)).summary).toBe('Operator chose a private snapshot; publication remains a separate gate.')
 w.unmount()
})
it('never offers approval for blocked or failed stories',async()=>{
 const {w}=setup();await w.setProps({card:{...completed(),blocked_by:[6]}});expect(w.find('button').exists()).toBe(false)
 await w.setProps({card:{...completed(),last_run:run({stage:'failed'})}});expect(w.find('button').exists()).toBe(false);w.unmount()
})
it('approves a scoped output continuation without accepting its handoff',async()=>{
 const p=project();p.tasks[0]!.run_stage='awaiting_approval';p.tasks[0]!.output_approval={run_id:8,path:'/private/inventory.md',plan:'Unfinished plan'}
 const {w,f}=setup(p);await w.setProps({card:{...completed(),last_run:run({id:8,stage:'awaiting_approval'})}})
 await w.get('button').trigger('click');await flushPromises()
 const writes=calls(f,'POST','/api/');expect(writes.map(([url])=>url)).toEqual(['/api/projects/1/stories/5/continue-output'])
 expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2,run_id:8,approve_output:true});w.unmount()
})
it('approves ordinary run permission from the board without opening the task',async()=>{
 const {w,f}=setup();await w.setProps({card:card({id:2,column:'review',needs_approval:true,approval_reasons:['Edit mode'],project:null})})
 expect(w.text()).toContain('Edit mode');await w.get('button').trigger('click');await flushPromises()
 expect(calls(f,'POST','/api/').map(([url])=>url)).toEqual(['/api/cards/2/approve']);w.unmount()
})

it('shows a checkpoint question and sends the answer for the displayed approval',async()=>{
 const {w,f}=setup();await w.setProps({card:card({id:5,column:'review',project:null,last_run:run({id:8,stage:'awaiting_approval',approval:{approval_id:'gate-1',kind:'human_decision',question:'Choose a destination',options:[{id:'private',label:'Private folder'}],proposed_output:{preview:'Prepared operation',sha256:'a'.repeat(64)}}})})})
 expect(w.text()).toContain('Answer run decision');await w.get('button').trigger('click');await flushPromises()
 const dialog=new DOMWrapper(document.querySelector('[role=dialog]')!)
 expect(dialog.text()).toContain('Choose a destination');expect(dialog.text()).toContain('Prepared operation')
 await dialog.get('select').setValue('private');await dialog.get('textarea').setValue('Keep the prepared contents')
 await dialog.get('form').trigger('submit');await flushPromises()
 const writes=calls(f,'POST','/api/runs/8/decision');expect(writes).toHaveLength(1)
 expect(JSON.parse(String(writes[0]![1]?.body))).toMatchObject({approval_id:'gate-1',verdict:'answer',option_id:'private',answer_text:'Keep the prepared contents',approved_output_sha256:'a'.repeat(64)})
 expect(w.emitted('changed')).toHaveLength(1);w.unmount()
})
it('offers rejection and disables a decision already being applied',async()=>{
 const {w,f}=setup();const c=card({id:5,column:'review',last_run:run({id:8,stage:'awaiting_approval',approval:{approval_id:'gate-1',kind:'human_decision',question:'Proceed?'}})})
 await w.setProps({card:c});await w.get('button').trigger('click');await flushPromises()
 const dialog=new DOMWrapper(document.querySelector('[role=dialog]')!)
 const reject=dialog.findAll('button').find(b=>b.text()==='Reject decision')!
 await reject.trigger('click');await flushPromises()
 expect(JSON.parse(String(calls(f,'POST','/api/runs/8/decision')[0]![1]?.body)).verdict).toBe('reject')
 await w.setProps({card:{...c,last_run:{...c.last_run!,decision_pending:true}}})
 expect(w.get('button').attributes('disabled')).toBeDefined();w.unmount()
})
