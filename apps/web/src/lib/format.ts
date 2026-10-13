/** Display formatters. Every one returns "—" for null, undefined or non-finite input. */

export const DASH = '—'

type Maybe = number | null | undefined

function isNum(v: Maybe): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** One decimal under 100, none from 100 up ("12.7", "432"). */
function trimmed(v: number): string {
  return v >= 100 ? v.toFixed(0) : v.toFixed(1)
}

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

/** Binary units (1 KB = 1024 B): 13_650_000_000 -> "12.7 GB". */
export function formatBytes(bytes: Maybe): string {
  if (!isNum(bytes)) return DASH
  let v = Math.abs(bytes)
  let i = 0
  while (v >= 1024 && i < BYTE_UNITS.length - 1) {
    v /= 1024
    i++
  }
  const sign = bytes < 0 ? '-' : ''
  return `${sign}${i === 0 ? Math.round(v).toString() : trimmed(v)} ${BYTE_UNITS[i]}`
}

/** Bytes per second -> "432 KB/s". */
export function formatRate(bps: Maybe): string {
  const b = formatBytes(bps)
  return b === DASH ? DASH : `${b}/s`
}

/** Bytes -> gigabytes with one decimal ("12.7 GB"), for chart axes. */
export function formatGB(bytes: Maybe): string {
  if (!isNum(bytes)) return DASH
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

/** Bytes per second -> KB/s with no decimals ("432 KB/s"), for chart axes. */
export function formatKBps(bps: Maybe): string {
  if (!isNum(bps)) return DASH
  return `${(bps / 1024).toFixed(0)} KB/s`
}

export function formatPct(pct: Maybe, digits = 1): string {
  if (!isNum(pct)) return DASH
  return `${pct.toFixed(digits)}%`
}

export function formatTemp(c: Maybe): string {
  if (!isNum(c)) return DASH
  return `${c.toFixed(1)} °C`
}

export function formatWatts(w: Maybe): string {
  if (!isNum(w)) return DASH
  return `${w.toFixed(1)} W`
}

export function formatRpm(rpm: Maybe): string {
  if (!isNum(rpm)) return DASH
  return `${Math.round(rpm)} rpm`
}

/** Seconds -> "4 s ago", "3 min ago", "2 h ago", "5 d ago". */
export function formatAge(seconds: Maybe): string {
  if (!isNum(seconds)) return DASH
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s} s ago`
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

/** Shown (muted) where the API has no value: a missing metric is never displayed as 0 or blank. */
export const NOT_REPORTED = 'not reported'

/** Seconds -> "3.7 s", "45 s", "2 min 5 s", "1 h 3 min". */
export function formatDuration(seconds: Maybe): string {
  if (!isNum(seconds)) return DASH
  const s = Math.max(0, seconds)
  if (s < 10) return `${s.toFixed(1)} s`
  if (s < 60) return `${Math.round(s)} s`
  const whole = Math.floor(s)
  if (whole < 3600) return `${Math.floor(whole / 60)} min ${whole % 60} s`
  return `${Math.floor(whole / 3600)} h ${Math.floor((whole % 3600) / 60)} min`
}

/** Whole numbers with thousands separators ("14,964"). */
export function formatCount(n: Maybe): string {
  if (!isNum(n)) return DASH
  return Math.round(n).toLocaleString('en-US')
}

/** US dollars with a fixed number of decimals ("$0.0123"). */
export function formatUsd(usd: Maybe, digits = 4): string {
  if (!isNum(usd)) return DASH
  return `$${usd.toFixed(digits)}`
}

/** Epoch seconds -> "3 min ago" relative to `nowS` (epoch seconds, default: the current time). */
export function formatSince(epochS: Maybe, nowS: number = Date.now() / 1000): string {
  if (!isNum(epochS)) return DASH
  return formatAge(nowS - epochS)
}

/** Minutes -> "20m", "40h", "1h 30m". */
export function formatEstimate(minutes: Maybe): string {
  if (!isNum(minutes) || minutes < 0) return DASH
  const m = Math.round(minutes)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return m % 60 === 0 ? `${h}h` : `${h}h ${m % 60}m`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "YYYY-MM-DD" -> "Oct 12" (with the year when it is not `now`'s year). Anything else is "—". */
export function formatDueDate(iso: string | null | undefined, now: Date = new Date()): string {
  const m = typeof iso === 'string' ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso) : null
  if (!m) return DASH
  const month = MONTHS[Number(m[2]) - 1]
  if (!month) return DASH
  const day = Number(m[3])
  return Number(m[1]) === now.getFullYear() ? `${month} ${day}` : `${month} ${day}, ${m[1]}`
}

/** A model id cut down to what tells models apart: "openrouter/thinkingmachines/inkling:free" becomes
 *  "inkling · free" and "claude-opus-5-5" stays as it is. Falls back to the full id when nothing is left. */
export function formatModelShort(id: string | null | undefined): string {
  const full = (id ?? '').trim()
  if (!full) return DASH
  const [path, ...tags] = full.split(':')
  const name = path.split('/').pop() || path
  const tag = tags.join(':')
  return tag ? `${name} \u00b7 ${tag}` : name
}

/** "no price for a, b +2 more" for the models used without a recorded price; empty when none are named. */
export function unpricedModels(models: string[] | null | undefined, show = 2): string {
  if (!models?.length) return ''
  const rest = models.length - show
  return `no price for ${models.slice(0, show).join(', ')}${rest > 0 ? ` +${rest} more` : ''}`
}

export const UNPRICED_HINT = 'A model was used that the price catalog has no price for. Update the catalog: scripts/pricing/check.py --used'
