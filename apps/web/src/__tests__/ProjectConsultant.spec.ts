import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ProjectConsultant from '@/components/ProjectConsultant.vue'
import { stubFetch } from './helpers'
vi.mock('@/components/ChatConversation.vue',()=>({default:{props:['threadId'],template:'<div data-test="conversation">Conversation</div>'}}))
afterEach(()=>vi.unstubAllGlobals())
const options={props:{workdirs:[{path:'/workspace',branch:null}],available:true},global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}}
it('opens without a model call and starts a free read-only consultant only on request',async()=>{
 const f=stubFetch(url=> url==='/api/chat/threads'?{body:{id:7}}:url.startsWith('/api/routes?feature=chat')?{body:{feature:'chat',label:'Chat',default:{runtime:'hermes',model:'openrouter/free'},default_note:null,allowed:[],hidden:[],empty_reason:null,scope:{managed:false,managed_error:null,app_saved:true,project:null}}}: {body:{id:1}})
 const w=mount(ProjectConsultant,options)
 await w.get('button').trigger('click');expect(f.mock.calls.filter(([url])=>String(url).startsWith('/api/chat'))).toHaveLength(0)   // opening starts no conversation (it only reads the project types)
 await w.get('input').setValue('Build a dashboard');await w.get('textarea').setValue('Compare goals and dependencies')
 await w.get('form').trigger('submit');await flushPromises()
 const request=JSON.parse(String(f.mock.calls.find(([url])=>url==='/api/chat/threads')![1]?.body))
 expect(request).toMatchObject({agent:'hermes',model:'openrouter/free',mode:'read',working_dir:'/workspace'})
 expect(w.emitted('started')![0]).toEqual([7])
 expect(f.mock.calls.map(([url])=>url)).not.toContain('/api/projects')   // no project is created
 w.unmount()
})
it('starts on the Chat default from Models & providers and hands a completed answer to editable review',async()=>{
 const f=stubFetch(url=> url==='/api/chat/threads'?{body:{id:9}}:url.startsWith('/api/routes?feature=chat')?{body:{feature:'chat',label:'Chat',default:{runtime:'codex',model:'gpt-6-luna'},default_note:null,allowed:[],hidden:[],empty_reason:null,scope:{managed:false,managed_error:null,app_saved:true,project:null}}}:url==='/api/chat/threads/9'?{body:{title:'Project consultant: Goal',working_dir:'/workspace',busy:false,messages:[{role:'assistant',status:'done',text:'Goal\nPhases\nStories\nScope\nDefinitions of done\nDependencies'}]}}:{body:{id:1}})
 const w=mount(ProjectConsultant,{...options,props:{...options.props,preferences:{ai_agent:'codex',ai_model:'gpt-6-luna',theme:'system',planning_bias:50,working_dir:'/workspace',dashboard_origin:'',discord_channel_id:'',notify_plans:true,allow_discord_planning:false,allow_discord_control:false,allow_discord_diagnostics:false}}})
 await w.get('button').trigger('click');await w.get('input').setValue('Goal');await w.get('textarea').setValue('Idea');await w.get('form').trigger('submit');await flushPromises()
 expect(JSON.parse(String(f.mock.calls.find(([url])=>url==='/api/chat/threads')![1]?.body))).toMatchObject({agent:'codex',model:'gpt-6-luna'})
 await w.findAll('button').find(b=>b.text().includes('Review existing brief'))!.trigger('click');await flushPromises()
 expect(w.emitted('review')![0]![0]).toMatchObject({title:'Goal',working_dir:'/workspace',brief:expect.stringContaining('Definitions of done')})
 expect(f.mock.calls.some(([url,init])=>url.startsWith('/api/projects')&&init?.method==='POST')).toBe(false)   // nothing is created or submitted
 w.unmount()
})
it('refuses to hand off an unfinished or approval-pending conversation',async()=>{
 stubFetch(()=>({body:{busy:true,messages:[]}}))
 const w=mount(ProjectConsultant,{...options,props:{...options.props,resumeId:7}})
 await w.get('button').trigger('click');await w.findAll('button').find(b=>b.text().includes('Review existing brief'))!.trigger('click');await flushPromises()
 expect(w.emitted('review')).toBeUndefined();expect(w.text()).toContain('Wait for the conversation')
 w.unmount()
})
it('gives the first message the same knowledge the plan run gets, and still starts if that cannot be read',async()=>{
 const f=stubFetch(url=> url==='/api/chat/threads'?{body:{id:7}}: url.startsWith('/api/projects/consultant-context')?{body:{text:'Starter standards apply. area money: minimum risk high.'}}:{body:{id:1}})
 const w=mount(ProjectConsultant,options)
 await w.get('button').trigger('click');await w.get('input').setValue('Build a dashboard');await w.get('textarea').setValue('Compare goals')
 await w.get('form').trigger('submit');await flushPromises()
 const asked=f.mock.calls.find(([url])=>String(url).startsWith('/api/projects/consultant-context'))![0]
 expect(asked).toBe('/api/projects/consultant-context?working_dir=%2Fworkspace&project_type=')
 const body=JSON.parse(String(f.mock.calls.find(([url])=>url==='/api/chat/threads/7/messages')![1]?.body))
 const sent=body.context
 expect(sent).toContain('advice for this conversation, not authorization')
 expect(sent).toContain('area money: minimum risk high')
 expect(body.text).toBe('Compare goals')                                                // the bubble shows what the owner wrote and nothing else
 expect(sent).toContain('Project: Build a dashboard')
 expect(body.text).not.toContain('advice for this conversation')                      // background is sent apart from the operator's words, so it cannot trip the approval check
 w.unmount()
 const g=stubFetch(url=> url==='/api/chat/threads'?{body:{id:8}}: url.startsWith('/api/projects/consultant-context')?{status:500,body:{detail:'boom'}}:{body:{id:1}})
 const v=mount(ProjectConsultant,options)
 await v.get('button').trigger('click');await v.get('input').setValue('X');await v.get('textarea').setValue('Y')
 await v.get('form').trigger('submit');await flushPromises()
 const sentBody=JSON.parse(String(g.mock.calls.find(([url])=>url==='/api/chat/threads/8/messages')![1]?.body))
 expect(sentBody.text).toBe('Y');expect(sentBody.context).not.toContain('What this installation knows')
 v.unmount()
})
it('says plainly why a route cannot start and leaves the form open to change the model',async()=>{
 const f=stubFetch(url=> url==='/api/chat/threads'?{status:409,body:{detail:'Hermes cannot run openrouter/free here: that route has not been reviewed for pricing. Choose a model in Profile, AI defaults.'}}:{body:{id:1}})
 const w=mount(ProjectConsultant,options)
 await w.get('button').trigger('click');await w.get('input').setValue('Site');await w.get('textarea').setValue('A simple site')
 await w.get('form').trigger('submit');await flushPromises()
 expect(w.get('[role="alert"]').text()).toContain('has not been reviewed for pricing')
 expect(w.find('form').exists()).toBe(true)                                          // nothing was started; the operator can fix the default and retry
 expect(f.mock.calls.some(([url])=>String(url).includes('/messages'))).toBe(false)
 w.unmount()
})
it('lets the owner say when it is enough, then writes up the brief and opens it for review',async()=>{
 vi.useFakeTimers()
 let drafted=false
 const f=stubFetch((url,init)=>{
  if(url==='/api/chat/threads'&&init?.method==='POST') return {body:{id:11}}
  if(url==='/api/chat/threads/11/messages'){ if(String(init?.body).includes('That is enough')) drafted=true; return {body:{id:1}} }
  if(url==='/api/chat/threads/11') return {body:{title:'Project consultant: Site',working_dir:'/workspace',busy:!drafted?false:false,messages:[{role:'assistant',status:'done',text: drafted?'Goal\nPhases\nStories\nScope':'What audience is the site for?'}]}}
  return {body:{id:1}}
 })
 const w=mount(ProjectConsultant,options)
 await w.get('button').trigger('click');await w.get('input').setValue('Site');await w.get('textarea').setValue('A simple site');await w.get('form').trigger('submit');await flushPromises()
 expect(w.emitted('review')).toBeUndefined()                                          // talking does not submit anything
 await w.findAll('button').find(b=>b.text().includes('Review project summary'))!.trigger('click');await flushPromises()
 await vi.advanceTimersByTimeAsync(2100);await flushPromises()
 const ask=f.mock.calls.filter(([url])=>url==='/api/chat/threads/11/messages').map(([,init])=>JSON.parse(String(init?.body)))
 expect(ask).toHaveLength(2);expect(ask[1].text).toContain('That is enough')
 expect(w.emitted('review')![0]![0]).toMatchObject({brief:expect.stringContaining('Phases'),working_dir:'/workspace'})
 expect(f.mock.calls.some(([url,init])=>url.startsWith('/api/projects')&&init?.method==='POST')).toBe(false)   // still nothing created or submitted
 w.unmount();vi.useRealTimers()
})

const typeList=[{id:'website-property',label:'Website property (static site with generated media)',summary:'A static site.',failure_points:[],human_signoffs:[],visual_checks:''},{id:'other',label:'Other (does not exactly fit)',summary:'Does not fit.',failure_points:[],human_signoffs:[],visual_checks:''}]
it('asks for the project type before starting, with Other for what does not fit, and hands it to the context and the review',async()=>{
 const f=stubFetch((url)=> url==='/api/project-types'?{body:{types:typeList}}: url==='/api/chat/threads'?{body:{id:12}}: url==='/api/chat/threads/12'?{body:{title:'Project consultant: Goal',working_dir:'/workspace',busy:false,messages:[{role:'assistant',status:'done',text:'Goal\nPhases\nStories\nDefinitions of done'}]}}: url.startsWith('/api/projects/consultant-context')?{body:{text:'The operator chose the project type Other.'}}:{body:{id:1}})
 const w=mount(ProjectConsultant,{...options})
 await w.get('button').trigger('click');await flushPromises()
 const select=w.get('select[aria-label="Project type"]')
 const labels=select.findAll('option').map(o=>o.text())
 expect(labels[0]).toBe('Choose a project type…');expect(labels).toContain('Other (does not exactly fit)')
 await w.findAll('input')[0]!.setValue('Goal');await w.get('textarea').setValue('Something unusual');await w.get('form').trigger('submit');await flushPromises()
 expect(w.text()).toContain('Choose a project type');expect(f.mock.calls.some(([url])=>url==='/api/chat/threads')).toBe(false)   // nothing starts without a type
 await select.setValue('other');await w.get('form').trigger('submit');await flushPromises()
 const ctx=f.mock.calls.find(([url])=>String(url).startsWith('/api/projects/consultant-context'))![0]
 expect(String(ctx)).toContain('project_type=other')
 const sent=f.mock.calls.find(([url,init])=>String(url).includes('/messages')&&init?.method==='POST')!
 expect(String(JSON.parse(String(sent[1]?.body)).context)).toContain('Project type: other')
 await w.findAll('button').find(b=>b.text().includes('Review existing brief'))!.trigger('click');await flushPromises()
 expect(w.emitted('review')![0]![0]).toMatchObject({project_type:'other'})
 w.unmount()
})
