import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import OpenRouterSpend from '@/components/OpenRouterSpend.vue'
import type { OpenRouterSpending } from '@/lib/api'
const data: OpenRouterSpending = {
  checked_at: 100,
  unavailable_agents: [],
  meters: [{ id: 'shared', agents: ['hermes','openclaw'], state: 'ready', checked_at: 100, updated_at: Date.now()/1000, today_usd: 0, week_usd: 0, month_usd: 0, lifetime_usd: 37.32966, byok_month_usd: 0.030098 }],
}
describe('OpenRouter spending', () => {
  it('shows a shared key once, true zeros, BYOK and UTC windows separately', () => {
    const w=mount(OpenRouterSpend,{props:{data}})
    expect(w.findAll('.meter')).toHaveLength(1)
    expect(w.text()).toContain('Shared key · Hermes + OpenClaw')
    expect(w.text()).toContain('$0.00000')
    expect(w.text()).toContain('$0.03010')
    expect(w.text()).toContain('This month · UTC')
    expect(w.text()).toContain('cannot be separated by key')
  })
  it('keeps key-wide charges for agent selection and hides for subscription agents', () => {
    expect(mount(OpenRouterSpend,{props:{data,agent:'hermes'}}).text()).toContain('Shared key')
    expect(mount(OpenRouterSpend,{props:{data,agent:'codex'}}).find('section').exists()).toBe(false)
  })
  it('labels stale figures and never invents zero for unavailable charges', () => {
    const stale=mount(OpenRouterSpend,{props:{data:{...data,meters:[{...data.meters[0]!,state:'stale'}]}}})
    expect(stale.text()).toContain('Last known spending')
    const missing=mount(OpenRouterSpend,{props:{data:{...data,meters:[{id:'x',agents:['hermes'],state:'unavailable',checked_at:100}]}}})
    expect(missing.text()).toContain('Charges are not available yet')
    expect(missing.text()).not.toContain('$0.00000')
  })
  it('shows missing key configuration and loading states', () => {
    expect(mount(OpenRouterSpend,{props:{}}).text()).toContain('Waiting for OpenRouter')
    expect(mount(OpenRouterSpend,{props:{data:{meters:[],checked_at:100,unavailable_agents:['hermes']}}}).text()).toContain('Hermes: no readable default OpenRouter key')
  })
})
