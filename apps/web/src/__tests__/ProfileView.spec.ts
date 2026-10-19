import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ProfileView from '@/views/ProfileView.vue'
import { stubFetch } from './helpers'
afterEach(()=>{vi.unstubAllGlobals();localStorage.clear()})
async function setup() {
  let profile={owner:'operator@example.com',preferences:{theme:'light',planning_bias:50,working_dir:'/tmp/project',dashboard_origin:'',discord_channel_id:'123456789012345678',notify_plans:true,allow_discord_planning:false},discord_linked:false,discord_user_id:null,credentials:[] as {provider:string;hint:string}[],origins:['http://127.0.0.1:8800']}
  const fetch=stubFetch((url,init)=>{
    if(url==='/api/profile' && init?.method==='PUT') {profile={...profile,preferences:JSON.parse(String(init.body))};return {body:profile}}
    if(url==='/api/profile')return {body:profile}
    if(url==='/api/workdirs')return {body:{workdirs:[{path:'/tmp/project',branch:null}]}}
    if(url==='/api/profile/credentials/openrouter') {profile={...profile,credentials:init?.method==='DELETE'?[]:[{provider:'openrouter',hint:'1234'}]};return {body:profile}}
    if(url==='/api/profile/discord/pair')return {body:{instruction:'Link my MCD profile with code PRIVATECODE'}}
  })
  const w=mount(ProfileView,{global:{plugins:[createPinia()]}});await flushPromises();return {w,fetch}
}
it('saves credentials write-only and clears the field without browser storage',async()=>{
  const {w,fetch}=await setup();const key='sk-or-test-key1234'
  await w.get('[aria-label="openrouter credential"]').setValue(key)
  await w.findAll('button').find(b=>b.text()==='Save credential')!.trigger('click');await flushPromises()
  expect((w.get('[aria-label="openrouter credential"]').element as HTMLInputElement).value).toBe('')
  expect(w.text()).not.toContain(key);expect(w.text()).toContain('Saved ····1234');expect(localStorage.length).toBe(0)
  const write=fetch.mock.calls.find(([url,init])=>url==='/api/profile/credentials/openrouter'&&init?.method==='PUT')!
  expect(JSON.parse(String(write[1]?.body))).toEqual({value:key});w.unmount()
})
it('saves the channel before requesting a one-time pairing code',async()=>{
  const {w,fetch}=await setup()
  await w.findAll('button').find(b=>b.text()==='Get pairing code')!.trigger('click');await flushPromises()
  const writes=fetch.mock.calls.filter(([,init])=>(init?.method??'GET')!=='GET')
  expect(writes.map(([url])=>url)).toEqual(['/api/profile','/api/profile/discord/pair'])
  expect(w.text()).toContain('within 10 minutes');expect(w.text()).toContain('PRIVATECODE')
  expect(JSON.parse(String(writes[0]![1]?.body)).allow_discord_planning).toBe(false);w.unmount()
})

it('offers sharing the saved OpenRouter key only once a key is saved, saves just that switch, and says what it does',async()=>{
  const {w,fetch}=await setup()
  expect(w.find('[data-testid="share-key"]').exists()).toBe(false)                // no key saved: nothing to share
  await w.get('[aria-label="openrouter credential"]').setValue('sk-or-test-key1234')
  await w.findAll('button').find(b=>b.text()==='Save credential')!.trigger('click');await flushPromises()
  const box=w.get('[data-testid="share-key"]')
  expect((box.element as HTMLInputElement).checked).toBe(false)                   // off by default
  expect(w.text()).toContain('Claude, Codex and Grok never receive it')
  expect(w.text()).toContain('use a dedicated key with a credit limit')
  await box.setValue(true);await flushPromises()
  const put=fetch.mock.calls.filter(([u,i])=>u==='/api/profile'&&i?.method==='PUT').at(-1)!
  expect(JSON.parse(String(put[1]!.body)).use_saved_openrouter_key).toBe(true)
  expect(w.text()).toContain('now use your saved OpenRouter key')
})

it('never exports the sharing switch with portable preferences',async()=>{
  const {w}=await setup()
  const blobs:Blob[]=[]
  vi.stubGlobal('URL',{...URL,createObjectURL:(b:Blob)=>{blobs.push(b);return 'blob:x'},revokeObjectURL:()=>{}})
  await w.findAll('button').find(b=>b.text()==='Export')!.trigger('click');await flushPromises()
  expect(blobs.length).toBeGreaterThan(0)
  expect(await blobs[0]!.text()).not.toContain('use_saved_openrouter_key')
})

it('keeps Settings first and opens the group that holds a linked section, so old #agent-tools links still land',async()=>{
  const {w}=await setup()
  const panel=(label:string)=>w.get(`[role="tabpanel"][aria-label="${label}"]`)
  expect(w.get('[data-tab="settings"]').attributes('aria-selected')).toBe('true')
  expect(panel('Updates and installs').attributes('style')).toContain('display: none')
  await w.get('[data-tab="updates"]').trigger('click')
  expect(panel('Updates and installs').attributes('style')??'').not.toContain('display: none')
  expect(panel('Settings').attributes('style')).toContain('display: none')
  w.unmount()
  window.location.hash='#github-settings'
  const again=await setup()
  expect(again.w.get('[data-tab="maintenance"]').attributes('aria-selected')).toBe('true')
  again.w.unmount();window.location.hash=''
})
