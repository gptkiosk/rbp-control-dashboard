import type { ReleaseEnvelope } from '@/lib/api'

const SHORT = 7

/**
 * Build the footer release label, e.g. "v0.1.0 • local • api b2bf245 • web 4594185".
 *
 * Both SHAs are shown whenever the web build knows its own, even when they are
 * equal. The api and the web bundle are built and rolled separately, so a
 * half-finished deploy leaves them on different commits; always printing both
 * makes that visible at a glance, and two matching values read as an explicit
 * "both halves are current" rather than leaving the viewer to guess whether the
 * web SHA was simply left out.
 */
export function releaseLabel(
  release: Pick<ReleaseEnvelope, 'version' | 'environment' | 'commit_sha' | 'has_migrations'> | null | undefined,
  webCommitSha: string | null | undefined,
): string {
  if (!release) return ''

  const apiSha = release.commit_sha
  const apiShort = !apiSha || apiSha === 'unknown' ? 'unknown' : apiSha.slice(0, SHORT)
  const webShort = (webCommitSha ?? '').trim().slice(0, SHORT)

  const segment = webShort === '' ? apiShort : `api ${apiShort} · web ${webShort}`
  return `v${release.version} • ${release.environment} • ${segment}${release.has_migrations ? ' • migrations' : ''}`
}
