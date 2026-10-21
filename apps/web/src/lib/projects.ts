import type { RecoveryInfo } from './routeRecovery'
export interface ProjectNode {
  key: string; kind: 'phase' | 'story'; title: string; description: string; acceptance: string; scope: string
  parent: string | null; depends_on: string[]; assignee: 'human' | 'claude' | 'codex' | 'grok' | 'hermes' | 'openclaw'
  model: string; agent_target: string; mode: 'read' | 'edit'; rationale: string; x: number; y: number
  fallbacks: ('claude' | 'codex' | 'grok')[]
  routes: { agent: 'claude' | 'codex' | 'grok' | 'hermes' | 'openclaw'; model: string }[]
  touches?: string[]; integration?: boolean
}
export interface ProjectDocument {
  title: string; brief: string; constraints: string; working_dir: string
  repository?: { name: string; repo: string; folder: string; branch: string } | null
  project_type?: string | null; planner_agent: 'auto' | 'claude' | 'codex' | 'grok' | 'hermes' | 'openclaw'; planner_model: string; planning_bias: number; dispatch_mode: 'sequential' | 'parallel'; nodes: ProjectNode[]
}
export interface ProjectTask { queued_route_blocker?: string | null; queued_route_options?: {agent: 'claude' | 'codex'; model: string}[]; blocked_by?: number[]; working_dir?: string; agent?: string; model?: string; mode?: 'read'|'edit'; incomplete_reason?: string | null; card_id: number; node_key: string; role: string; revision: number; column: string; title: string; run_id: number | null; run_stage: string | null; planning_retry_routes?: {agent: ProjectNode['assignee']; model: string}[]; retry_routes?: ProjectNode['routes']; free_retry_routes?: { agent: 'openclaw'; model: string; agent_target: string }[]; paid_retry_routes?: { agent: 'openclaw'; model: string; agent_target: string }[]; low_cost_routes?: { agent: 'claude' | 'codex'; model: string }[]; output_approval?: { run_id: number; path: string; plan: string } | null }
export interface Memory { id: number; kind: string; text: string; actor: string; card_id: number | null; run_id: number | null; created_at: number }
export interface Project {
  route_reliability?: RecoveryInfo | null
  bootstrap?: boolean
  id: number; document: ProjectDocument; revision: number; state: string; approved_revision: number | null
  handoff_approval?: { mode: 'manual' | 'automatic'; manifest_hash: string | null; eligible: {card_id:number;title:string;column:string}[]; excluded: {card_id:number;title:string;reason:string}[] }
  model_lock?: boolean
  amendments?: { id: number; text: string; actor: string; created_at: number }[]
  can_resume_plan?: boolean
  standards_check?: { source?: string | null; property?: string | null; problems: string[]; areas: string[]; fixable?: number } | null
  timing?: { runs: number; busy_minutes: number; elapsed_minutes: number; overlap: number } | null
  schedule?: { stories: number; total_minutes: number; critical_minutes: number; speedup: number; width: number; critical_path: string[]; problems: string[]; max_concurrent_runs: number } | null
  pipeline: { step: string; card_id: number; delegator?: {agent:string;model:string} } | null; error: string | null; updated_at: number
  deliveries?: { kind: string; revision: number; status: string; error: string | null; message_id: string | null }[]
  tasks: ProjectTask[]; memory: Memory[]
  workspaces: Record<string, { path: string; branch: string; integration_error?: string | null }>; artifacts: Record<string, { branch: string; head: string; files: string[] }>
}
export interface ProjectSummary { id: number; title: string; state: string; revision: number; updated_at: number }
export function emptyProject(working_dir = ''): ProjectDocument {
  return { title: '', brief: '', constraints: '', working_dir, planner_agent: 'auto', planner_model: '', planning_bias: 50, dispatch_mode: 'sequential', nodes: [] }
}
export function newNode(kind: 'phase' | 'story', index: number, parent: string | null = null, planningBias = 50, openclawTarget = ''): ProjectNode {
  return { key: crypto.randomUUID(), kind, title: kind === 'phase' ? 'New phase' : 'New story', description: '', acceptance: '', scope: '', parent,
    depends_on: [], assignee: planningBias < 50 ? 'openclaw' : 'codex', model: planningBias >= 50 && planningBias < 63 ? 'gpt-6-luna' : '', agent_target: planningBias < 50 ? openclawTarget : '', mode: 'read', rationale: '', x: kind === 'phase' ? 40 : 380,
    y: 50 + index * 150, fallbacks: [], routes: [] }
}
/** Stable hierarchy layout; dependency arrows are rendered separately. */
export function arrange(nodes: ProjectNode[]): ProjectNode[] {
  let row = 0
  const output: ProjectNode[] = []
  function visit(parent: string | null, depth: number) {
    for (const n of nodes.filter(n => (n.parent || null) === parent)) {
      output.push({ ...n, x: 40 + depth * 320, y: 40 + row++ * 150 })
      visit(n.key, depth + 1)
    }
  }
  visit(null, 0)
  return output
}
export function label(state: string): string { return state === 'awaiting_approval' ? 'Awaiting output approval' : state === 'timeout' ? 'Timed out' : state.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()) }

export function planningBiasLabel(value: number): string {
  if (value < 13) return 'Economy · OpenClaw first'
  if (value < 38) return 'Lean toward OpenClaw'
  if (value < 63) return 'Balanced'
  if (value < 88) return 'Lean toward Claude & Codex'
  return 'Capability · Claude & Codex first'
}
export function planningBiasHint(value: number): string {
  if (value < 38) return 'Favor OpenClaw for bounded tasks. If a subscription is needed, start with Haiku or Luna.'
  if (value < 63) return 'Use OpenClaw for routine slices and Haiku/Luna for routine subscription work; step up to Sonnet/Terra only when justified.'
  return 'Favor Claude and Codex for implementation and critical reasoning. Use OpenClaw for smaller supporting tasks.'
}
