/** Shapes of GET /api/models/profiles and POST /api/models/refresh (see apps/api/model_profiles.py). */
export interface ModelNote { id: string; model: string; text: string; source: string; date: string; stale: boolean }
export interface KindStat { kind: string; runs: number; success_rate: number; first_pass: number; proven: boolean }
export interface ModelProfile {
  evidence?: { metric: string; value: number | boolean; unit: string; source: string; as_of: string; benchmark: string; scale_max: number | null; environment: string; method: string; stale: boolean; conflicting: boolean }[]
  selection?: { class: string; use: string; speed: string; source: string | null; verified: string | null; vision: boolean | null; stale?: boolean }
  id: string; name: string; free: boolean | null; platform: string | null; agents: string[]; status: string | null; in_catalog: boolean; in_snapshot: boolean
  context: number | null; tools: boolean | null; structured: boolean | null; reasoning: boolean | null; inputs: string[]
  price_in: number | null; price_out: number | null
  observed: { runs: number; success_rate: number; median_seconds: number | null; tokens: number; cost_usd: number; served_instead_of_requested: number; proven: boolean } | null
  kinds: KindStat[]; notes: ModelNote[]
}
export interface Profiles {
  generated_at: number; days: number; proven_runs: number; stale_days: number; stale_notes: number
  snapshot: { fetched_at: number; count: number; free: number } | null; models: ModelProfile[]
  watch?: { enabled: boolean; interval_days: number; last_run: number | null; last_ok: boolean | null; last_error: string | null; last_summary: string | null; last_card_id: number | null; due: boolean }
}
export interface RefreshResult {
  fetched_at: number; count: number; free: number
  diff: { new_free: string[]; no_longer_free: string[]; changed: { id: string; fields: string[] }[]; added_since_last?: number; removed_since_last?: number }
}
