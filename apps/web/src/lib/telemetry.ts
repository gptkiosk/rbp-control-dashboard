/** Shapes of GET /api/telemetry (see apps/api/telemetry.py). */
export interface TelemetryTiles {
  unassigned: number; in_progress: number; waiting_for_you: number; completed: number; completed_days: number
  estimates_missing: number; failed: number; untagged: number
}
export interface AssigneeRow { name: string; type: 'human' | 'agent'; open: number; done: number; failed: number }
export interface JobRow {
  job: string; project_id: number; title: string; stories: number; done: number; failed: number; open: number
  estimate_minutes: number; actual_minutes: number; cost_usd: number; api_equivalent_usd: number; last_activity: number
}
export interface PropertyRow { property: string; stories: number; open: number; done: number; failed: number; first_pass_rate: number | null; median_minutes: number | null }
export interface KindRow { kind: string; stories: number; done: number; median_minutes: number | null; first_pass_rate: number | null; median_actual_over_estimate: number | null }
export interface ModelRow {
  agent: string; model: string; tier: string; runs: number; succeeded: number; success_rate: number; median_seconds: number | null
  tokens: number; cost_usd: number; api_equivalent_usd: number; served_instead_of_requested: number
}
export interface ActivityRow { at: number; card_id: number; title: string; outcome: string; assignee: string; agent: string; model: string | null; job: string | null }
export interface Telemetry {
  generated_at: number; days: number; filters: Record<string, string>; options: Record<string, string[]>
  tiles: TelemetryTiles; by_status: { column: string; count: number }[]; by_property: PropertyRow[]; by_tier: { tier: string; count: number }[]; by_assignee: AssigneeRow[]; velocity: { week: string; done: number }[]
  jobs: JobRow[]; by_kind: KindRow[]; models: ModelRow[]; activity: ActivityRow[]
  totals: { cost_usd: number; api_equivalent_usd: number; unpriced_runs: number; tokens: number; cards: number }
  note: string
}
export const FILTERS = ['job', 'property', 'kind', 'risk', 'size', 'tier', 'assignee', 'agent', 'model'] as const
export type FilterKey = (typeof FILTERS)[number]

export function money(value: number): string {
  return value === 0 ? '$0' : value < 0.01 ? '<$0.01' : `$${value.toFixed(2)}`
}
export function minutes(value: number | null): string {
  if (value == null || value === 0) return '–'
  return value < 90 ? `${Math.round(value)} min` : `${(value / 60).toFixed(1)} h`
}
export function seconds(value: number | null): string {
  if (value == null) return '–'
  return value < 90 ? `${Math.round(value)} s` : `${(value / 60).toFixed(1)} min`
}
export function percent(value: number | null): string {
  return value == null ? '–' : `${Math.round(value * 100)}%`
}
