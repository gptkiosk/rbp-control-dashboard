import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import RouteRecoveryPanel from '@/components/RouteRecoveryPanel.vue'
import RouteRecoveryNotice from '@/components/RouteRecoveryNotice.vue'
import { stubFetch } from './helpers'

afterEach(() => vi.unstubAllGlobals())
const info = () => ({
  policy:{enabled:false,apply_to_stories:false,routes:[]},subscription_allowed:false,
  options:[{agent:'claude',model:'claude-haiku-5-5',price_class:'subscription',installed:true,allowed:false,cost:'Uses membership quota.'},
    {agent:'hermes',model:'openrouter/free',price_class:'free',installed:true,allowed:true,cost:'Free endpoint; availability varies.'}],
  health:[],recommendations:[{agent:'hermes',model:'openrouter/free',message:'3 of its last 5 attempts failed. A different route may be needed.',cost:'API routes add charges.',link:'/profile#route-recovery'}],window_days:7,sample_limit:500,
})
it('explains persistent failures and cost, and saves only the explicitly enabled route policy',async()=>{
  const calls:{url:string;body:unknown}[]=[]
  const data=info()
  stubFetch((url,init)=>{
    if(url==='/api/profile/route-reliability'){
      if(init?.method==='PUT'){calls.push({url,body:JSON.parse(String(init.body))});return {body:{...data,policy:JSON.parse(String(init.body))}}}
      return {body:data}
    }
  })
  const w=mount(RouteRecoveryPanel,{global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}});await flushPromises()
  expect(w.text()).toContain('A different route may be needed')
  expect(w.text()).toContain('Paid API routes add provider charges')
  expect(calls).toEqual([])
  await w.get('input[role="switch"]').setValue(true)
  const check=w.findAll('.route-check input').at(1)!
  await check.setValue(true)
  await w.findAll('button').find(b=>b.text()==='Save recovery settings')!.trigger('click');await flushPromises()
  expect(calls[0]?.body).toEqual({enabled:true,apply_to_stories:false,routes:[{agent:'hermes',model:'openrouter/free'}]})
  expect(w.emitted('saved')).toHaveLength(1)
})
it('shows the cost classes and sends changes to Models & providers instead of a second switch',async()=>{
  stubFetch(url=>{ if(url==='/api/profile/route-reliability')return {body:info()} })
  const w=mount(RouteRecoveryPanel,{global:{stubs:{RouterLink:{props:['to'],template:'<a :href="to"><slot /></a>'}}}});await flushPromises()
  const line=w.get('[data-testid="cost-classes"]')
  expect(line.text()).toContain('membership off')
  expect(line.text()).toContain('overage settings still apply')
  expect(line.get('a').attributes('href')).toBe('/profile#models-providers')
  expect(w.findAll('input[role="switch"]')).toHaveLength(2)
})
it('points a failed task directly to the recovery toggle without changing a setting',()=>{
  const w=mount(RouteRecoveryNotice,{props:{failed:true},global:{stubs:{RouterLink:{props:['to'],template:'<a :href="to"><slot /></a>'}}}})
  expect(w.get('a').attributes('href')).toBe('/profile#route-recovery')
  expect(w.text()).toContain('Paid API routes add provider charges')
})
