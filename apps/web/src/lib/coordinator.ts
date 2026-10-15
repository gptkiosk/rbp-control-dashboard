/** Shape of GET /api/coordinator/scorecard (see apps/api/scorecard.py). */
export interface PlanEdits { added: number; removed: number; changed: number; total: number; nodes_returned: number }
export interface PlanRow {
  project_id: number; revision: number; title: string; approved_at: number | null; planner: string | null; delegator: string | null
  wording: { label: string; sha: string } | null; score: number; failed: string[]; returned_score: number | null; edits: PlanEdits | null
  stories: number; done: number; first_pass: number; failed_stories: number; estimate_ratio: number | null
}
export interface Group { label: string; plans: number; score: number; edits_per_plan: number | null; first_pass_rate: number | null; estimate_ratio: number | null; stories_done: number }
export interface Scorecard { generated_at: number; days: number; plans: PlanRow[]; by_planner: Group[]; by_wording: Group[]; briefs: number; note: string }
