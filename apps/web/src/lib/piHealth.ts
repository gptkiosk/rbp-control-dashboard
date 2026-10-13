import type { MetricsCurrent, ThrottleFlag } from '@/lib/api'

export type FlagTone = 'ok' | 'warn' | 'danger' | 'muted'

export interface FlagStatus {
  tone: FlagTone
  /** Short state for a tile value: "None", "Active", "Since boot" or "Not reported". */
  value: string
  /** The conditions behind the state, e.g. "Frequency capped, Soft temperature limit". */
  detail: string
}

const LABELS: Record<ThrottleFlag, string> = {
  under_voltage: 'Under-voltage',
  frequency_capped: 'Frequency capped',
  throttled: 'Throttled',
  soft_temp_limit: 'Soft temperature limit',
  previously_under_voltage: 'Under-voltage',
  previously_frequency_capped: 'Frequency capped',
  previously_throttled: 'Throttled',
  previously_soft_temp_limit: 'Soft temperature limit',
}

const THROTTLE_ACTIVE: ThrottleFlag[] = ['throttled', 'frequency_capped', 'soft_temp_limit']
const THROTTLE_PAST: ThrottleFlag[] = ['previously_throttled', 'previously_frequency_capped', 'previously_soft_temp_limit']

function status(flags: ThrottleFlag[] | undefined, active: ThrottleFlag[], past: ThrottleFlag[]): FlagStatus {
  // vcgencmd is Raspberry Pi firmware; other hosts send no flags at all.
  if (flags === undefined) return { tone: 'muted', value: 'Not reported', detail: 'This host does not expose Pi firmware flags.' }
  const now = active.filter((f) => flags.includes(f))
  if (now.length) return { tone: 'danger', value: 'Active', detail: now.map((f) => LABELS[f]).join(', ') }
  const before = past.filter((f) => flags.includes(f))
  if (before.length) return { tone: 'warn', value: 'Since boot', detail: `${before.map((f) => LABELS[f]).join(', ')} since the last boot` }
  return { tone: 'ok', value: 'None', detail: 'No events since boot' }
}

/** Throttling: frequency caps, firmware throttling and the soft temperature limit. */
export function throttlingStatus(m: Pick<MetricsCurrent, 'throttle_flags'>): FlagStatus {
  return status(m.throttle_flags, THROTTLE_ACTIVE, THROTTLE_PAST)
}

/** Under-voltage, reported on its own because it points at the power supply, not heat. */
export function undervoltageStatus(m: Pick<MetricsCurrent, 'throttle_flags'>): FlagStatus {
  return status(m.throttle_flags, ['under_voltage'], ['previously_under_voltage'])
}
