export interface SetupProgress {
  step: number; status: 'new' | 'in_progress' | 'deferred' | 'complete'
  confirmed: ('host' | 'native_routes' | 'subscriptions' | 'tour')[]
}
export interface Preferences {
  theme: 'system' | 'light' | 'dark'; planning_bias: number; working_dir: string
  dashboard_origin: string; discord_channel_id: string; notify_plans: boolean; allow_discord_planning: boolean; allow_discord_control: boolean; allow_discord_diagnostics: boolean
  setup?: SetupProgress
}
export interface Profile {
  owner: string; preferences: Preferences; discord_linked: boolean; discord_user_id: string | null
  credentials: { provider: string; hint: string }[]; origins?: string[]; suggested_discord_channel?: string
}
