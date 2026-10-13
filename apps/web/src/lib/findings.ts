import type { ReportFinding } from '@/lib/operations'

/**
 * Collector sections that can become tasks. This mirrors the draft endpoint's match in apps/api/routes/operations.py:
 * only `## <id> - warn|crit (reason)` headings count, so report prose can never create a route.
 */
const SECTION = /^## ([a-z0-9][a-z0-9_-]{0,39}) - (warn|crit) \(([^\n]*)\)\n(.*?)(?=^## |(?![\s\S]))/gms

export function actionableFindings(content: string): ReportFinding[] {
  return [...content.matchAll(SECTION)].map(m => ({ id: m[1]!, status: m[2] as ReportFinding['status'], reason: m[3]!, evidence: m[4]!.trim() }))
}
