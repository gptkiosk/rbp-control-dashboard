import { computed, onMounted, ref, watch, type Ref } from 'vue'
import { getJson, type Card } from '@/lib/api'

export interface MediaSummary { published: number; skipped: number; pending: number; total: number; complete: boolean; text: string }
export interface MediaCost { remaining_usd: number; remaining_items: number; unpriced: number; spent_usd: number; spent_runs: number }
export interface ProjectMedia { available: boolean; error?: string | null; summary?: MediaSummary; cost?: MediaCost }

const usd = (v: number) => `about $${v.toFixed(2)}`
/** The money, in plain words: what is left to make and what has been spent. Estimates only; fal's invoice is the truth. */
export function costWords(cost: MediaCost | undefined): { left: string; spent: string; short: string; leftValue: string; spentValue: string } {
  if (!cost) return { left: '', spent: '', short: '', leftValue: '', spentValue: '' }
  const left = cost.remaining_items === 0 ? 'nothing left to make'
    : `${usd(cost.remaining_usd)} left to make (${cost.remaining_items} ${cost.remaining_items === 1 ? 'item' : 'items'}${cost.unpriced ? `, ${cost.unpriced} with no listed price` : ''})`
  const short = cost.remaining_items === 0 ? 'nothing left to make' : `${usd(cost.remaining_usd)} left${cost.unpriced ? ' + unpriced' : ''}`
  const leftValue = cost.remaining_items === 0 ? 'nothing left' : `${usd(cost.remaining_usd)} · ${cost.remaining_items} ${cost.remaining_items === 1 ? 'item' : 'items'}${cost.unpriced ? ` (${cost.unpriced} unpriced)` : ''}`
  return { leftValue, spentValue: cost.spent_runs ? usd(cost.spent_usd) : 'nothing yet', left, spent: cost.spent_runs ? `${usd(cost.spent_usd)} spent so far` : 'nothing spent yet', short }
}

/** Where a human media story's project stands in the media studio: slots, cost, and the link to open it. Only human stories about media of a project with media slots. */
export function useProjectMedia(card: Ref<Card | null> | (() => Card | null)) {
  const get = () => (typeof card === 'function' ? card() : card.value)
  const media = ref<ProjectMedia | null>(null)
  const isMediaStory = computed(() => /\b(media|stills?|clips?|video|illustrations?|art|images?)\b/i.test(`${get()?.title ?? ''} ${get()?.body || ''}`))
  const link = computed(() => (get()?.project ? `/projects?project=${get()!.project!.id}&view=media` : ''))
  async function load() {
    media.value = null
    const c = get()
    if (!c || !c.project || c.assignee_type !== 'human' || !isMediaStory.value) return
    try { media.value = await getJson<ProjectMedia>(`/api/media/project/${c.project.id}`) } catch { media.value = null }
  }
  onMounted(() => { void load() })
  watch(() => get()?.id, () => { void load() })
  return { media, link, isMediaStory, load }
}
