export interface Freshness { checked_at: number | null; error: string | null; stale: boolean }
export interface Repository { name: string; description: string | null; url: string; private: boolean; archived: boolean; branch: string; updated_at: string }
export interface GithubSetup { state: 'migration_required' | 'configuration_error' | 'disabled' | 'unconfigured' | 'ready'; message?: string; error?: string }
export interface RepositoryProblem { name: string; reason: 'not_found' | 'denied' | 'unavailable'; hint?: string | null }
export interface Repositories extends Freshness { repos: Repository[]; limited: boolean; setup?: GithubSetup; problems?: RepositoryProblem[] }

/** One plain sentence per repository RCD could not read, with the real reason. */
export function problemLine(p: RepositoryProblem): string {
  if (p.reason === 'not_found') return `${p.name} was not found for this GitHub login. Check the spelling in Settings > GitHub.${p.hint ? ` Did you mean ${p.hint}?` : ''}`
  if (p.reason === 'denied') return `GitHub refused access to ${p.name}. Check the gh login, the repository permission or the rate limit.`
  return `${p.name} could not be read right now. It will be tried again.`
}
export interface GithubItem { number: number; title: string; user: string; updated_at: string; draft: boolean; labels: string[]; url: string }
export interface GithubStream extends Freshness { items?: GithubItem[]; limited?: boolean }
export interface RepositoryDetails { name: string; pulls: GithubStream; issues: GithubStream }
export interface Report { id: string; name: string; size: number; modified_at: number; readable: boolean; source?: string; source_id?: string; title?: string }
export interface ReportSource { id: string; root: string; mode: string; state: string; available: boolean; error: string | null }
export interface Reports { sources?: ReportSource[]; reports: Report[]; available: boolean; error: string | null; limited: boolean; root: string }
export interface ReportContent extends Report { content: string; format: 'text' | 'markdown'; response_only?: boolean; finding_tasks?: Record<string, FindingTaskStatus | null> }
/** Linked task state for one finding, as returned with a report. `null` entries mean the task was removed. */
export interface FindingTaskStatus { task_id: number; task_status: string; run_id: number | null; run_status: string | null }
export interface ReportFinding { id: string; status: 'warn' | 'crit'; reason: string; evidence: string }
export function dateLabel(value: number | string | null): string {
  if (value === null) return 'Not checked yet'
  const date = new Date(typeof value === 'number' ? value * 1000 : value)
  return Number.isNaN(date.getTime()) ? 'Not reported' : date.toLocaleString()
}
export function bytesLabel(bytes: number): string { return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KiB` }
export type CheckStatus = 'ok' | 'warn' | 'crit' | 'missing'
export interface OpsSource { id: string; kind: string; status: CheckStatus; summary: string | null; evidence: string | null; checked_at: number | null; since: number | null; stale: boolean }
export interface OpsSchedule { id: string; label: string; enabled: boolean; every_s: number | null; at: string | null; weekday: number | null; sources?: string[]; last_run: number | null; next_due: number | null }
export interface OpsArchive { archived: number; already: number; left_in_place: string[]; bytes: number; at: number }
export interface OpsLastRun { at: number; checked: string[]; cached: number; changed: string[]; report: string | null; schedule: string | null }
export interface OpsCollectorStatus { enabled: boolean; error: string | null; schedules: OpsSchedule[]; archive: OpsArchive | null; sources: OpsSource[]; overall: 'ok' | 'warn' | 'crit'; last_run: OpsLastRun | null; link: string }
