export interface RecoveryRoute { agent: 'hermes'|'openclaw'|'claude'|'codex'|'grok'; model: string }
export interface RecoveryPolicy { enabled: boolean; apply_to_stories: boolean; routes: RecoveryRoute[] }
export interface RecoveryInfo {
  policy: RecoveryPolicy
  options: (RecoveryRoute & { price_class: string; installed: boolean; allowed: boolean; cost: string })[]
  health: (RecoveryRoute & { attempts: number; failures: number; recent_failures: number; persistent: boolean; last_failure: string|null; categories: Record<string, number> })[]
  recommendations: (RecoveryRoute & { message: string; cost: string; link: string })[]
  window_days: number; sample_limit: number; host_free_only: boolean; subscription_allowed: boolean; paid_allowed?: boolean
}
