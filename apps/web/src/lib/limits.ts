export interface ProviderLimit {
  provider: string; name: string; detected_at: number; lift_at: number | null; seconds_left: number | null
  lift_label: string | null; rerouting: boolean; handoffs: number; rerouted: number; waiting: number
  alternate: string; alternate_name: string; alternate_limited: boolean; can_reroute: boolean
}
export interface LimitsPayload { active: ProviderLimit[]; now: number }

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** '4:00 PM', or 'Oct 14, 3:00 AM' on another day, in the viewer's own time zone. */
export function liftClock(lift: number, now: number): string {
  const d = new Date(lift * 1000), today = new Date(now * 1000)
  const clock = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return d.toDateString() === today.toDateString() ? clock : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${clock}`
}

export function remaining(seconds: number): string {
  if (seconds < 90) return 'under a minute'
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60), r = m % 60
  return r ? `${h} h ${r} m` : `${h} h`
}

/** One calm line about when it lifts. */
export function liftLine(l: ProviderLimit, now: number): string {
  if (l.lift_at === null) return `${l.name} limit reached. Resume time not reported.`
  if (l.lift_at <= now) return `${l.name} limit should have lifted.`
  return `${l.name} limit reached. Resets ${liftClock(l.lift_at, now)} (in ${remaining(l.lift_at - now)}).`
}

/** What already happened, only the parts that are non-zero. Empty when there is nothing to say. */
export function detailLine(l: ProviderLimit): string {
  const parts: string[] = []
  if (l.handoffs) parts.push(`${plural(l.handoffs, 'story', 'stories')} moved to ${l.alternate_name} on their own`)
  if (l.rerouted) parts.push(`${plural(l.rerouted, 'story', 'stories')} started on ${l.alternate_name}`)
  if (l.waiting && !l.rerouting) parts.push(`${l.waiting} waiting for ${l.name}`)
  return parts.length ? parts.join(' · ') + '.' : ''
}
