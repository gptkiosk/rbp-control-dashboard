/** Vocabulary and small formatters shared by the MCP view and its dialogs. */
import type { AgentId, McpChange, McpChangeSpec, McpChangeStatus, McpServer } from './api'
import type { Tone } from './cards'

export const MCP_AGENTS: readonly { id: AgentId; label: string }[] = [
  { id: 'claude', label: 'Claude Code' },
  { id: 'codex', label: 'Codex' },
  { id: 'hermes', label: 'Hermes' },
  { id: 'openclaw', label: 'OpenClaw' },
]

export function mcpAgentLabel(id: string): string {
  return MCP_AGENTS.find((a) => a.id === id)?.label ?? id
}

/** ok when connected or enabled, warn when disabled, danger when failed, otherwise muted. */
export function serverStatusTone(status: string | null): Tone {
  if (!status) return 'muted'
  if (/failed/i.test(status)) return 'danger'
  if (/connected/i.test(status) || status === 'enabled') return 'ok'
  if (/disabled/i.test(status)) return 'warn'
  return 'muted'
}

export function isAccountConnector(s: Pick<McpServer, 'removable' | 'source'>): boolean {
  return !s.removable && /claude\.ai/i.test(s.source)
}

const CHANGE_TONES: Record<McpChangeStatus, Tone> = {
  pending: 'warn',
  applied: 'ok',
  failed: 'danger',
  rejected: 'muted',
}

export function changeTone(status: McpChangeStatus): Tone {
  return CHANGE_TONES[status] ?? 'muted'
}

export function changeStatusLabel(status: McpChangeStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1)
}

/** What the server will run or call: the command line for stdio, the address for http. */
export function specTarget(spec: McpChangeSpec): string | null {
  if (spec.transport === 'http' || (!spec.command && spec.url)) return spec.url
  const parts = [spec.command, ...(spec.args ?? [])].filter((p): p is string => !!p)
  return parts.length ? parts.join(' ') : null
}

/** One line for the confirm dialog: exactly what will be added or removed, and for which agent. */
export function describeChange(c: McpChange): string {
  const agent = mcpAgentLabel(c.agent)
  if (c.action === 'remove') {
    return `Remove the MCP server "${c.name}" from ${agent}'s configuration now?`
  }
  const target = specTarget(c.spec)
  const kind = c.spec.transport ?? 'unknown'
  const env = c.spec.env_names?.length ? `; environment variables: ${c.spec.env_names.join(', ')}` : ''
  return `Add the MCP server "${c.name}" (${kind}: ${target ?? 'no command or URL'}${env}) to ${agent}'s configuration now?`
}
