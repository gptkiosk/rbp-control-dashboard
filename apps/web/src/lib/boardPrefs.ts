/** Per-browser memory for the Tasks list: collapsed groups, hidden lanes and filters. Never throws. */
import type { AssigneeType, CardColumn, Priority } from './api'
import { DEFAULT_COLLAPSED, GROUPS, emptyFilters, type TaskFilters } from './cards'

export const PREFS_KEY = 'mcd.tasks.board.v1'

export interface BoardPrefs {
  collapsed: CardColumn[]
  hidden: CardColumn[]
  filters: TaskFilters
}

export function defaultPrefs(): BoardPrefs {
  return { collapsed: [...DEFAULT_COLLAPSED], hidden: [], filters: emptyFilters() }
}

/** The storage object, or null where the browser refuses it (private mode, blocked site data). */
function store(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

const GROUP_IDS = new Set<string>(GROUPS.map((g) => g.id))
const ASSIGNEES = new Set<string>(['agent', 'human'])
const PRIORITY_IDS = new Set<string>(['urgent', 'high', 'normal', 'low'])

function strings(v: unknown, allowed?: Set<string>): string[] {
  if (!Array.isArray(v)) return []
  return v.filter((x): x is string => typeof x === 'string' && (!allowed || allowed.has(x)))
}

export function loadPrefs(): BoardPrefs {
  const prefs = defaultPrefs()
  try {
    const raw = store()?.getItem(PREFS_KEY)
    if (!raw) return prefs
    const data = JSON.parse(raw) as Record<string, unknown>
    if (Array.isArray(data.collapsed)) prefs.collapsed = strings(data.collapsed, GROUP_IDS) as CardColumn[]
    prefs.hidden = strings(data.hidden, GROUP_IDS) as CardColumn[]
    const f = (data.filters && typeof data.filters === 'object' ? data.filters : {}) as Record<string, unknown>
    prefs.filters = {
      search: typeof f.search === 'string' ? f.search : '',
      agents: strings(f.agents),
      assignees: strings(f.assignees, ASSIGNEES) as AssigneeType[],
      tags: strings(f.tags),
      priorities: strings(f.priorities, PRIORITY_IDS) as Priority[],
      createdBy: strings(f.createdBy),
      blockedOnly: f.blockedOnly === true,
      overdueOnly: f.overdueOnly === true,
    }
  } catch {
    /* unreadable or unavailable: start from the defaults */
  }
  return prefs
}

export function savePrefs(prefs: BoardPrefs): void {
  try {
    store()?.setItem(PREFS_KEY, JSON.stringify(prefs))
  } catch {
    /* the board works without persistence */
  }
}
