import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MembershipPrerequisites from '@/components/MembershipPrerequisites.vue'
import RecommendedAgentMix from '@/components/RecommendedAgentMix.vue'

it('distinguishes native membership entitlement and API charges before installation', () => {
  const w = mount(MembershipPrerequisites)
  expect(w.text()).toContain('$20/month')
  expect(w.text()).toContain('$30/month')
  expect(w.text()).toContain('API keys and API/Console billing are separate')
  expect(w.text()).toContain('does not purchase a membership')
  expect(w.text()).toContain('only need memberships for agents you choose')
  expect(w.find('a[href="https://docs.x.ai/x-subscription/pricing"]').exists()).toBe(true)
})
it('shows the free baseline and platform-specific worker limits without buying or configuring accounts', () => {
  for (const platform of ['mac', 'pi'] as const) {
    const w = mount(RecommendedAgentMix, { props: { platform } })
    expect(w.find('a[href="https://openrouter.ai/"]').exists()).toBe(true)
    expect(w.text()).toContain('hermes setup')
    expect(w.text()).toContain('openrouter/free')
    expect(w.text()).toContain('BYOK')
    expect(w.find('button').exists()).toBe(false)
    if (platform === 'pi') {
      expect(w.text()).toContain('experimental')
      expect(w.text()).toContain('ZeroClaw')
      expect(w.text()).toContain('PicoClaw')
    } else expect(w.text()).toContain('OpenClaw')
  }
})
