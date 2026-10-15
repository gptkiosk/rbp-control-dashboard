/** Typed same-origin JSON client and payload types for the mac-control API. */

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Human-readable text for an API `detail`: a string, a FastAPI validation list, or anything else. */
function detailText(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (d && typeof d === 'object' && 'msg' in d) {
        const item = d as { msg?: unknown; loc?: unknown }
        const where = Array.isArray(item.loc) ? String(item.loc[item.loc.length - 1] ?? '') : ''
        return where && where !== 'body' ? `${where}: ${String(item.msg)}` : String(item.msg)
      }
      return typeof d === 'string' ? d : JSON.stringify(d)
    })
    return parts.join('; ')
  }
  if (detail !== undefined && detail !== null) return JSON.stringify(detail)
  return null
}

async function toApiError(res: Response): Promise<ApiError> {
  if (res.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('mcd:auth-expired'))
  let message = `Request failed (${res.status})`
  try {
    const body = (await res.json()) as { detail?: unknown }
    message = detailText(body?.detail) ?? message
  } catch {
    /* body was not JSON: keep the generic message */
  }
  return new ApiError(message, res.status)
}

/** GET a JSON path. On a non-2xx response throws an ApiError carrying the API's `detail` text. */
export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!res.ok) throw await toApiError(res)
  return (await res.json()) as T
}

/** Header the server requires on every state-changing request (it answers 403 without it). */
export const GUARD_HEADER = 'X-Mac-Control'

async function send<T>(method: 'POST' | 'PATCH' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    [GUARD_HEADER]: '1',
  }
  const init: RequestInit = { method, headers, cache: 'no-store' }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  const res = await fetch(path, init)
  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** POST JSON (or nothing) with the request-guard header. Throws ApiError with the server's `detail`. */
export function postJson<T>(path: string, body?: unknown): Promise<T> {
  return send<T>('POST', path, body)
}

/** PATCH JSON with the request-guard header. Throws ApiError with the server's `detail`. */
export function patchJson<T>(path: string, body?: unknown): Promise<T> {
  return send<T>('PATCH', path, body)
}

/** DELETE with the request-guard header. Resolves to undefined on 204. Throws ApiError on non-2xx. */
export function deleteJson<T = void>(path: string): Promise<T> {
  return send<T>('DELETE', path)
}

type Num = number | null

export interface ReleaseEnvelope {
  version: string
  environment: string
  commit_sha?: string | null
  dirty?: boolean
  has_migrations?: boolean
  owner?: string
  product?: string
}

export type PressureLabel = 'normal' | 'warning' | 'critical'
export type MacmonStatus = 'running' | 'restarting' | 'missing' | 'disabled' | 'starting'

export interface MetricsCurrent {
  ts: Num
  cpu_pct: Num
  ecpu_pct: Num
  pcpu_pct: Num
  gpu_pct: Num
  mem_used: Num
  mem_total: Num
  swap_used: Num
  swap_total: Num
  pressure_level: Num
  disk_used: Num
  disk_total: Num
  net_rx_bps: Num
  net_tx_bps: Num
  cpu_temp: Num
  gpu_temp: Num
  sys_power: Num
  cpu_power: Num
  gpu_power: Num
  ane_power: Num
  ram_power: Num
  fan_rpm: Num
  sample_age_s: Num
  mem_used_pct: Num
  swap_used_pct: Num
  disk_used_pct: Num
  pressure_label: PressureLabel | null
  disk_days_to_full: Num
  /** Host kind reported by the collector ("linux" on a Pi), or null before the collector starts. */
  platform?: string | null
  /** Raspberry Pi firmware flags (`vcgencmd get_throttled`); absent when the host cannot report them. */
  throttled?: boolean
  throttle_flags?: ThrottleFlag[]
  /** Kept for API compatibility with the macOS collector; the Pi UI does not show it. */
  macmon_status?: MacmonStatus
}

/** Active conditions come first; `previously_*` records a condition since boot. */
export type ThrottleFlag =
  | 'under_voltage'
  | 'frequency_capped'
  | 'throttled'
  | 'soft_temp_limit'
  | 'previously_under_voltage'
  | 'previously_frequency_capped'
  | 'previously_throttled'
  | 'previously_soft_temp_limit'

export type SeriesRange = '1h' | '24h' | '7d' | '30d' | '1y'

export interface SeriesPayload {
  range: SeriesRange
  step_s: number
  series: { ts: number[] } & Record<string, (number | null)[]>
}

export type ServiceFlag = 'crash_loop' | 'last_exit_nonzero'

export interface ServiceInfo {
  label: string
  own?: boolean
  domain: string
  state: string
  pid: Num
  runs: Num
  runs_24h: Num
  allowed_runs_24h: Num
  last_exit: string | null
  last_exit_code: Num
  flags: ServiceFlag[]
  severity: 0 | 1 | 2
  schedule: string
  path: string | null
  program: string | null
  observed_at: Num
}

export interface ServicesPayload {
  services: ServiceInfo[]
  crash_loop_threshold_24h: number
}

export interface TopApp {
  app: string
  cpu_pct: Num
  rss: Num
  count: Num
}

export interface TopProcessesPayload {
  apps: TopApp[]
}

export interface TailscalePeer {
  hostname: string
  dns_name: string
  os: string | null
  online: boolean
  active: boolean
  relay: string | null
  direct_addr: string | null
  last_seen: string | null
  ips: string[]
}

export interface TailscaleStatus {
  backend_state: string
  version: string
  tailnet: string | null
  magic_dns_suffix: string | null
  self: { hostname: string; dns_name: string; ips: string[]; online: boolean }
  peers: TailscalePeer[]
  checked_at: Num
}

export interface TailscaleError {
  error: string
  checked_at: Num
}

export type TailscalePayload = TailscaleStatus | TailscaleError

export interface PendingUpdate {
  label: string
  title: string
  version: string | null
  recommended: boolean
  requires_restart: boolean
}

export interface UpdatesOk {
  updates: PendingUpdate[]
  checked_at: Num
}

export interface UpdatesError {
  error: string
  checked_at: Num
}

export type UpdatesPayload = UpdatesOk | UpdatesError

// ---- Phase 3: agents, workdirs, cards, runs ----

export type AgentId = 'claude' | 'codex' | 'grok' | 'hermes' | 'openclaw'
export type RunStage = 'running' | 'succeeded' | 'failed' | 'timeout' | 'cancelled' | 'interrupted' | 'awaiting_approval'
export type CardColumn = 'backlog' | 'queued' | 'running' | 'review' | 'done' | 'failed'
export type CardMode = 'read' | 'edit'

export interface Run {
  approval?: { approval_id: string; question: string; kind: string; options?: { id: string; label: string }[]; proposed_output?: { preview?: string; sha256: string }; expires_at?: number | null; nonce?: string | null } | null
  decision_pending?: boolean
  id: number
  card_id: number
  agent: AgentId
  stage: RunStage
  model_requested: string | null
  model_reported: string | null
  provider: string | null
  started_at: number
  ended_at: Num
  duration_s: Num
  exit_code: Num
  input_tokens: Num
  output_tokens: Num
  cost_usd: Num
  session_id: string | null
  working_dir: string | null
  command: string[] | null
  error: string | null
  result_text: string | null
}

export interface AgentCurrentRun {
  thread_id?: number | null
  run_id: number
  card_id: number
  title: string
  model: string | null
  running_s: number
  liveness?: RunLiveness
}

export interface RunLiveness {
  state: 'live' | 'quiet' | 'dead' | 'unknown'
  stale: boolean
  checked_at: number
  pid_alive: boolean | null
  last_activity_at: number | null
  reason: string
}

export interface UnresponsiveRun {
  run_id: number
  card_id: number | null
  thread_id: number | null
  since_s: number
  liveness: RunLiveness
}

export interface AgentProcess {
  pid: number
  kind: string
  running_s: number
  model: string | null
  session: string | null
  cwd: string | null
}
export interface ConfiguredAgent {
  id: string
  name: string | null
  model: string | null
  default: boolean
  bindings: number
  workspace: string | null
  sessions_24h: Num
  last_active_s: Num
  tokens_24h: Num
  models: string[]
}
export interface AgentSession {
  id: string
  title: string
  workspace: string
  last_active: string
}
export interface Subagents {
  processes: AgentProcess[]
  agents?: ConfiguredAgent[]
  sessions?: AgentSession[]
}
export interface Agent {
  id: AgentId
  name: string
  role: 'worker' | 'manager'
  available: boolean
  binary: string
  default_model: string | null
  suggested_models: string[]
  enforces_mode: boolean
  notes: string
  subscription_configured?: boolean
  current: AgentCurrentRun[]
  unresponsive?: UnresponsiveRun[]
  last_run: Run | null
  runs_24h: Num
  failed_24h: Num
  input_tokens_24h: Num
  output_tokens_24h: Num
  cost_usd_24h: Num
  busy_s_24h: Num
  subagents?: Subagents
}

export interface AgentsPayload {
  subagents_checked_at?: Num
  checked_at?: number
  agents: Agent[]
}

export interface Workdir {
  path: string
  branch: string | null
  root: string
}

export interface WorkdirsPayload {
  workdirs: Workdir[]
}

export type AssigneeType = 'agent' | 'human'
export type Priority = 'urgent' | 'high' | 'normal' | 'low'

export interface Card {
  project?: { id: number; node_key: string; role: string } | null
  superseded_by?: number | null
  closed_project?: boolean
  id: number
  title: string
  body: string
  /** Null on a human task. */
  agent: AgentId | null
  agent_target: string | null
  model: string | null
  mode: CardMode
  /** Null on a human task. */
  working_dir: string | null
  column: CardColumn
  position: number
  timeout_s: number
  idle_timeout_s: number | null
  max_attempts: number
  retry_backoff_s: number
  retry_after: number | null
  budget_usd: Num
  needs_approval: boolean
  approval_reasons: string[]
  approved_at: Num
  /** One-time nonce and route pin the approve request must echo; null when not awaiting approval. */
  approval_challenge?: string | null
  approval_pin?: string | null
  created_by: string
  created_at: number
  updated_at: number
  last_run: Run | null
  assignee_type: AssigneeType
  priority: Priority
  /** YYYY-MM-DD, or null. */
  due_date: string | null
  estimate_minutes: Num
  tags: string[]
  /** Standard job envelope (null on cards made by hand). route_tier is derived by the server. */
  /** A human task's assignee (an approved user's email or short name); null = unassigned. Agent tasks use agent and model. */
  assignee_user?: string | null
  kind?: string | null
  size?: string | null
  risk?: string | null
  area?: string | null
  route_tier?: string | null
  route_reason?: string | null
  /** Definition of done. */
  acceptance: string | null
  depends_on: number[]
  /** The dependencies that are not Done yet. */
  blocked_by: number[]
  dependents: number[]
}

export interface TagCount {
  tag: string
  count: number
}

export interface TagsPayload {
  tags: TagCount[]
}

export interface CardsPayload {
  cards: Card[]
}

export interface CardDetail extends Card {
  runs: Run[]
}

export interface NewCardInput {
  title: string
  body?: string
  assignee_type?: AssigneeType
  agent?: AgentId
  working_dir?: string
  mode?: CardMode
  model?: string | null
  agent_target?: string | null
  timeout_s?: number
  idle_timeout_s?: number | null
  max_attempts?: number
  retry_backoff_s?: number
  budget_usd?: number
  priority?: Priority
  due_date?: string | null
  estimate_minutes?: number | null
  tags?: string[]
  acceptance?: string | null
  depends_on?: number[]
}

export type CardPatch = Partial<
  Pick<
    Card,
    | 'title'
    | 'body'
    | 'agent'
    | 'agent_target'
    | 'model'
    | 'mode'
    | 'working_dir'
    | 'timeout_s'
    | 'idle_timeout_s'
    | 'max_attempts'
    | 'retry_backoff_s'
    | 'budget_usd'
    | 'priority'
    | 'due_date'
    | 'estimate_minutes'
    | 'tags'
    | 'acceptance'
  >
> & { column?: CardColumn; position?: number }

export interface LogChunk {
  text: string
  next_offset: number
  done: boolean
  stage: RunStage | null
}

// ---- Phase 3b: chat and MCP ----

export type ChatMessageStatus = 'pending_approval' | 'running' | 'done' | 'failed' | 'cancelled'

export interface ChatThreadLastMessage {
  role: 'user' | 'assistant'
  text: string
  status: ChatMessageStatus
}

export interface ChatThread {
  id: number
  agent: AgentId
  agent_target: string | null
  title: string
  model: string | null
  mode: CardMode
  working_dir: string
  session_id: string | null
  created_at: number
  last_activity_at: number
  busy: boolean
  last_message: ChatThreadLastMessage | null
}

export interface ChatThreadsPayload {
  threads: ChatThread[]
}

export interface ChatMessage {
  id: number
  thread_id: number
  role: 'user' | 'assistant'
  text: string
  /** Characters of background the app sent to the agent with this message (not shown in the bubble). */
  context_chars?: number
  status: ChatMessageStatus
  approval_reasons: string[]
  approved_at: Num
  run_id: number | null
  model: string | null
  input_tokens: Num
  output_tokens: Num
  cost_usd: Num
  duration_s: Num
  created_at: number
}

export interface ChatThreadDetail extends ChatThread {
  messages: ChatMessage[]
}

export interface NewChatInput {
  agent: AgentId
  working_dir: string
  mode: CardMode
  title?: string
  model?: string
  agent_target?: string
}

export interface McpServer {
  name: string
  target: string
  transport: 'stdio' | 'http' | null
  status: string | null
  enabled: boolean
  source: string
  removable: boolean
  env_names?: string[]
}

export interface McpAgentServers {
  agent: AgentId
  servers: McpServer[]
  error: string | null
  /** false when the agent's command is not on this host: shown as a quiet note, not an error. */
  installed?: boolean
  checked_at: Num
}

export interface McpServersPayload {
  agents: McpAgentServers[]
}

export interface McpEnvNamesPayload {
  names: string[]
}

export type McpChangeStatus = 'pending' | 'applied' | 'failed' | 'rejected'

export interface McpChangeSpec {
  transport: 'stdio' | 'http' | null
  command: string | null
  args: string[] | null
  url: string | null
  env_names: string[] | null
}

export interface McpChange {
  id: number
  agent: AgentId
  action: 'add' | 'remove'
  name: string
  spec: McpChangeSpec
  status: McpChangeStatus
  output: string | null
  note: string | null
  created_at: number
  decided_at: Num
}

export interface McpChangesPayload {
  changes: McpChange[]
}

export interface NewMcpChangeInput {
  agent: AgentId
  action: 'add' | 'remove'
  name: string
  transport?: 'stdio' | 'http'
  command?: string
  args?: string[]
  url?: string
  env_names?: string[]
  note?: string
}

export interface UsageSummary {
  responses: number
  input_tokens: number | null
  output_tokens: number | null
  cached_input_tokens: number
  cache_write_tokens: number
  api_equivalent_usd: number | null
  unpriced: number
  unpriced_models?: string[]
  sessions: number
  last_active: number | null
  models: (Omit<UsageSummary, 'models'> & { model: string })[]
}
export interface BillingAccount {
  mode: 'api' | 'subscription'
  monthly_usd: number
}
export interface ModelRate {
  long_after?: number
  long_input_multiplier?: number
  long_output_multiplier?: number
  input: number
  output: number
  cached: number
  write: number
  write_1h: number
  max_input: number | null
  source?: string
  verified?: string
}
export interface BillingSettings {
  accounts: Record<AgentId, BillingAccount>
  rates: Record<string, ModelRate>
  timezone: string
}
export interface AgentUsage extends UsageSummary {
  agent: AgentId
  billing: BillingAccount
  month_api_equivalent_usd: number | null
  month_unpriced: number
  month_subscription_usd: number | null
  month_savings_usd: number | null
  lifetime_sessions_excluded: number
  month_lifetime_sessions_excluded?: number
}
export interface UsageSession extends UsageSummary {
  name?: string | null
  agent: AgentId
  id: string
  parent: string | null
  scope: string
}
export interface UsageActivity {
  id: string
  agent: AgentId
  session_id: string
  target?: string | null
  ts: number
  model: string | null
  input_tokens: number | null
  output_tokens: number | null
  cached_input_tokens: number | null
  cache_write_tokens: number | null
  api_equivalent_usd: number | null
  cost_basis: string
  scope: string
  source: string
  parent?: string | null
  stage?: string
  card_id?: number
  thread_id?: number
}
export interface OpenRouterMeter {
  id: string
  agents: AgentId[]
  state: 'ready' | 'stale' | 'unavailable'
  checked_at: number
  updated_at?: number
  today_usd?: number | null
  week_usd?: number | null
  month_usd?: number | null
  lifetime_usd?: number | null
  byok_today_usd?: number | null
  byok_week_usd?: number | null
  byok_month_usd?: number | null
  byok_lifetime_usd?: number | null
  include_byok_in_limit?: boolean | null
  limit_reset?: string | null
  limit_usd?: number | null
  remaining_usd?: number | null
}
export interface OpenRouterSpending {
  meters: OpenRouterMeter[]
  unavailable_agents: AgentId[]
  checked_at: number | null
}
export interface UsagePayload {
  openrouter?: OpenRouterSpending
  period: '24h' | '7d' | 'month'
  start: number
  end: number
  month_start: number
  timezone: string
  overview: AgentUsage[]
  summary: UsageSummary
  sessions: UsageSession[]
  activity: UsageActivity[]
  coverage: Partial<
    Record<
      AgentId,
      { state: string; checked_at: number | null; files?: number; pending_files?: number; note?: string }
    >
  >
  note: string
}

export function putJson<T>(path: string, body?: unknown): Promise<T> { return send<T>('PUT', path, body) }
