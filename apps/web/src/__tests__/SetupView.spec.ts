import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import { useAuthStore } from '@/stores/auth'
import SetupView from '@/views/SetupView.vue'
import SetupPrompt from '@/components/SetupPrompt.vue'
import { stubFetch } from './helpers'
import type { Profile } from '@/lib/profile'
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); document.body.innerHTML = '' })
async function setup(step=0, component: typeof SetupView | typeof SetupPrompt = SetupView) {
  let profile: Profile = {owner:'operator@example.com',preferences:{theme:'dark',planning_bias:81,working_dir:'/workspace',dashboard_origin:'',discord_channel_id:'',notify_plans:true,allow_discord_planning:false,allow_discord_control:false,allow_discord_diagnostics:false},credentials:[],discord_linked:false,discord_user_id:null,origins:['http://127.0.0.1:8800','https://example.test:9443']}
  const fetch=stubFetch((url,init)=>{
    if(url==='/auth/status') return {body:{enabled:true,user:{email:profile.owner,method:'google',expires_at:10000},local_recovery:false}}
    if(url==='/api/profile/setup') {profile.preferences.setup=JSON.parse(String(init?.body));return {body:{...profile,origins:undefined}}}
    if(url==='/api/profile/credentials/openrouter') {profile.credentials=[{provider:'openrouter',hint:'1234'}];return {body:profile}}
    if(url==='/api/profile' && init?.method==='PUT') {profile.preferences=JSON.parse(String(init.body));return {body:profile}}
    if(url==='/api/profile') return {body:profile}
    if(url==='/api/agents') return {body:{agents:[{id:'hermes',available:true},{id:'openclaw',available:false},{id:'claude',available:true},{id:'codex',available:true}]}}
    if(url==='/api/workdirs') return {body:{workdirs:[{path:'/workspace',branch:null,root:'/workspace'}]}}
  })
  const pinia=createPinia();setActivePinia(pinia)
  const auth=useAuthStore();auth.enabled=true;auth.user={email:profile.owner,method:'google',expires_at:10000}
  const router=createAppRouter(createMemoryHistory());await router.push(component===SetupView ? `/setup?step=${step}` : '/')
  const w=mount(component,{global:{plugins:[pinia,router]},attachTo:document.body});await flushPromises()
  return {w,fetch,profile,router,auth}
}
it('resumes steps in the profile without touching permissions, native agents or unrelated defaults',async()=>{
  const {w,fetch,profile}=await setup()
  await w.get('.wizard-footer .primary').trigger('click');await flushPromises()
  expect(w.get('h2').text()).toBe('Google sign-in')
  expect(w.text()).toContain('https://example.test:9443/auth/callback')
  const write=fetch.mock.calls.find(([url])=>url==='/api/profile/setup')!
  expect(JSON.parse(String(write[1]?.body))).toEqual({step:1,status:'in_progress',confirmed:[]})
  expect(profile.preferences.planning_bias).toBe(81);expect(profile.preferences.allow_discord_planning).toBe(false)
  expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
  w.unmount()
})
it('reports missing executables without claiming their login or provider is verified',async()=>{
  const {w}=await setup(2)
  expect(w.text()).toContain('Executable detected');expect(w.text()).toContain('Executable not found')
  expect(w.text()).toContain('does not verify provider login or gateway health')
  expect(w.find('a[href="/profile#discord-profile"]').exists()).toBe(true)
  w.unmount()
})
it('saves a key write-only and clears the input before leaving or recording progress',async()=>{
  const {w,fetch}=await setup(3);const secret='sk-or-test-private1234'
  await w.get('#setup-openrouter').setValue(secret)
  await w.get('.key-form').trigger('submit');await flushPromises()
  expect((w.get('#setup-openrouter').element as HTMLInputElement).value).toBe('')
  expect(w.text()).not.toContain(secret);expect(localStorage.length).toBe(0)
  expect(w.text()).toContain('Native agent routes are unchanged')
  await w.get('.wizard-footer .primary').trigger('click');await flushPromises()
  const state=fetch.mock.calls.find(([url])=>url==='/api/profile/setup')!
  expect(String(state[1]?.body)).not.toContain(secret)
  w.unmount()
})
it('finishes a walkthrough while keeping unmet prerequisites visible and not dispatching jobs',async()=>{
  const {w,fetch}=await setup(6)
  expect(w.get('.readiness').text()).toContain('Pending · Hermes and OpenClaw')
  expect(w.find('a[href="/help?topic=agent-tasks"]').exists()).toBe(false)
  await w.get('.wizard-footer .primary').trigger('click');await flushPromises()
  expect(w.text()).toContain('Your pending checklist items remain visible')
  expect(w.find('a[href="/help?topic=agent-tasks"]').exists()).toBe(true)
  const writes=fetch.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')
  expect(writes.map(([url])=>url)).toEqual(['/api/profile/setup'])
  expect(JSON.parse(String(writes[0]![1]?.body)).status).toBe('complete')
  w.unmount()
})
it('offers first-run setup and persists Later without making setup inaccessible',async()=>{
  const {w,fetch}=await setup(0,SetupPrompt)
  expect(w.get('a[href="/setup"]').text()).toBe('Start setup wizard')
  await w.get('button').trigger('click');await flushPromises()
  expect(w.find('aside').exists()).toBe(false)
  const write=fetch.mock.calls.find(([url])=>url==='/api/profile/setup')!
  expect(JSON.parse(String(write[1]?.body)).status).toBe('deferred')
  w.unmount()
})
