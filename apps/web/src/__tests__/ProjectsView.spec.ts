import { afterEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import ProjectsView from '@/views/ProjectsView.vue'
import { emptyProject, newNode, arrange } from '@/lib/projects'
import { stubFetch } from './helpers'
import { vi } from 'vitest'
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML='' })
async function setup(state='draft', tasks: import('@/lib/projects').ProjectTask[] = [], proposedOutput: {path:string;markdown:string;sha256:string} | null = null, url='/projects?project=1', unarranged=false) {
 const phase=newNode('phase',0);phase.title='Architecture'
 const story=newNode('story',1,phase.key);story.title='Bounded implementation';story.model='gpt-6.1-sol';story.routes=[{agent:'claude',model:'claude-sonnet-5-5'}]
 const doc={...emptyProject('/tmp/project'),title:'Reviewed project',brief:'An approved goal',nodes:unarranged ? [phase,story].map(n=>({...n,x:0,y:0})) : arrange([phase,story])}
 let p={id:1,document:doc,revision:1,state,can_resume_plan:state==='planning_failed',approved_revision:null,pipeline:null,error:null,updated_at:1,handoff_approval:{mode:'manual' as 'manual'|'automatic',manifest_hash:'b'.repeat(64),eligible:[{card_id:5,title:'Routine document',column:'review'}],excluded:[{card_id:6,title:'Repository publication',reason:'Publication requires individual review'}]},tasks,memory:[],workspaces:{},artifacts:{}}
 const f=stubFetch((url,init) => {
  if(url==='/api/projects' && init?.method==='POST') { p={...p,document:JSON.parse(String(init.body))}; return {status:201,body:p} }
  if(url==='/api/projects') return {body:{projects:[{id:1,title:doc.title,state,revision:1,updated_at:1}]}}
  if(url==='/api/projects/1' && init?.method==='PATCH') { const body=JSON.parse(String(init.body)); p={...p,document:body.document,revision:2}; return {body:p} }
  if(url==='/api/projects/1/handoff-policy') { const body=JSON.parse(String(init?.body));p={...p,handoff_approval:{...p.handoff_approval,mode:body.mode==='automatic'?'automatic':'manual'}};return {body:p} }
  if(url==='/api/projects/1/close') { p={...p,state:'closed'};return {body:p} }
  if(url==='/api/projects/1') return {body:p}
  if(url==='/api/projects/1/stories/5/artifact') return {body:{files:[],diff:'',head:null,output:proposedOutput}}
  if(url==='/api/projects/1/stories/5/accept') { p={...p,tasks:tasks.map(t=>({...t,column:'done'}))};return {body:p} }
  if(url==='/api/projects/1/stories/5/continue-output') { p={...p,tasks:tasks.map(t=>({...t,column:'queued',output_approval:null}))};return {body:p} }
  if(url==='/api/projects/1/stories/5/retry') { p={...p,tasks:tasks.map(t=>({...t,column:'queued'}))};return {body:p} }
  if(url==='/api/projects/1/resume-plan') { p={...p,state:'planning',can_resume_plan:false};return {body:p} }
  if(url==='/api/projects/1/plan') { p={...p,state:'planning'};return {body:{...p,pipeline:{step:'coordinate',card_id:2}}} }
  if(url==='/api/agents') return {body:{agents:[{id:'codex',name:'Codex',default_model:'gpt-6.1-sol'},{id:'claude',name:'Claude Code',default_model:null}]}}
  if(url==='/api/workdirs') return {body:{workdirs:[{path:'/tmp/project',branch:'codex/project'}]}}
  return undefined
 })
 const router=createAppRouter(createMemoryHistory());await router.push(url);await router.isReady()
 const w=mount(ProjectsView,{global:{plugins:[router]},attachTo:document.body});await flushPromises()
 return {w,f,doc,setTasks:(next:typeof tasks)=>{p={...p,tasks:next}}}
}
it('resumes a saved failed proposal without requesting a new subscription plan',async()=>{
 const {w,f}=await setup('planning_failed')
 await w.findAll('button').find(b=>b.text()==='Resume saved plan')!.trigger('click');await flushPromises()
 const writes=f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')
 expect(writes.map(([url])=>url)).toEqual(['/api/projects/1/resume-plan'])
 expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:1})
 expect(w.text()).toContain('Submitted to Hermes');w.unmount()
})
it('edits the visual map without starting a model; saved revisions retain assignments and links',async()=>{
 const {w,f}=await setup()
 expect(w.findAll('.map-node')).toHaveLength(2)
 expect(w.find('.parent-edge').exists()).toBe(true)
 await w.get('[aria-label="story: Bounded implementation"]').trigger('click')
 await w.get('.node-editor input').setValue('Reviewed slice')
 expect(w.text()).toContain('Unsaved edits')
 expect(w.findAll('button').find(b=>b.text()==='Plan with Hermes')?.attributes('disabled')).toBeDefined()
 await w.findAll('button').find(b=>b.text()==='Save revision')!.trigger('click');await flushPromises()
 const writes=f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')
 expect(writes.map(([url])=>url)).toEqual(['/api/projects/1'])
 expect(JSON.parse(String(writes[0]![1]?.body)).document.nodes[1].routes[0].model).toBe('claude-sonnet-5-5')
 expect(w.text()).toContain('REVISION 2');w.unmount()
})
it('submits a new brief to Hermes after coordination approval and displays honest progress',async()=>{
 const {w,f}=await setup()
 await w.findAll('button').find(b=>b.text()==='+ New project')!.trigger('click')
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 await modal.get('input[data-autofocus]').setValue('Balanced project');await modal.get('textarea').setValue('A reviewed brief')
 const submit=modal.findAll('button').find(b=>b.text()==='Submit to Hermes')!
 expect(submit.attributes('disabled')).toBeDefined()
 await modal.get('input[type=checkbox]').setValue(true);await modal.get('form').trigger('submit');await flushPromises()
 const writes=f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')
 expect(writes.map(([url])=>url)).toEqual(['/api/projects','/api/projects/1/plan'])
 expect(JSON.parse(String(writes[0]![1]?.body)).planning_bias).toBe(50)
 expect(JSON.parse(String(writes[1]![1]?.body))).toEqual({revision:1,approve_coordination:true})
 expect(w.text()).toContain('Submitted to Hermes');expect(w.get('progress').attributes('value')).toBeUndefined()
 expect(w.text()).toContain('Link Discord in your profile');w.unmount()
})
it('submission opens a concrete review and requires coordination acknowledgment before dispatch',async()=>{
 const {w,f}=await setup()
 await w.findAll('button').find(b=>b.text()==='Review & submit')!.trigger('click');await flushPromises()
 expect(w.text()).toContain('Review project submission');expect(w.text()).toContain('claude-sonnet-5-5')
 const submit=w.findAll('button').find(b=>b.text()==='Submit approved revision')!
 expect(submit.attributes('disabled')).toBeDefined()
 expect(f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')).toHaveLength(0);w.unmount()
})
it('locks an approved map but retains the pause and context controls',async()=>{
 const {w}=await setup('active')
 expect(w.findAll('button').find(b=>b.text()==='+ Story')?.attributes('disabled')).toBeDefined()
 expect(w.get('input[type=range]').attributes('disabled')).toBeDefined()
 expect(w.text()).toContain('Pause dispatch');expect(w.text()).toContain('Export context');w.unmount()
})

it('saves a new project preference without starting models',async()=>{
 const {w,f}=await setup()
 await w.findAll('button').find(b=>b.text()==='+ New project')!.trigger('click')
 const dialog=document.querySelector('[role=dialog]')!
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(dialog)
 await modal.get('input[data-autofocus]').setValue('Economical project')
 await modal.get('textarea').setValue('A bounded project brief')
 const slider=modal.get('input[type=range]');expect((slider.element as HTMLInputElement).value).toBe('50')
 await slider.setValue('0');expect(slider.attributes('aria-valuetext')).toBe('Economy · OpenClaw first')
 await modal.findAll('button').find(b=>b.text()==='Save draft')!.trigger('click');await flushPromises()
 const writes=f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')
 expect(writes).toHaveLength(1);expect(writes[0]![0]).toBe('/api/projects')
 expect(JSON.parse(String(writes[0]![1]?.body)).planning_bias).toBe(0);w.unmount()
})
it('changing a mapped preference leaves existing routes intact and sets new story defaults',async()=>{
 const {w,f}=await setup()
 await w.get('input[type=range]').setValue('0')
 expect(w.text()).toContain('Save and replan')
 await w.findAll('button').find(b=>b.text()==='+ Story')!.trigger('click')
 await w.findAll('button').find(b=>b.text()==='Save revision')!.trigger('click');await flushPromises()
 const write=f.mock.calls.find(([,init])=>init?.method==='PATCH')!
 const doc=JSON.parse(String(write[1]?.body)).document
 expect(doc.planning_bias).toBe(0)
 expect(doc.nodes[1].assignee).toBe('codex');expect(doc.nodes[1].routes[0].model).toBe('claude-sonnet-5-5')
 expect(doc.nodes[2].assignee).toBe('openclaw');expect(doc.nodes[2].model).toBe('')
 await w.findAll('button').find(b=>b.text()==='Review & submit')!.trigger('click')
 expect(document.body.textContent).toContain('Story preference: Economy · OpenClaw first');w.unmount()
})

it('retries a failed story only through an explicitly selected reviewed route',async()=>{
 const choice={agent:'claude' as const,model:'claude-haiku-5-5'}
 const {w,f}=await setup('active',[{card_id:5,node_key:'a',role:'story',revision:1,column:'failed',title:'Inventory',agent:'openclaw',model:'openrouter/thinkingmachines/inkling:free',run_id:6,run_stage:'timeout',retry_routes:[choice]}])
 await w.findAll('button').find(b=>b.text()==='Stories & runs')!.trigger('click');await flushPromises()
 expect(w.text()).toContain('Run #6 · Timed out')
 expect(f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')).toHaveLength(0)
 await w.findAll('button').find(b=>b.text()==='Retry with Claude · claude-haiku-5-5')!.trigger('click');await flushPromises()
 const writes=f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')
 expect(writes.map(([url])=>url)).toEqual(['/api/projects/1/stories/5/retry'])
 expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:1,route:choice})
 w.unmount()
})

it('requires explicit output approval and never offers handoff acceptance for an unfinished plan',async()=>{
 const task={card_id:5,node_key:'inventory',role:'story',revision:1,column:'review',title:'Inventory',agent:'claude',model:'claude-haiku-5-5',run_id:7,run_stage:'awaiting_approval',output_approval:{run_id:7,path:'/private/project-outputs/inventory.md',plan:'Plan mode blocks writing the inventory.'}}
 const {w,f}=await setup('active',[task])
 await w.findAll('button').find(b=>b.text()==='Stories & runs')!.trigger('click');await flushPromises()
 expect(w.text()).toContain('Awaiting output approval')
 expect(w.findAll('button').some(b=>b.text()==='Review handoff')).toBe(false)
 await w.findAll('button').find(b=>b.text()==='Approve output & continue')!.trigger('click');await flushPromises()
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 expect(modal.text()).toContain('/private/project-outputs/inventory.md')
 expect(modal.text()).toContain('agent remains read-only')
 expect(modal.findAll('button').find(b=>b.text()==='Approve & continue')!.attributes('disabled')).toBeDefined()
 expect(f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')).toHaveLength(0)
 await modal.get('input[type=checkbox]').setValue(true)
 await modal.get('form').trigger('submit');await flushPromises()
 const writes=f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')
 expect(writes.map(([url])=>url)).toEqual(['/api/projects/1/stories/5/continue-output'])
 expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:1,run_id:7,approve_output:true})
 w.unmount()
})

it('previews the saved output and requires document review before sending its hash for acceptance',async()=>{
 const task={card_id:5,node_key:'inventory',role:'story',revision:1,column:'review',title:'Inventory',agent:'claude',model:'claude-haiku-5-5',run_id:8,run_stage:'succeeded'}
 const output={path:'/private/inventory.md',markdown:'# Checked document\n<script>untrusted</script>',sha256:'a'.repeat(64)}
 const {w,f}=await setup('active',[task],output)
 await w.findAll('button').find(b=>b.text()==='Stories & runs')!.trigger('click')
 await w.findAll('button').find(b=>b.text()==='Review handoff')!.trigger('click');await flushPromises()
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 expect(modal.text()).toContain(output.markdown)
 expect(modal.find('script').exists()).toBe(false)
 await modal.get('textarea').setValue('Checked all sections and references.')
 expect(modal.findAll('button').find(b=>b.text()==='Accept handoff')!.attributes('disabled')).toBeDefined()
 await modal.get('input[type=checkbox]').setValue(true)
 await modal.get('form').trigger('submit');await flushPromises()
 const writes=f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')
 expect(writes).toHaveLength(1)
 expect(JSON.parse(String(writes[0]![1]?.body)).output_sha256).toBe(output.sha256)
 expect(w.text()).toContain('STORY · Done');w.unmount()
})

it('opens the exact output review from the task board without submitting approval',async()=>{
 const task={card_id:5,node_key:'inventory',role:'story',revision:1,column:'review',title:'Inventory',agent:'claude',model:'claude-haiku-5-5',run_id:7,run_stage:'awaiting_approval',output_approval:{run_id:7,path:'/private/project-outputs/inventory.md',plan:'Plan mode blocks writing.'}}
 const {w,f}=await setup('active',[task],null,'/projects?project=1&view=work&story=5&action=review')
 const dialog=document.querySelector('[role=dialog]')!
 expect(dialog.textContent).toContain('Approve output & continue')
 expect((dialog.querySelector('input[type=checkbox]') as HTMLInputElement).checked).toBe(false)
 expect(f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')).toHaveLength(0)
 w.unmount()
})


it('never treats automatic display layout or opening a project as unsaved edits',async()=>{
 const confirm=vi.fn();vi.stubGlobal('confirm',confirm)
 const {w,f}=await setup('active',[],null,'/projects?project=1',true)
 expect(w.text()).not.toContain('Unsaved edits')
 expect(w.text()).toContain('View only')
 await w.get('.project-link').trigger('click');await flushPromises()
 expect(confirm).not.toHaveBeenCalled()
 expect(f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')).toHaveLength(0)
 w.unmount()
})

it('does not prompt before loading a project from the empty welcome screen',async()=>{
 const confirm=vi.fn();vi.stubGlobal('confirm',confirm)
 const {w}=await setup('active',[],null,'/projects')
 await w.get('.project-link').trigger('click');await flushPromises()
 expect(confirm).not.toHaveBeenCalled();expect(w.text()).toContain('View only');w.unmount()
})

it('updates live story, phase and project colors from polling without writing the plan',async()=>{
 vi.useFakeTimers()
 const {w,f,doc,setTasks}=await setup('active')
 setTasks([{card_id:5,node_key:doc.nodes[1]!.key,role:'story',revision:1,column:'running',title:'Routine document',run_id:7,run_stage:'running'}])
 await vi.advanceTimersByTimeAsync(3000);await flushPromises()
 expect(w.get('.map-node.story').classes()).toContain('status-running')
 expect(w.get('.map-node.phase').classes()).toContain('status-running')
 expect(w.get('.project-bubble').classes()).toContain('status-running')
 setTasks([{card_id:5,node_key:doc.nodes[1]!.key,role:'story',revision:1,column:'done',title:'Routine document',run_id:7,run_stage:'succeeded'}])
 await vi.advanceTimersByTimeAsync(3000);await flushPromises()
 expect(w.get('.map-node.phase').classes()).toContain('status-done')
 expect(w.text()).toContain('1 / 1 stories done')
 expect(f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')).toHaveLength(0);w.unmount()
})

it('shows the bulk scope and requires acknowledgment before enabling automatic handoffs',async()=>{
 const {w,f}=await setup('active')
 await w.findAll('button').find(b=>b.text()==='Approve all except human-required tasks…')!.trigger('click');await flushPromises()
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 expect(modal.text()).toContain('Routine document');expect(modal.text()).toContain('Repository publication')
 expect(modal.text()).toContain('Requires human input or approval')
 expect(modal.text()).toContain('Human-required tasks remain excluded.')
 expect(modal.findAll('button').find(b=>b.text()==='Enable automatic handoffs')!.attributes('disabled')).toBeDefined()
 expect(f.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')).toHaveLength(0)
 await modal.findAll('input[type=checkbox]')[1]!.setValue(true)
 await modal.get('form').trigger('submit');await flushPromises()
 const write=f.mock.calls.find(([url])=>url==='/api/projects/1/handoff-policy')!
 expect(JSON.parse(String(write[1]?.body))).toEqual({revision:1,manifest_hash:'b'.repeat(64),mode:'automatic',approve:true})
 expect(w.text()).toContain('Automatic agent handoffs enabled');w.unmount()
})

it('reruns an unaccepted successful story without accepting its old handoff',async()=>{
 const {w,f}=await setup('active',[{card_id:5,node_key:'a',role:'story',revision:1,column:'review',title:'Inventory',agent:'codex',model:'gpt-6.1-sol',run_id:6,run_stage:'succeeded'}])
 await w.findAll('button').find(b=>b.text()==='Stories & runs')!.trigger('click');await flushPromises()
 await w.findAll('button').find(b=>b.text()==='Rerun same story')!.trigger('click');await flushPromises()
 const writes=f.mock.calls.filter(([,init])=>init?.method==='POST')
 expect(writes.map(([url])=>url)).toEqual(['/api/projects/1/stories/5/retry'])
 expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:1})
 w.unmount()
})

it('shows upstream failure reasons on blocked stories without offering a handoff',async()=>{
 const reason='#4 Root: failed; prerequisite handoff has not been accepted.'
 const {w}=await setup('active',[{card_id:5,node_key:'a',role:'story',revision:1,column:'queued',title:'Dependent',run_id:null,run_stage:null,blocked_by:[4],blocked_reasons:[{card_id:4,reason}]}])
 await w.findAll('button').find(b=>b.text()==='Stories & runs')!.trigger('click');await flushPromises()
 expect(w.get('.work-row [role=status]').text()).toBe(reason)
 expect(w.findAll('button').some(b=>b.text()==='Review handoff')).toBe(false)
 w.unmount()
})

it('closes an unfinished project only with a reason and shows it as Closed, never Complete',async()=>{
 const prompt=vi.spyOn(window,'prompt').mockReturnValueOnce('').mockReturnValueOnce('Superseded by the RCD project')
 const {w,f}=await setup('active')
 const closeButton=()=>w.findAll('button').find(b=>b.text()==='Close project…')!
 await closeButton().trigger('click');await flushPromises()
 expect(f.mock.calls.some(([url])=>url==='/api/projects/1/close')).toBe(false)
 await closeButton().trigger('click');await flushPromises()
 const write=f.mock.calls.find(([url])=>url==='/api/projects/1/close')!
 expect(JSON.parse(String(write[1]?.body))).toEqual({revision:1,reason:'Superseded by the RCD project'})
 expect(prompt).toHaveBeenCalledTimes(2);expect(w.text()).toContain('Closed');expect(w.text()).not.toContain('Complete')
 expect(w.findAll('button').some(b=>b.text()==='Close project…')).toBe(false);w.unmount()
})

it('offers no close action for a completed or planning project',async()=>{
 for(const state of ['complete','planning','dispatching']){
  const {w}=await setup(state);expect(w.findAll('button').some(b=>b.text()==='Close project…')).toBe(false);w.unmount()
 }
})
