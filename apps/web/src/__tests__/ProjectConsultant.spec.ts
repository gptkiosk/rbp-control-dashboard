import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ProjectConsultant from '@/components/ProjectConsultant.vue'
import { stubFetch } from './helpers'
vi.mock('@/components/ChatConversation.vue',()=>({default:{props:['threadId'],template:'<div data-test="conversation">Conversation</div>'}}))
afterEach(()=>vi.unstubAllGlobals())
const options={props:{workdirs:[{path:'/workspace',branch:null}],available:true},global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}}
it('opens without a model call and starts a free read-only consultant only on request',async()=>{
 const f=stubFetch(url=> url==='/api/chat/threads'?{body:{id:7}}: {body:{id:1}})
 const w=mount(ProjectConsultant,options)
 await w.get('button').trigger('click');expect(f).not.toHaveBeenCalled()
 await w.get('input').setValue('Build a dashboard');await w.get('textarea').setValue('Compare goals and dependencies')
 await w.get('form').trigger('submit');await flushPromises()
 const request=JSON.parse(String(f.mock.calls.find(([url])=>url==='/api/chat/threads')![1]?.body))
 expect(request).toMatchObject({agent:'hermes',model:'openrouter/free',mode:'read',working_dir:'/workspace'})
 expect(w.emitted('started')![0]).toEqual([7])
 expect(f.mock.calls.map(([url])=>url)).not.toContain('/api/projects')
 w.unmount()
})
it('uses explicit membership profile defaults and hands a completed answer to editable review',async()=>{
 const f=stubFetch(url=> url==='/api/chat/threads'?{body:{id:9}}:url==='/api/chat/threads/9'?{body:{title:'Project consultant: Goal',working_dir:'/workspace',busy:false,messages:[{role:'assistant',status:'done',text:'Goal\nPhases\nStories\nScope\nDefinitions of done\nDependencies'}]}}:{body:{id:1}})
 const w=mount(ProjectConsultant,{...options,props:{...options.props,preferences:{ai_agent:'codex',ai_model:'gpt-6-luna',theme:'system',planning_bias:50,working_dir:'/workspace',dashboard_origin:'',discord_channel_id:'',notify_plans:true,allow_discord_planning:false,allow_discord_control:false,allow_discord_diagnostics:false}}})
 await w.get('button').trigger('click');await w.get('input').setValue('Goal');await w.get('textarea').setValue('Idea');await w.get('form').trigger('submit');await flushPromises()
 expect(JSON.parse(String(f.mock.calls[0]![1]?.body))).toMatchObject({agent:'codex',model:'gpt-6-luna'})
 await w.findAll('button').find(b=>b.text().includes('Review brief'))!.trigger('click');await flushPromises()
 expect(w.emitted('review')![0]![0]).toMatchObject({title:'Goal',working_dir:'/workspace',brief:expect.stringContaining('Definitions of done')})
 expect(f.mock.calls.some(([url])=>url.startsWith('/api/projects'))).toBe(false)
 w.unmount()
})
it('refuses to hand off an unfinished or approval-pending conversation',async()=>{
 stubFetch(()=>({body:{busy:true,messages:[]}}))
 const w=mount(ProjectConsultant,{...options,props:{...options.props,resumeId:7}})
 await w.get('button').trigger('click');await w.findAll('button').find(b=>b.text().includes('Review brief'))!.trigger('click');await flushPromises()
 expect(w.emitted('review')).toBeUndefined();expect(w.text()).toContain('Wait for the conversation')
 w.unmount()
})
