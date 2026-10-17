import { afterEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import ProjectConsultant from '@/components/ProjectConsultant.vue'
import ProjectsView from '@/views/ProjectsView.vue'
import { emptyProject, newNode, arrange } from '@/lib/projects'
import { stubFetch } from './helpers'
import { vi } from 'vitest'
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML='' })
async function setup(state='draft', tasks: import('@/lib/projects').ProjectTask[] = [], proposedOutput: {path:string;markdown:string;sha256:string} | null = null, url='/projects?project=1', unarranged=false) {
 const phase=newNode('phase',0);phase.title='Architecture'
 const story=newNode('story',1,phase.key);story.title='Bounded implementation';story.model='gpt-6.1-sol';story.routes=[{agent:'claude',model:'claude-sonnet-5-5'}]
 const doc={...emptyProject('/tmp/project'),title:'Reviewed project',brief:'An approved goal',nodes:unarranged ? [phase,story].map(n=>({...n,x:0,y:0})) : arrange([phase,story])}
 let p={model_lock:false,id:1,document:doc,revision:1,state,can_resume_plan:state==='planning_failed',approved_revision:null,pipeline:null,error:null,updated_at:1,handoff_approval:{mode:'manual' as 'manual'|'automatic',manifest_hash:'b'.repeat(64),eligible:[{card_id:5,title:'Routine document',column:'review'}],excluded:[{card_id:6,title:'Repository publication',reason:'Publication requires individual review'}]},tasks,memory:[],workspaces:{},artifacts:{}}
 const f=stubFetch((url,init) => {
  if(url==='/api/roles') return {body:{delegator:'hermes',revision:'a'.repeat(64)}}
  if(url==='/api/projects' && init?.method==='POST') { p={...p,document:JSON.parse(String(init.body))}; return {status:201,body:p} }
  if(url==='/api/projects') return {body:{projects:[{id:1,title:doc.title,state,revision:1,updated_at:1}]}}
  if(url==='/api/projects/1' && init?.method==='PATCH') { const body=JSON.parse(String(init.body)); p={...p,document:body.document,revision:2}; return {body:p} }
  if(url==='/api/projects/1/model-lock') { const body=JSON.parse(String(init?.body));p={...p,model_lock:body.enabled};return {body:p} }
  if(url==='/api/projects/1/handoff-policy') { const body=JSON.parse(String(init?.body));p={...p,handoff_approval:{...p.handoff_approval,mode:body.mode==='automatic'?'automatic':'manual'}};return {body:p} }
  if(url==='/api/projects/1/close') { p={...p,state:'closed'};return {body:p} }
  if(url==='/api/projects/1/retier') { p={...p,document:{...p.document,planning_bias:50},tasks:p.tasks.map(t=>({...t,model:t.agent==='claude'?'claude-haiku-5-5':t.agent==='codex'?'gpt-6-luna':t.model}))};return {body:p} }
  if(url==='/api/projects/1/stories/5/repair-execution') { p={...p,tasks:p.tasks.map(t=>t.card_id===5?{...t,column:'queued',agent:'codex',model:'gpt-6-luna',mode:'edit',incomplete_reason:null}:t)};return {body:p} }
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
 const writes=f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')
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
 const writes=f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')
 expect(writes.map(([url])=>url)).toEqual(['/api/projects/1'])
 expect(JSON.parse(String(writes[0]![1]?.body)).document.nodes[1].routes[0].model).toBe('claude-sonnet-5-5')
 expect(w.text()).toContain('REVISION 2');w.unmount()
})
it('deletes a closed project only after confirmation and says the folder is kept',async()=>{
 const {w,f}=await setup('closed')
 const inner=globalThis.fetch
 const posted:unknown[]=[]
 vi.stubGlobal('fetch',(url:string,init?:RequestInit)=>url==='/api/projects/1/delete'&&init?.method==='POST'
  ? (posted.push(JSON.parse(String(init.body))),Promise.resolve(new Response(JSON.stringify({deleted:1,working_dir_kept:'/tmp/project'}),{status:200,headers:{'content-type':'application/json'}})))
  : inner(url as never,init))
 await flushPromises()
 const button=w.findAll('button').find(b=>b.text()==='Delete project…')!
 expect(button).toBeTruthy()
 const confirm=vi.spyOn(window,'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
 await button.trigger('click');await flushPromises()
 expect(confirm.mock.calls[0]![0]).toContain('The working folder and its files are kept')
 expect(posted).toEqual([])                                                            // cancelled: nothing sent
 await button.trigger('click');await flushPromises()
 expect(posted).toEqual([{revision:1,confirm:true}])
 confirm.mockRestore();w.unmount()
})
it('does not offer Delete on a live project',async()=>{
 const {w}=await setup('active')
 expect(w.findAll('button').some(b=>b.text()==='Delete project…')).toBe(false)
 w.unmount()
})
it('asks for a missing key before creating the project, then creates it after the key is saved or skipped',async()=>{
 const {w,f}=await setup()
 const inner=globalThis.fetch
 let keySaved=false
 vi.stubGlobal('fetch',(url:string,init?:RequestInit)=>{
  const json=(b:unknown)=>Promise.resolve(new Response(JSON.stringify(b),{status:200,headers:{'content-type':'application/json'}}))
  if(url==='/api/keys/check') return json(keySaved?{ready:true,missing:[]}:{ready:false,missing:[{id:'video',label:'fal.ai key',provider:'fal',providers:['fal'],blocking:false,why:'This project mentions generated video.',obtain:'https://fal.ai/dashboard/keys',scope:'API preset.'}]})
  if(url==='/api/profile/credentials/fal'&&init?.method==='PUT'){keySaved=true;return json({credentials:[{provider:'fal',hint:'abcd'}]})}
  return inner(url as never,init)
 })
 await w.findAll('button').find(b=>b.text()==='+ New project')!.trigger('click')
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 await modal.get('input[data-autofocus]').setValue('Media site');await modal.get('textarea').setValue('A site with an AI-generated video background')
 await modal.get('input[type=checkbox]:not([data-testid])').setValue(true);await modal.get('form').trigger('submit');await flushPromises()
 const gate=document.querySelector('[data-gate=video]')!
 expect(gate.textContent).toContain('This project mentions generated video.')
 expect(f.mock.calls.some(([u,i])=>u==='/api/projects'&&i?.method==='POST')).toBe(false)      // nothing is created before the key is dealt with
 const field=new DOMWrapper(gate.querySelector('input[type=password]')!);await field.setValue('fal-test-'+'k'.repeat(30))
 await new DOMWrapper(gate.querySelector('button')!).trigger('click');await flushPromises()
 expect(keySaved).toBe(true)
 expect(document.querySelector('[data-gate=video]')).toBeNull()                                 // the check ran again and found nothing missing
 w.unmount()
})
it('submits a new brief to Hermes after coordination approval and displays honest progress',async()=>{
 const {w,f}=await setup()
 await w.findAll('button').find(b=>b.text()==='+ New project')!.trigger('click')
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 await modal.get('input[data-autofocus]').setValue('Balanced project');await modal.get('textarea').setValue('A reviewed brief')
 const submit=modal.findAll('button').find(b=>b.text()==='Submit to Hermes')!
 expect(submit.attributes('disabled')).toBeDefined()
 expect((modal.get('[data-testid=parallel-new]').element as HTMLInputElement).checked).toBe(false)         // parallel build is off unless chosen
 await modal.get('input[type=checkbox]:not([data-testid])').setValue(true);await modal.get('form').trigger('submit');await flushPromises()
 const writes=f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')
 expect(writes.map(([url])=>url)).toEqual(['/api/projects','/api/projects/1/plan'])
 expect(JSON.parse(String(writes[0]![1]?.body)).planning_bias).toBe(50)
 expect(JSON.parse(String(writes[0]![1]?.body)).dispatch_mode).toBe('sequential')
 expect(JSON.parse(String(writes[1]![1]?.body))).toEqual({revision:1,approve_coordination:true,delegator_revision:'a'.repeat(64)})
 expect(w.text()).toContain('Submitted to Hermes');expect(w.get('progress').attributes('value')).toBeUndefined()
 expect(w.text()).toContain('Link Discord in your profile');w.unmount()
})
it('submission opens a concrete review and requires coordination acknowledgment before dispatch',async()=>{
 const {w,f}=await setup()
 await w.findAll('button').find(b=>b.text()==='Review & submit')!.trigger('click');await flushPromises()
 expect(w.text()).toContain('Review project submission');expect(w.text()).toContain('claude-sonnet-5-5')
 const submit=w.findAll('button').find(b=>b.text()==='Submit approved revision')!
 expect(submit.attributes('disabled')).toBeDefined()
 expect(f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')).toHaveLength(0);w.unmount()
})
it('locks an approved map but retains the pause and context controls',async()=>{
 const {w}=await setup('active')
 expect(w.findAll('button').find(b=>b.text()==='+ Story')?.attributes('disabled')).toBeDefined()
 expect(w.get('input[type=range]').attributes('disabled')).toBeDefined()
 expect(w.text()).toContain('Pause dispatch');expect(w.text()).toContain('Export context');w.unmount()
})

it('retieres only a paused project after showing the exact lower-cost routes',async()=>{
 const tasks=[{card_id:5,node_key:'a',role:'story',revision:1,column:'queued',title:'Queued implementation',agent:'codex',model:'gpt-6.1-sol',run_id:null,run_stage:null}]
 const {w,f}=await setup('paused',tasks)
 await w.findAll('button').find(b=>b.text()==='Use lower-cost models…')!.trigger('click');await flushPromises()
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 expect(modal.text()).toContain('Claude Haiku 5.5');expect(modal.text()).toContain('Codex GPT-6 Luna')
 expect(modal.findAll('button').find(b=>b.text()==='Apply model change')!.attributes('disabled')).toBeDefined()
 await modal.get('input[type=checkbox]').setValue(true);await modal.get('form').trigger('submit');await flushPromises()
 const write=f.mock.calls.find(([url])=>url==='/api/projects/1/retier')!
 expect(JSON.parse(String(write[1]?.body))).toEqual({revision:1,claude_model:'claude-haiku-5-5',codex_model:'gpt-6-luna',acknowledge:true})
 expect(w.text()).toContain('Resume dispatch');w.unmount()
})

it('repairs an explicitly unfinished read-only assignment only after review',async()=>{
 const tasks=[{card_id:5,node_key:'a',role:'story',revision:1,column:'review',title:'Fault matrix',agent:'claude',model:'claude-sonnet-5-5',mode:'read' as const,incomplete_reason:'The agent explicitly reported unfinished work.',run_id:156,run_stage:'succeeded'}]
 const {w,f}=await setup('paused',tasks)
 await w.findAll('button').find(b=>b.text()==='Repair first assignment…')!.trigger('click');await flushPromises()
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 expect(modal.text()).toContain('Fault matrix');expect(modal.text()).toContain('Edit workspace')
 await modal.get('input[type=checkbox]').setValue(true);await modal.get('form').trigger('submit');await flushPromises()
 const write=f.mock.calls.find(([url])=>url==='/api/projects/1/stories/5/repair-execution')!
 expect(JSON.parse(String(write[1]?.body))).toEqual({revision:1,acknowledge:true})
 expect(w.text()).not.toContain('read-only story reports unfinished execution');w.unmount()
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
 const writes=f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')
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
 await w.findAll('button').find(b=>b.text()==='Review & submit')!.trigger('click');await flushPromises()
 expect(document.body.textContent).toContain('Story preference');expect(document.body.textContent).toContain('Economy · OpenClaw first');w.unmount()
})

it('retries a failed story only through an explicitly selected reviewed route',async()=>{
 const choice={agent:'claude' as const,model:'claude-haiku-5-5'}
 const {w,f}=await setup('active',[{card_id:5,node_key:'a',role:'story',revision:1,column:'failed',title:'Inventory',agent:'openclaw',model:'openrouter/thinkingmachines/inkling:free',run_id:6,run_stage:'timeout',retry_routes:[choice]}])
 await w.findAll('button').find(b=>b.text()==='Stories & runs')!.trigger('click');await flushPromises()
 expect(w.text()).toContain('Run #6 · Timed out')
 expect(f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')).toHaveLength(0)
 await w.findAll('button').find(b=>b.text()==='Retry with Claude · claude-haiku-5-5')!.trigger('click');await flushPromises()
 const writes=f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')
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
 expect(f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')).toHaveLength(0)
 await modal.get('input[type=checkbox]').setValue(true)
 await modal.get('form').trigger('submit');await flushPromises()
 const writes=f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')
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
 const writes=f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')
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
 expect(f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')).toHaveLength(0)
 w.unmount()
})


it('never treats automatic display layout or opening a project as unsaved edits',async()=>{
 const confirm=vi.fn();vi.stubGlobal('confirm',confirm)
 const {w,f}=await setup('active',[],null,'/projects?project=1',true)
 expect(w.text()).not.toContain('Unsaved edits')
 expect(w.text()).toContain('View only')
 await w.get('.project-link').trigger('click');await flushPromises()
 expect(confirm).not.toHaveBeenCalled()
 expect(f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')).toHaveLength(0)
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
 expect(f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')).toHaveLength(0);w.unmount()
})

it('shows the bulk scope and requires acknowledgment before enabling automatic handoffs',async()=>{
 const {w,f}=await setup('active')
 await w.findAll('button').find(b=>b.text()==='Approve all except human-required tasks…')!.trigger('click');await flushPromises()
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 expect(modal.text()).toContain('Routine document');expect(modal.text()).toContain('Repository publication')
 expect(modal.text()).toContain('Requires human input or approval')
 expect(modal.text()).toContain('Human-required tasks remain excluded.')
 expect(modal.findAll('button').find(b=>b.text()==='Enable automatic handoffs')!.attributes('disabled')).toBeDefined()
 expect(f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')).toHaveLength(0)
 await modal.findAll('input[type=checkbox]')[1]!.setValue(true)
 await modal.get('form').trigger('submit');await flushPromises()
 const write=f.mock.calls.find(([url])=>url==='/api/projects/1/handoff-policy')!
 expect(JSON.parse(String(write[1]?.body))).toEqual({revision:1,manifest_hash:'b'.repeat(64),mode:'automatic',approve:true})
 expect(w.text()).toContain('Automatic agent handoffs enabled');w.unmount()
})

it('does not prompt for a routine review while automatic handoffs are enabled',async()=>{
 const task={card_id:5,node_key:'a',role:'story' as const,revision:1,column:'review',title:'Routine document',agent:'codex',model:'gpt-6.1-sol',run_id:7,run_stage:'succeeded'}
 const {w}=await setup('active',[task])
 await w.findAll('button').find(b=>b.text()==='Approve all except human-required tasks…')!.trigger('click');await flushPromises()
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 await modal.findAll('input[type=checkbox]')[1]!.setValue(true)
 await modal.get('form').trigger('submit');await flushPromises()
 await w.findAll('button').find(b=>b.text()==='Stories & runs')!.trigger('click');await flushPromises()
 expect(w.findAll('button').some(b=>b.text()==='Review handoff')).toBe(false)
 w.unmount()
})

it('reruns an unaccepted successful story without accepting its old handoff',async()=>{
 const {w,f}=await setup('active',[{card_id:5,node_key:'a',role:'story',revision:1,column:'review',title:'Inventory',agent:'codex',model:'gpt-6.1-sol',run_id:6,run_stage:'succeeded'}])
 await w.findAll('button').find(b=>b.text()==='Stories & runs')!.trigger('click');await flushPromises()
 await w.findAll('button').find(b=>b.text()==='Rerun same story')!.trigger('click');await flushPromises()
 const writes=f.mock.calls.filter(([u,init])=>init?.method==='POST'&&u!=='/api/keys/check')
 expect(writes.map(([url])=>url)).toEqual(['/api/projects/1/stories/5/retry'])
 expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:1})
 w.unmount()
})

it('closes an unfinished project only with a reason and shows it as Closed, never Complete',async()=>{
 const prompt=vi.spyOn(window,'prompt').mockReturnValueOnce('').mockReturnValueOnce('Superseded by the RCD project')
 vi.spyOn(window,'confirm').mockReturnValue(false)
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

it('closes a project and then deletes it after one confirmation, keeping the folder',async()=>{
 vi.spyOn(window,'prompt').mockReturnValue('Replanned as a new project')
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);confirm.mockClear()
 const {w,f}=await setup('active')
 const inner=globalThis.fetch
 const posted:{url:string,body:unknown}[]=[]
 vi.stubGlobal('fetch',(url:string,init?:RequestInit)=>{
  if(url==='/api/projects/1/delete'&&init?.method==='POST'){posted.push({url,body:JSON.parse(String(init.body))});return Promise.resolve(new Response(JSON.stringify({deleted:1,working_dir_kept:'/tmp/project'}),{status:200,headers:{'content-type':'application/json'}}))}
  return inner(url as never,init)
 })
 await w.findAll('button').find(b=>b.text()==='Close project…')!.trigger('click');await flushPromises()
 const write=f.mock.calls.find(([url])=>url==='/api/projects/1/close')!
 expect(JSON.parse(String(write[1]?.body))).toEqual({revision:1,reason:'Replanned as a new project',remove_tasks:true})
 expect(posted).toEqual([{url:'/api/projects/1/delete',body:{revision:expect.any(Number),confirm:true}}])
 expect(confirm).toHaveBeenCalledTimes(1);expect(confirm.mock.calls[0]![0]).toContain('The working folder and its files are kept')
 w.unmount()
})
it('can still close a project and remove only its tasks, keeping the project and ledger',async()=>{
 vi.spyOn(window,'prompt').mockReturnValue('Parked for now')
 const confirm=vi.spyOn(window,'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);confirm.mockClear()
 const {w,f}=await setup('active')
 await w.findAll('button').find(b=>b.text()==='Close project…')!.trigger('click');await flushPromises()
 const write=f.mock.calls.find(([url])=>url==='/api/projects/1/close')!
 expect(JSON.parse(String(write[1]?.body))).toEqual({revision:1,reason:'Parked for now',remove_tasks:true})
 expect(f.mock.calls.some(([url])=>url==='/api/projects/1/delete')).toBe(false)
 expect(confirm).toHaveBeenCalledTimes(2);w.unmount()
})

it('offers no close action for a completed or planning project',async()=>{
 for(const state of ['complete','planning','dispatching']){
  const {w}=await setup(state);expect(w.findAll('button').some(b=>b.text()==='Close project…')).toBe(false);w.unmount()
 }
})

it('keeps the economy worker default free of a subscription-only model',()=>{
 const economy=newNode('story',0,null,45)
 expect(economy.assignee).toBe('openclaw');expect(economy.model).toBe('')
 const balanced=newNode('story',0,null,50)
 expect(balanced.assignee).toBe('codex');expect(balanced.model).toBe('gpt-6-luna')
})

it('locks models at project level and restores approved failover when unlocked',async()=>{
 const {w,f}=await setup('active',[],null,'/projects?project=1&view=work')
 const toggle=w.findAll('input[type="checkbox"]').find(i=>i.element.parentElement?.textContent?.includes('Model lock'))!
 expect(toggle.exists()).toBe(true)
 await toggle.setValue(true);await flushPromises()
 expect(w.text()).toContain('Failures stop on the assigned model')
 const request=f.mock.calls.find(([url])=>url==='/api/projects/1/model-lock')!
 expect(JSON.parse(String(request[1]?.body))).toEqual({revision:1,enabled:true})
 await toggle.setValue(false);await flushPromises()
 expect(w.text()).toContain('Approved equivalent models can take over')
 w.unmount()
})

it('opens the consultant proposal as an editable brief without starting project planning',async()=>{
 const {w,f}=await setup('draft',[],null,'/projects')
 w.getComponent(ProjectConsultant).vm.$emit('review',{title:'Consulted goal',brief:'Goal, phases, scope, definitions of done and dependencies',working_dir:'/tmp/project'})
 await flushPromises()
 const {DOMWrapper}=await import('@vue/test-utils');const dialog=new DOMWrapper(document.querySelector('[role=dialog]')!)
 expect((dialog.get('input[data-autofocus]').element as HTMLInputElement).value).toBe('Consulted goal')
 expect((dialog.get('textarea').element as HTMLTextAreaElement).value).toContain('definitions of done')
 expect(dialog.findAll('button').find(b=>b.text()==='Submit to Hermes')!.attributes('disabled')).toBeDefined()
 expect(f.mock.calls.filter(([u,init])=>(init?.method??'GET')!=='GET'&&u!=='/api/keys/check')).toHaveLength(0)
 w.unmount()
})

it('builds in parallel only when the person turns it on when creating the project',async()=>{
 const {w,f}=await setup()
 await w.findAll('button').find(b=>b.text()==='+ New project')!.trigger('click')
 const {DOMWrapper}=await import('@vue/test-utils');const modal=new DOMWrapper(document.querySelector('[role=dialog]')!)
 await modal.get('input[data-autofocus]').setValue('Fast project');await modal.get('textarea').setValue('A reviewed brief')
 await modal.get('[data-testid=parallel-new]').setValue(true)
 await modal.get('input[type=checkbox]:not([data-testid])').setValue(true);await modal.get('form').trigger('submit');await flushPromises()
 const created=f.mock.calls.find(([url,init])=>url==='/api/projects'&&init?.method==='POST')!
 expect(JSON.parse(String(created[1]?.body)).dispatch_mode).toBe('parallel');w.unmount()
})
