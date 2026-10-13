/** Board vocabulary, task filters and the one move-a-card routine shared by the list and the detail panel. */
import type { IconName } from '@/icons/icons'
import { patchJson, type AgentId, type AssigneeType, type Card, type CardColumn, type Priority, type RunStage } from './api'

export interface GroupDef {
  /** The API column name. */
  id: CardColumn
  /** Shown on the status pill, in caps. */
  label: string
  /** Sentence-case name for messages and the "Move to" menu. */
  name: string
  icon: IconName
  subtitle?: string
}

/** The six status groups, in the order they stack on screen. */
export const GROUPS: readonly GroupDef[] = [
  { id: 'running', label: 'IN PROGRESS', name: 'In progress', icon: 'run' },
  { id: 'review', label: 'NEEDS APPROVAL', name: 'Needs approval', icon: 'approval', subtitle: 'Waiting for your approval' },
  { id: 'queued', label: 'QUEUED', name: 'Queued', icon: 'clock' },
  { id: 'backlog', label: 'BACKLOG', name: 'Backlog', icon: 'tasks' },
  { id: 'failed', label: 'FAILED', name: 'Failed', icon: 'alert' },
  { id: 'done', label: 'DONE', name: 'Done', icon: 'check' },
]

/** Groups collapsed until the operator opens them. */
export const DEFAULT_COLLAPSED: readonly CardColumn[] = ['done']

export function columnLabel(id: CardColumn): string {
  return GROUPS.find((g) => g.id === id)?.name ?? id
}

export function isHuman(card: Pick<Card, 'assignee_type'>): boolean {
  return card.assignee_type === 'human'
}

/** Columns a card may be moved into by hand: the server refuses "running" for an agent task. */
export function movableColumns(card: Pick<Card, 'assignee_type'>): readonly GroupDef[] {
  return isHuman(card) ? GROUPS : GROUPS.filter((g) => g.id !== 'running')
}

/** A running agent task is owned by its run and cannot be dragged. */
export function canDrag(card: Pick<Card, 'assignee_type' | 'column'>): boolean {
  return isHuman(card) || card.column !== 'running'
}

/** True when dropping `card` on `column` is allowed (the server still has the last word). */
export function canMoveTo(card: Pick<Card, 'assignee_type' | 'column'>, column: CardColumn): boolean {
  return canDrag(card) && card.column !== column && (isHuman(card) || column !== 'running')
}

const AGENT_LABELS: Record<AgentId, string> = {
  claude: 'Claude',
  codex: 'Codex',
  hermes: 'Hermes',
  openclaw: 'OpenClaw',
}

export const AGENT_IDS: readonly AgentId[] = ['claude', 'codex', 'hermes', 'openclaw']

export function agentLabel(id: string | null | undefined): string {
  if (!id) return '—'
  return AGENT_LABELS[id as AgentId] ?? id
}

export function isManagerAgent(id: string | null | undefined): boolean {
  return id === 'hermes'
}

export type Tone = 'ok' | 'warn' | 'danger' | 'muted' | 'accent'

const STAGE_TONES: Record<RunStage, Tone> = {
  running: 'accent',
  succeeded: 'ok',
  failed: 'danger',
  timeout: 'danger',
  cancelled: 'warn',
  interrupted: 'warn',
  awaiting_approval: 'warn',
}

export function stageTone(stage: RunStage): Tone {
  return STAGE_TONES[stage] ?? 'muted'
}

export function stageLabel(stage: RunStage): string {
  if (stage === 'timeout') return 'Timed out'
  if (stage === 'awaiting_approval') return 'Awaiting output approval'
  return stage.charAt(0).toUpperCase() + stage.slice(1)
}

/** True while the card is waiting on an approval nobody has given yet. */
export function awaitsApproval(card: Pick<Card, 'needs_approval' | 'approved_at'>): boolean {
  return card.needs_approval && !card.approved_at
}

export function approvalNotice(card: Pick<Card, 'approval_reasons'>): string {
  const reasons = card.approval_reasons.filter(Boolean)
  return reasons.length ? `Needs your approval: ${reasons.join('; ')}` : 'Needs your approval before it can run.'
}

// ---- priority, estimates, due dates ----

export const PRIORITIES: readonly { id: Priority; label: string }[] = [
  { id: 'urgent', label: 'Urgent' },
  { id: 'high', label: 'High' },
  { id: 'normal', label: 'Normal' },
  { id: 'low', label: 'Low' },
]

export function priorityLabel(p: Priority | null | undefined): string {
  return PRIORITIES.find((x) => x.id === p)?.label ?? '—'
}

export const PRIORITY_TONES: Record<Priority, Tone> = { urgent: 'danger', high: 'warn', normal: 'accent', low: 'muted' }

/** Local calendar date as YYYY-MM-DD. */
export function todayIso(now: Date = new Date()): string {
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${mm}-${dd}`
}

/** Past its due date and not Done. */
export function isOverdue(card: Pick<Card, 'due_date' | 'column'>, today: string = todayIso()): boolean {
  return !!card.due_date && card.column !== 'done' && card.due_date < today
}

export function isBlocked(card: Pick<Card, 'blocked_by'>): boolean {
  return (card.blocked_by?.length ?? 0) > 0
}

export function idList(ids: readonly number[]): string {
  return ids.map((n) => `#${n}`).join(', ')
}

export type EstimateUnit = 'minutes' | 'hours'

/** "1.5" hours -> 90. Null for blank; NaN for anything that is not a positive number. */
export function estimateToMinutes(value: string, unit: EstimateUnit): number | null {
  const text = value.trim()
  if (text === '') return null
  const n = Number(text)
  if (!Number.isFinite(n) || n <= 0) return Number.NaN
  return Math.round(unit === 'hours' ? n * 60 : n)
}

/** Stored minutes -> the value and unit the form shows (whole hours as hours). */
export function estimateForForm(minutes: number | null | undefined): { value: string; unit: EstimateUnit } {
  if (minutes == null) return { value: '', unit: 'hours' }
  return minutes % 60 === 0 ? { value: String(minutes / 60), unit: 'hours' } : { value: String(minutes), unit: 'minutes' }
}

/** Mirrors the server's tag rule closely enough to give instant feedback; the server still has the last word. */
export function normalizeTag(raw: string): string {
  return raw.trim().replace(/\s+/g, ' ').toLowerCase().slice(0, 32)
}

export const MAX_TAGS = 10

// ---- grouping ----

/** Cards grouped into every column (empty ones included), each ordered by position then id. */
export function groupCards(cards: readonly Card[]): Record<CardColumn, Card[]> {
  const out = Object.fromEntries(GROUPS.map((g) => [g.id, [] as Card[]])) as Record<CardColumn, Card[]>
  for (const card of cards) {
    // Surface a ready operator gate without changing its persisted state or prerequisites.
    const readyDecision = card.project?.role === 'story' && isHuman(card) && card.column === 'backlog' && !isBlocked(card)
    ;(out[readyDecision ? 'review' : card.column] ?? out.backlog).push(card)
  }
  for (const list of Object.values(out)) list.sort((a, b) => a.position - b.position || a.id - b.id)
  return out
}

// ---- filters ----

export interface TaskFilters {
  search: string
  agents: string[]
  assignees: AssigneeType[]
  tags: string[]
  priorities: Priority[]
  createdBy: string[]
  blockedOnly: boolean
  overdueOnly: boolean
}

export function emptyFilters(): TaskFilters {
  return { search: '', agents: [], assignees: [], tags: [], priorities: [], createdBy: [], blockedOnly: false, overdueOnly: false }
}

export function filtersActive(f: TaskFilters): boolean {
  return (
    f.search.trim() !== '' ||
    f.agents.length > 0 ||
    f.assignees.length > 0 ||
    f.tags.length > 0 ||
    f.priorities.length > 0 ||
    f.createdBy.length > 0 ||
    f.blockedOnly ||
    f.overdueOnly
  )
}

/** Does `card` pass every active filter? Within one filter the choices are alternatives (any of). */
export function matchesFilters(card: Card, f: TaskFilters, today: string = todayIso()): boolean {
  const q = f.search.trim().toLowerCase()
  if (q) {
    const hay = [card.title, card.body ?? '', `#${card.id}`, ...(card.tags ?? [])].join('\n').toLowerCase()
    if (!hay.includes(q)) return false
  }
  if (f.agents.length && !(card.agent && f.agents.includes(card.agent))) return false
  if (f.assignees.length && !f.assignees.includes(card.assignee_type)) return false
  if (f.tags.length && !(card.tags ?? []).some((t) => f.tags.includes(t))) return false
  if (f.priorities.length && !f.priorities.includes(card.priority)) return false
  if (f.createdBy.length && !f.createdBy.includes(card.created_by)) return false
  if (f.blockedOnly && !isBlocked(card)) return false
  if (f.overdueOnly && !isOverdue(card, today)) return false
  return true
}

export interface MoveResult {
  card: Card
  /** Set when the server put the card somewhere other than where it was sent. */
  notice: string | null
}

/**
 * PATCH a card into `column`. Throws ApiError on 409/422. When the server lands it elsewhere
 * (a card needing approval goes to review instead of queued) `notice` explains why.
 */
export async function moveCard(id: number, column: CardColumn): Promise<MoveResult> {
  const card = await patchJson<Card>(`/api/cards/${id}`, { column })
  let notice: string | null = null
  if (card.column !== column) {
    notice =
      card.column === 'review' || awaitsApproval(card)
        ? approvalNotice(card)
        : `Card landed in ${columnLabel(card.column)} instead of ${columnLabel(column)}.`
  }
  return { card, notice }
}
