import type { CheckStatus, OpsSource, Report } from '@/lib/operations'

/** Ordering and wording for check severity. `missing` is a configured check with no result yet. */
export const SEVERITY_ORDER: Record<CheckStatus, number> = { crit: 0, missing: 1, warn: 2, ok: 3 }
export const SEVERITY_LABEL: Record<CheckStatus, string> = { crit: 'Critical', missing: 'Missing', warn: 'Warning', ok: 'OK' }

/**
 * Dashboard page for each collector kind. This mirrors LINKS in apps/api/ops_collectors.py.
 * Hardware kinds point at the host page (/pi here, /mac in MCD); service checks use the shared Services page.
 */
export const KIND_LINKS: Record<string, string> = {
  jobs: '/tasks', waits: '/tasks', agents: '/agents', memory: '/pi', disk: '/pi', load: '/pi',
  service: '/services', release: '/profile', dir_age: '/pi',
}
export const PAGE_LABELS: Record<string, string> = { '/tasks': 'Tasks', '/agents': 'Agents', '/pi': 'Pi health', '/services': 'Services', '/profile': 'Settings', '/reports': 'Ops reports' }

export const ARCHIVED_PREFIX = 'Historic (archived) · '
export type ReportKind = 'fleet' | 'archived' | 'hermes' | 'other'
export const REPORT_KIND_LABEL: Record<ReportKind | 'all', string> = { all: 'All reports', fleet: 'Fleet health', archived: 'Archived copies', hermes: 'Hermes archive', other: 'Other Ops reports' }

export function linkFor(kind: string): string {
  return KIND_LINKS[kind] ?? '/reports'
}

export function pageLabel(path: string): string {
  return PAGE_LABELS[path] ?? 'Ops reports'
}

/** Worst severity across checks; an empty list falls back to the backend's own summary. */
export function worstSeverity(sources: OpsSource[], fallback: 'ok' | 'warn' | 'crit'): CheckStatus {
  if (!sources.length) return fallback
  return sources.reduce<CheckStatus>((worst, s) => (SEVERITY_ORDER[s.status] < SEVERITY_ORDER[worst] ? s.status : worst), 'ok')
}

/** Most severe first, then by id, so the list reads as a triage queue. */
export function sortChecks(sources: OpsSource[]): OpsSource[] {
  return [...sources].sort((a, b) => SEVERITY_ORDER[a.status] - SEVERITY_ORDER[b.status] || a.id.localeCompare(b.id))
}

/** Case-insensitive search over id, kind, summary and evidence; level `all` keeps every severity. */
export function filterChecks(sources: OpsSource[], query: string, level: CheckStatus | 'all'): OpsSource[] {
  const needle = query.trim().toLowerCase()
  return sources.filter(s => (level === 'all' || s.status === level)
    && (!needle || [s.id, s.kind, s.summary ?? '', s.evidence ?? ''].some(text => text.toLowerCase().includes(needle))))
}

/** Duration in words: "< 1 min", "45 min", "3 h", "2 d". */
export function duration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return '< 1 min'
  if (s < 3600) return `${Math.floor(s / 60)} min`
  if (s < 86400) return `${Math.floor(s / 3600)} h`
  return `${Math.floor(s / 86400)} d`
}

/** Relative time from an epoch-seconds timestamp. `now` is passed in so the caller controls refresh. */
export function ago(at: number | null | undefined, now: number): string {
  if (at === null || at === undefined) return 'never'
  const s = now - at
  return s < 60 ? 'just now' : `${duration(s)} ago`
}

export function reportKind(report: Report): ReportKind {
  if (report.title?.startsWith(ARCHIVED_PREFIX)) return 'archived'
  if (report.source_id === 'hermes') return 'hermes'
  if (report.source_id === 'ops' && report.name.startsWith('fleet-health/')) return 'fleet'
  return 'other'
}

export function filterReports(reports: Report[], query: string, kind: ReportKind | 'all'): Report[] {
  const needle = query.trim().toLowerCase()
  return reports.filter(r => (kind === 'all' || reportKind(r) === kind)
    && (!needle || [r.title ?? '', r.name, r.source ?? ''].some(text => text.toLowerCase().includes(needle))))
}

/** Count of fleet-health reports per day for the last `days` days, oldest first; index `days - 1` is today. */
export function dailyFleetReports(reports: Report[], now: number, days = 7): number[] {
  const counts = new Array<number>(days).fill(0)
  for (const r of reports) {
    if (reportKind(r) !== 'fleet') continue
    const age = Math.floor((now - r.modified_at) / 86400)
    if (age >= 0 && age < days) counts[days - 1 - age]! += 1
  }
  return counts
}
