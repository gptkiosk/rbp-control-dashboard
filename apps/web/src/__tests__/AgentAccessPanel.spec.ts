import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AgentAccessPanel from '@/components/AgentAccessPanel.vue'
import { stubFetch, calls, headerOf } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.innerHTML = '' })

it('requires explicit review and approval, defaults to read only, and never displays a credential', async () => {
  const f = stubFetch((url, init) => {
    if (url === '/api/agent-access') return { body: init?.method === 'POST' ? { id: 'grant' } : { grants: [], auth_enabled: true, token_file: '/private/hermes.token' } }
  })
  const w = mount(AgentAccessPanel, { attachTo: document.body }); await flushPromises()
  await w.get('header button').trigger('click'); await flushPromises()
  expect(w.get('[role="dialog"]').text()).toContain('cannot start runs')
  expect(calls(f, 'POST', '/api/agent-access')).toHaveLength(0)
  await w.findAll('button').find(b => b.text() === 'Approve Hermes access')!.trigger('click'); await flushPromises()
  const [url, init] = calls(f, 'POST', '/api/agent-access')[0]!
  expect(url).toBe('/api/agent-access')
  expect(JSON.parse(init!.body as string)).toEqual({ scope: 'read', days: 7 })
  expect(headerOf(init, 'X-Mac-Control')).toBe('1')
  expect(w.find('[role="dialog"]').exists()).toBe(false)
  expect(w.text()).toContain('credential stays in its private local file')
  w.unmount()
})

it('revokes active access and reports failures without creating another grant', async () => {
  const grant = { id: 'one', agent: 'hermes', scope: 'draft', state: 'active', expires_at: 1900000000, last_used_at: null }
  const f = stubFetch((url, init) => {
    if (url === '/api/agent-access') return { body: { grants: [grant], auth_enabled: true, token_file: '/private/hermes.token' } }
    if (url === '/api/agent-access/one/revoke') return { status: 409, body: { detail: 'Could not revoke' } }
  })
  const w=mount(AgentAccessPanel);await flushPromises()
  await w.findAll('button').find(b=>b.text()==='Revoke access')!.trigger('click');await flushPromises()
  expect(w.text()).toContain('Could not revoke')
  expect(calls(f,'POST','/api/agent-access/one/revoke')).toHaveLength(1)
  expect(calls(f,'POST','/api/agent-access').filter(([url]) => url === '/api/agent-access')).toHaveLength(0)
  w.unmount()
})
