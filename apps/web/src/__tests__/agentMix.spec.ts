import { describe, expect, it } from 'vitest'
import { anyInstalled, firstInstalled, NATIVE_AGENTS, SUBSCRIPTION_CLIS } from '@/lib/agentMix'

const only = (...ids: string[]) => (id: string) => (ids.includes(id) ? true : false)

describe('any mix of agents', () => {
  it('needs only one subscription CLI, whichever it is', () => {
    for (const id of SUBSCRIPTION_CLIS) expect(anyInstalled(only(id), SUBSCRIPTION_CLIS)).toBe(true)
    expect(anyInstalled(only('hermes', 'openclaw'), SUBSCRIPTION_CLIS)).toBe(false)
    expect(anyInstalled(only(), SUBSCRIPTION_CLIS)).toBe(false)
  })
  it('treats a check that has not finished as not installed, never as installed', () => {
    expect(anyInstalled(() => undefined, SUBSCRIPTION_CLIS)).toBe(false)
  })
  it('needs only one of the native agents', () => {
    expect(anyInstalled(only('openclaw'), NATIVE_AGENTS)).toBe(true)
    expect(anyInstalled(only('hermes'), NATIVE_AGENTS)).toBe(true)
    expect(anyInstalled(only('claude'), NATIVE_AGENTS)).toBe(false)
  })
  it('starts a new story on the first installed agent in the preferred order', () => {
    expect(firstInstalled(only('grok', 'claude'), ['codex', 'claude', 'grok'])).toBe('claude')
    expect(firstInstalled(only('grok'), ['codex', 'claude', 'grok'])).toBe('grok')
    expect(firstInstalled(only(), ['codex', 'claude', 'grok'])).toBeUndefined()
  })
})
