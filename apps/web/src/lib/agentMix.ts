/** The dashboard runs with any mix of agents installed. Readiness never asks for a particular one. */
export type Availability = (id: string) => boolean | undefined

/** Agents sold as a flat-fee plan; any one of them is enough for subscription work. */
export const SUBSCRIPTION_CLIS = ['claude', 'codex', 'grok'] as const
/** The managing and free-model agents; either is enough for native routes. */
export const NATIVE_AGENTS = ['hermes', 'openclaw'] as const

export function anyInstalled(available: Availability, ids: readonly string[]): boolean {
  return ids.some((id) => available(id) === true)
}

/** The agents of a family that are installed, in the order given, for choosing a sensible default. */
export function firstInstalled(available: Availability, order: readonly string[]): string | undefined {
  return order.find((id) => available(id) === true)
}
