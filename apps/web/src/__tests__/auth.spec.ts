import { afterEach, describe, it, expect, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import { useAuthStore } from '@/stores/auth'
import App from '@/App.vue'
import LoginGate from '@/components/LoginGate.vue'
import { getJson } from '@/lib/api'
const reply = (body: unknown, status=200) => new Response(JSON.stringify(body), { status })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
async function mounted(component=App, path='/agents') {
  const pinia=createPinia(); setActivePinia(pinia)
  const router=createAppRouter(createMemoryHistory()); await router.push(path); await router.isReady()
  const w=mount(component,{global:{plugins:[pinia,router]}})
  await flushPromises()
  return { w, auth:useAuthStore(), router }
}
describe('Authentication gate', () => {
  it('never mounts protected views until access is known, including failed bootstrap',async () => {
    const calls:string[]=[]
    vi.stubGlobal('fetch',vi.fn((p:string)=>{calls.push(p); return p==='/healthz' ? Promise.resolve(reply({status:'ok'})) : Promise.reject(Error('offline'))}))
    const {w}=await mounted()
    expect(w.find('[aria-label="Main"]').exists()).toBe(false)
    expect(w.text()).toContain('Could not check sign-in status')
    expect(calls).not.toContain('/api/agents')
    w.unmount()
  })
  it('shows Google sign-in for anonymous sessions and keeps protected fetches stopped',async () => {
    const calls:string[]=[]
    vi.stubGlobal('fetch',vi.fn((p:string)=>{calls.push(p); return Promise.resolve(reply(p==='/auth/status' ? {enabled:true,user:null,local_recovery:false} : {status:'ok'}))}))
    const {w}=await mounted()
    expect(w.get('a.btn.primary').attributes('href')).toBe('/auth/login?next=%2Fagents')
    expect(w.text()).toContain('Continue with Google')
    expect(w.find('details').exists()).toBe(false)
    expect(calls).not.toContain('/api/agents')
    w.unmount()
  })
  it('returns to the gate on a 401 and removes expired sessions',async () => {
    setActivePinia(createPinia())
    const auth=useAuthStore()
    auth.enabled=true; auth.user={email:'user@example.com',method:'google',expires_at:9999999999}
    vi.stubGlobal('fetch',vi.fn((p:string)=>Promise.resolve(reply(p==='/auth/status' ? {enabled:true,user:null,local_recovery:false} : {detail:'Sign in'},p==='/auth/status'?200:401))))
    auth.start(); await flushPromises()
    await expect(getJson('/api/agents')).rejects.toThrow('Sign in')
    await flushPromises()
    expect(auth.user).toBeNull(); expect(auth.access).toBe(false)
    auth.stop()
  })
  it('shows local recovery only when the server allows it and clears the entered token',async () => {
    vi.stubGlobal('fetch',vi.fn((p:string)=>Promise.resolve(reply({detail:'bad'},401))))
    const {w,auth}=await mounted(LoginGate,'/login?error=signin_failed')
    auth.enabled=true; auth.localRecovery=true; await flushPromises()
    expect(w.text()).toContain('Sign-in did not complete')
    await w.get('input').setValue('private-token')
    await w.get('form').trigger('submit'); await flushPromises()
    expect((w.get('input').element as HTMLInputElement).value).toBe('')
    expect(w.text()).not.toContain('private-token')
    expect(w.text()).toContain('Recovery failed')
    w.unmount()
  })
})
