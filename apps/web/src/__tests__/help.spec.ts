import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, RouterView } from 'vue-router'
import { defineComponent, ref } from 'vue'
import { createAppRouter } from '@/router'
import { helpGuides, findGuides } from '@/lib/help'
import HelpChat from '@/components/HelpChat.vue'
import HelpView from '@/views/HelpView.vue'
import { useHelpStore } from '@/stores/help'
import { useGuideAction } from '@/composables/useGuideAction'

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })

describe('how-to answers and deep links', () => {
  it('finds specific workflows and refuses to invent an unrelated answer', () => {
    expect(findGuides('How do I configure a $20 Codex subscription?')[0]?.id).toBe('subscriptions')
    expect(findGuides('How do I track actual OpenRouter spending?')[0]?.id).toBe('openrouter')
    expect(findGuides('How do I revoke Hermes access?')[0]?.id).toBe('hermes-access')
    expect(findGuides('How do I chat with mm-developer?')[0]?.id).toBe('openclaw-chat')
    expect(findGuides('How do I do that?', 'dependencies')[0]?.id).toBe('dependencies')
    expect(findGuides('Where can I buy a pizza?', 'dependencies')).toEqual([])
    expect(findGuides('Which project type should I pick for a website?')[0]?.id).toBe('project-types')
    expect(findGuides('How do I generate images and video with fal for my project?')[0]?.id).toBe('project-media')
    expect(findGuides('Why was my fal bill higher than the estimate and how do I avoid double generation?')[0]?.id).toBe('media-spend')
    expect(findGuides('fal will not let me add minimax to the allowed models')[0]?.id).toBe('fal-key')
    expect(findGuides('How do I use accept anyway on an unfinished story?')[0]?.id).toBe('accept-anyway')
    expect(findGuides('Is my machine ready to build a project and push to GitHub?')[0]?.id).toBe('host-readiness')
    expect(findGuides('')).toEqual([])
  })
  it('covers every feature with resolvable local links and complete steps', () => {
    const router = createAppRouter(createMemoryHistory())
    expect(new Set(helpGuides.map(g => g.id)).size).toBe(helpGuides.length)
    expect(helpGuides.length).toBe(49)
    expect(findGuides('Approve all project handoffs')[0]?.id).toBe('project-approvals')
    expect(findGuides('grok only')[0]?.id).toBe('models-providers')
    for (const guide of helpGuides) {
      expect(guide.steps.length).toBeGreaterThanOrEqual(3)
      expect(guide.links.length).toBeGreaterThan(0)
      for (const link of guide.links) {
        expect(link.to.startsWith('/')).toBe(true)
        expect(link.to.startsWith('//')).toBe(false)
        expect(router.resolve(link.to).name).not.toBe('not-found')
      }
    }
  })
})

describe('local help chat', () => {
  it('answers, links to the feature, clears history and makes no network requests', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/mcp'); await router.isReady()
    const pinia = createPinia()
    const wrapper = mount(HelpChat, { global: { plugins: [pinia, router] }, attachTo: document.body })
    const help = useHelpStore(pinia)
    help.show(); await flushPromises()
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    await wrapper.get('textarea').setValue('How do I revoke Hermes access?')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.get('[role="log"]').text()).toContain('Manage Hermes planning access')
    expect(wrapper.findAll('a').some(a => a.attributes('href') === '/mcp#agent-access-title')).toBe(true)
    expect(fetch).not.toHaveBeenCalled()
    await wrapper.findAll('button').find(b => b.text() === 'Clear conversation')!.trigger('click')
    expect(wrapper.get('[role="log"]').text()).toContain('What would you like to do?')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await flushPromises()
    expect(help.open).toBe(false)
    wrapper.unmount()
  })
  it('escapes question text and shows a useful unmatched-question fallback', async () => {
    const router = createAppRouter(createMemoryHistory()); await router.push('/help')
    const pinia = createPinia(); const wrapper = mount(HelpChat, { global: { plugins: [pinia, router] }, attachTo: document.body })
    useHelpStore(pinia).show(); await flushPromises()
    await wrapper.get('textarea').setValue('<img src=x onerror=evil(1)> pizza')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.get('[role="log"]').text()).toContain('couldn’t match')
    expect(wrapper.findAll('a').some(a => a.text() === 'Browse all how-tos')).toBe(true)
    wrapper.unmount()
  })
})

describe('guides and form links', () => {
  it('loads a bookmarked guide and filters topics', async () => {
    const router = createAppRouter(createMemoryHistory()); await router.push('/help?topic=subscriptions')
    const wrapper = mount(HelpView, { global: { plugins: [createPinia(), router] } })
    expect(wrapper.get('.guide-reading').text()).toContain('Configure subscriptions')
    await wrapper.get('input').setValue('OpenRouter')
    expect(wrapper.findAll('.topic').length).toBe(7)   // includes AI & models (openrouter/free)
    wrapper.unmount()
  })
  it('opens a linked form once and consumes its action without submitting anything', async () => {
    const { createRouter } = await import('vue-router')
    const opened = vi.fn()
    const Harness = defineComponent({ setup() { const visible = ref(false); useGuideAction('new', () => { opened(); visible.value = true }); return { visible } }, template: '<p>{{visible}}</p>' })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/tasks', component: Harness }] })
    await router.push('/tasks?action=new&card=9#board-controls')
    const wrapper = mount(RouterView, { global: { plugins: [router] } }); await flushPromises()
    expect(opened).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.query).toEqual({ card: '9' })
    expect(router.currentRoute.value.hash).toBe('#board-controls')
    wrapper.unmount()
  })
})
