import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import QueuedTaskRouteAction from '@/components/QueuedTaskRouteAction.vue'
import { card, calls, stubFetch } from './helpers'
afterEach(()=>vi.unstubAllGlobals())
it('requires approval and changes a queued task with optimistic route checks',async()=>{
 const c=card({id:50,column:'queued',agent:'claude',model:'claude-sonnet-5-5',project:{id:2,node_key:'a',role:'story'}})
 const f=stubFetch(()=>({body:{revision:1,state:'paused',tasks:[{card_id:50,queued_route_options:[{agent:'codex',model:'gpt-6-luna'}]}]}}))
 const w=mount(QueuedTaskRouteAction,{props:{card:c},global:{stubs:{RouterLink:true}}});await flushPromises()
 expect(w.get('button').attributes('disabled')).toBeDefined()
 await w.get('select').setValue('codex:gpt-6-luna');await w.get('input').setValue(true)
 await w.get('button').trigger('click');await flushPromises()
 const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)
 expect(writes[0]![0]).toBe('/api/projects/2/stories/50/route')
 expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:1,agent:'codex',model:'gpt-6-luna',expected_agent:'claude',expected_model:'claude-sonnet-5-5',acknowledge:true})
 expect(w.emitted('changed')).toHaveLength(1)
 await w.setProps({card:{...c,column:'running'}});expect(w.find('button').exists()).toBe(false);w.unmount()
})
