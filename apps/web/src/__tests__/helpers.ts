import { vi } from 'vitest'
import type { Agent, Card, Run } from '@/lib/api'

export interface Reply {
  status?: number
  body?: unknown
}

export type Handler = (url: string, init: RequestInit | undefined) => Reply | undefined

/** A fetch stand-in: the handler answers by URL and method; unknown URLs answer 404 so a stray call is loud. */
export function stubFetch(handler: Handler) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const reply = handler(String(url), init) ?? {
      status: 404,
      body: { detail: `unmocked ${init?.method ?? 'GET'} ${url}` },
    }
    const status = reply.status ?? 200
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => reply.body,
    }
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

export function calls(fn: ReturnType<typeof stubFetch>, method: string, pathStart: string) {
  return fn.mock.calls.filter(
    ([url, init]) => (init?.method ?? 'GET') === method && String(url).startsWith(pathStart),
  )
}

export function headerOf(init: RequestInit | undefined, name: string): string | undefined {
  return (init?.headers as Record<string, string> | undefined)?.[name]
}

export function run(over: Partial<Run> = {}): Run {
  return {
    id: 1,
    card_id: 1,
    agent: 'claude',
    stage: 'succeeded',
    model_requested: null,
    model_reported: 'claude-x',
    provider: 'anthropic',
    started_at: 1_000,
    ended_at: 1_004,
    duration_s: 3.7,
    exit_code: 0,
    input_tokens: 10,
    output_tokens: 5,
    cost_usd: 0.0123,
    session_id: 'sess-1',
    working_dir: '/w',
    command: ['claude', '-p', '<prompt>'],
    error: null,
    result_text: 'All done',
    ...over,
  }
}

export function card(over: Partial<Card> = {}): Card {
  return {
    id: 1,
    title: 'Card',
    body: 'Do the thing',
    agent: 'claude',
    agent_target: null,
    model: null,
    mode: 'read',
    working_dir: '/w',
    column: 'backlog',
    position: 1,
    timeout_s: 1800,
    idle_timeout_s: null,
    max_attempts: 1,
    retry_backoff_s: 0,
    retry_after: null,
    budget_usd: 1,
    needs_approval: false,
    assignee_type: 'agent',
    priority: 'normal',
    due_date: null,
    estimate_minutes: null,
    tags: [],
    acceptance: null,
    depends_on: [],
    blocked_by: [],
    dependents: [],
    approval_reasons: [],
    approved_at: null,
    created_by: 'operator',
    created_at: 1,
    updated_at: 1,
    last_run: null,
    ...over,
  }
}

export function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: 'claude',
    name: 'Claude Code',
    role: 'worker',
    available: true,
    binary: '/bin/claude',
    default_model: null,
    suggested_models: ['claude-sonnet-5-5'],
    enforces_mode: true,
    notes: 'Enforced.',
    current: [],
    last_run: null,
    runs_24h: 0,
    failed_24h: 0,
    input_tokens_24h: 0,
    output_tokens_24h: 0,
    cost_usd_24h: 0,
    busy_s_24h: 0,
    ...over,
  }
}
