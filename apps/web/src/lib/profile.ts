export interface SetupProgress {
  step: number; status: 'new' | 'in_progress' | 'deferred' | 'complete'
  confirmed: ('host' | 'native_routes' | 'subscriptions' | 'tour')[]
}
export interface Preferences {
  ai_agent?: 'hermes' | 'openclaw' | 'claude' | 'codex' | 'grok'; ai_model?: string
  theme: 'system' | 'light' | 'dark'; planning_bias: number; working_dir: string
  dashboard_origin: string; discord_channel_id: string; notify_plans: boolean; use_saved_openrouter_key?: boolean; allow_discord_planning: boolean; allow_discord_control: boolean; allow_discord_diagnostics: boolean; allow_discord_maintenance?: boolean; allow_discord_standards?: boolean; allow_discord_repositories?: boolean
  setup?: SetupProgress
  coordinator_bootstrap?: CoordinatorBootstrapPreferences
}
export interface CoordinatorBootstrapPreferences {
  platforms: ('openclaw' | 'claude' | 'codex' | 'grok')[]
  roles: ('developer' | 'security' | 'reviewer')[]
  shared_project_memory: boolean
  project_workspaces: boolean
  model_policy: 'reuse_configured_default' | 'ask_before_change'
  security_review: 'risk_based' | 'every_project' | 'by_request'
}
export interface Profile {
  owner: string; preferences: Preferences; discord_linked: boolean; discord_user_id: string | null
  credentials: { provider: string; hint: string }[]; origins?: string[]; suggested_discord_channel?: string
}
