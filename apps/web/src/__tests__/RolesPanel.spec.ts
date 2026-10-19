import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RolesPanel from '@/components/RolesPanel.vue'
import { stubFetch } from './helpers'
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
it('previews exact managed changes before applying or rolling back instructions', async()=>{
 const roles={hermes:'delegator',codex:'worker'}
 const status={roles,workspace:'',available:['hermes','codex'],delegator:'hermes',guidance_installed:false,revision:'a'.repeat(64),rollback_available:false,recovery_required:false}
 const f=stubFetch((url,init)=>{
  if(url==='/api/roles') return {body:status}
  if(url==='/api/roles/preview') return {body:{roles:JSON.parse(String(init?.body)).roles,workspace:'',plan_sha256:'b'.repeat(64),changes:[{path:'/synthetic/.codex/AGENTS.md',diff:'+ Managed guidance'}],notice:'Guidance does not authorize execution'}}
  if(url==='/api/roles/apply') return {body:status}
 })
 const w=mount(RolesPanel,{attachTo:document.body});await flushPromises()
 expect(w.find('#role-hermes').exists()).toBe(false)
 expect(w.get('#role-codex').findAll('option').map(o=>o.attributes('value'))).toEqual(['worker','reviewer','security'])
 expect(f.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
 await w.findAll('button').find(b=>b.text()==='Preview role changes')!.trigger('click');await flushPromises()
 expect(document.body.textContent).toContain('/synthetic/.codex/AGENTS.md')
 expect(document.body.textContent).toContain('Your surrounding instructions are retained')
 expect(f.mock.calls.some(([url])=>url==='/api/roles/apply')).toBe(false)
 await w.findAll('button').find(b=>b.text()==='Confirm assignment and instructions')!.trigger('click');await flushPromises()
 const call=f.mock.calls.find(([url])=>url==='/api/roles/apply')!
 expect(JSON.parse(String(call[1]?.body))).toEqual({roles:{hermes:'delegator',codex:'worker'},workspace:'',plan_sha256:'b'.repeat(64),confirm:true})
 w.unmount()
})
