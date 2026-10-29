<script setup lang="ts">
import NoteFold from '@/components/NoteFold.vue'
import MediaPlanForm from '@/components/MediaPlanForm.vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getJson, postJson, patchJson } from '@/lib/api'
interface Plan { endpoint: string; estimate_usd: number | null }
interface Slot { plan_sha256?: string; width?: number; height?: number; resolution?: string | null; seconds?: number[] | null; name: string; kind: 'image' | 'video'; world: string | null; purpose: string; prompt: string; published: boolean; unreviewed?: number; published_bytes?: number; skipped?: boolean; history?: { ts: number; event: string; detail: string }[]; inbox?: string | null; candidates: string[]; waiting_for_stills: string[]; plans: Record<Tier, Plan> }
interface Storage { published_bytes: number; unused_bytes: number; unused_count: number }
interface Summary { published: number; skipped: number; pending: number; total: number; complete: boolean; text: string }
interface Job { id: string; state: 'queued' | 'running' | 'done' | 'failed'; progress: string; slot: string; error: string | null; files: { path: string; bytes: number }[] }
type Tier = 'draft' | 'standard' | 'premium'
// An omitted boolean prop would be read as false; undefined means "look it up yourself".
const props = withDefaults(defineProps<{ keySaved?: boolean; workingDir?: string }>(), { keySaved: undefined, workingDir: undefined })
const editing = ref<string | null>(null), savingPlan = ref(false)
const editPlan = ref({ prompt:'', purpose:'', world:'', width:1920, height:1080, resolution:'', minSeconds:4, maxSeconds:8 })
function openPlan(s: Slot) {
  editing.value=s.name
  editPlan.value={prompt:s.prompt,purpose:s.purpose,world:s.world || '',width:s.width || 1920,height:s.height || 1080,resolution:s.resolution || '',minSeconds:s.seconds?.[0] || 4,maxSeconds:s.seconds?.[1] || 8}
}
async function savePlan(s: Slot) {
  if (!s.plan_sha256 || savingPlan.value || busy.value) return
  savingPlan.value=true;error.value=''
  try {
    const {resolution,minSeconds,maxSeconds,...fields}=editPlan.value
    await patchJson('/api/media/slots',{working_dir:folder.value,slot:s.name,expected_sha256:s.plan_sha256,...(s.published ? {revise_published:true} : {}),...fields,resolution:resolution || null,...(s.kind==='video' ? {seconds:[minSeconds,maxSeconds]} : {})})
    editing.value=null;confirm.value=false
    note.value[s.name]={ok:true,text:'Asset plan saved. Review refreshed estimates and confirm spending again before generation.'}
    await loadSlots()
  } catch(e) { error.value=e instanceof Error ? e.message : String(e) }
  finally {savingPlan.value=false}
}
const keyOk = ref(props.keySaved ?? false)
const summary = ref<Summary | null>(null)
const cost = ref<{ spent_usd: number; spent_runs: number } | null>(null)
const storage = ref<Storage | null>(null)
const folders = ref<{ path: string; name: string }[]>([])
const folder = ref('')
const slots = ref<Slot[]>([])
const tier = ref<Record<string, Tier>>({}), count = ref<Record<string, number>>({}), more = ref<Record<string, boolean>>({})
const jobs = ref<Job[]>([])
const confirm = ref(false), error = ref(''), busy = ref(false)
// Feedback belongs beside the button that was pressed, not at the bottom of a long panel.
const note = ref<Record<string, { ok: boolean; text: string }>>({}), working = ref<Record<string, boolean>>({})
const ledger = ref<{ runs: number; done: number; estimated_usd: number; unpriced: number; repeats: number; repeat_usd: number; note: string } | null>(null)
// A slot that already has generations waiting for review is not paid for again unless the operator says so outright.
const offerTake = ref<Record<string, boolean>>({})
let timer: ReturnType<typeof setInterval> | undefined
const money = (v: number | null) => (v === null ? 'price not listed' : `about $${v.toFixed(2)}`)
async function loadFolders() {
  if (props.workingDir) { folder.value = props.workingDir; await loadSlots(); return }       // opened from a project: its folder is already chosen
  try { folders.value = (await getJson<{ folders: { path: string; name: string }[] }>('/api/media/folders')).folders; if (folders.value.length === 1) { folder.value = folders.value[0]!.path; await loadSlots() } } catch (e) { error.value = String(e instanceof Error ? e.message : e) } }
async function loadSlots() {
  if (!folder.value) { slots.value = []; return }
  try {
    const data = await getJson<{ slots: Slot[]; summary?: Summary; default_tiers?: Partial<Record<'image' | 'video', Tier>> }>(`/api/media/slots?working_dir=${encodeURIComponent(folder.value)}`)
    slots.value = data.slots
    summary.value = data.summary ?? null
    cost.value = (data as { cost?: { spent_usd: number; spent_runs: number } }).cost ?? null
    storage.value = (data as { storage?: Storage }).storage ?? null
    for (const s of data.slots) { tier.value[s.name] ||= data.default_tiers?.[s.kind] || 'standard'; count.value[s.name] ||= 1 }
  } catch (e) { error.value = e instanceof Error ? e.message : String(e); slots.value = [] }
}
async function loadLedger() { try { ledger.value = await getJson('/api/media/ledger') } catch { ledger.value = null } }
// Three states, so a finished slot is out of the way: published, candidates waiting for your decision, and not made yet.
// A published slot you regenerated is also waiting: its new takes replace the published file only when you accept one.
const published = computed(() => slots.value.filter(s => s.published))
const skipped = computed(() => slots.value.filter(s => !s.published && s.skipped))
const review = computed(() => slots.value.filter(s => !s.skipped && s.candidates.length > 0 && (!s.published || (s.unreviewed ?? 0) > 0)))
const todo = computed(() => slots.value.filter(s => !s.published && !s.skipped && s.candidates.length === 0))
const eligible = computed(() => todo.value.filter(s => s.waiting_for_stills.length === 0))
const stillWaiting = computed(() => todo.value.filter(s => s.waiting_for_stills.length > 0).length)
// 'each' uses the tier already chosen on every slot (a website's background clips start on the cheapest video tier); a named tier overrides all of them.
const batchTier = ref<Tier | 'each'>('each')
const tierFor = (s: Slot): Tier => (batchTier.value === 'each' ? (tier.value[s.name] || 'standard') : batchTier.value)
const batch = computed(() => {
  let total = 0, unknown = 0
  for (const s of eligible.value) { const e = s.plans[tierFor(s)].estimate_usd; if (e === null) unknown++; else total += e }
  return { total, unknown }
})
// The money, at a glance: what is already spent (the ledger's estimates for this folder) and what the slots not yet made would cost at the tiers chosen now.
const left = computed(() => {
  let total = 0, unknown = 0
  for (const s of todo.value) { const e = s.plans[tier.value[s.name] || 'standard'].estimate_usd; if (e === null) unknown++; else total += e * (count.value[s.name] || 1) }
  return { total, unknown }
})
const leftLine = computed(() => todo.value.length === 0 ? 'nothing left' : `about $${left.value.total.toFixed(2)}${left.value.unknown ? ` + ${left.value.unknown} unpriced` : ''}`)
const spentLine = computed(() => cost.value && cost.value.spent_runs ? `about $${cost.value.spent_usd.toFixed(2)}` : 'nothing yet')
const clearNote = ref('')
const jobsFor = (slot: string) => jobs.value.filter(j => j.slot === slot)
const activeFor = (slot: string) => jobs.value.some(j => j.slot === slot && (j.state === 'queued' || j.state === 'running'))
function jobLine(j: Job, n: number, of: number) {
  const take = of > 1 ? `Take ${n} of ${of}: ` : ''
  if (j.state === 'failed') return `${take}failed. ${j.error || 'Nothing was saved.'}`
  if (j.state === 'done') return `${take}finished. It is waiting for your decision.`
  return `${take}${j.state === 'queued' ? 'waiting to start' : 'generating'}${j.progress ? ` (${j.progress})` : ''}. About a minute for a picture, a few for a clip.`
}
const unfinished = computed(() => jobs.value.filter(j => j.state === 'queued' || j.state === 'running').length)
function queue(slot: string, ids: string[]) { for (const id of ids) jobs.value.push({ id, state: 'queued', progress: '', slot, error: null, files: [] }) }
const confirmBox = ref<HTMLInputElement | null>(null)
const CONFIRM_HINT = 'Tick "I understand each run spends from my fal account" at the top of this section first.'
// A button that does nothing is the worst answer. Without the acknowledgement it says why and takes you to the box.
function needConfirm(slot?: string) {
  if (slot) note.value[slot] = { ok: false, text: CONFIRM_HINT } ; else error.value = CONFIRM_HINT
  confirmBox.value?.scrollIntoView?.({ block: 'center' }); confirmBox.value?.focus()
}
async function generateAll() {
  if (busy.value || savingPlan.value || editing.value || !eligible.value.length) return
  if (!confirm.value) { needConfirm(); return }
  const n = eligible.value.length, tierName = batchTier.value === 'each' ? 'chosen' : batchTier.value
  const price = batch.value.unknown ? `about $${batch.value.total.toFixed(2)} plus ${batch.value.unknown} with no listed price` : `about $${batch.value.total.toFixed(2)}`
  if (!window.confirm(`Generate ${n} item${n === 1 ? '' : 's'} at the ${tierName} tier? Estimated cost ${price}. This spends from your fal account and cannot be undone; fal's invoice is the truth.`)) return
  busy.value = true; error.value = ''
  try {
    for (const s of eligible.value) queue(s.name, (await postJson<{ jobs: string[] }>('/api/media/generate', { working_dir: folder.value, slot: s.name, tier: tierFor(s), count: 1, confirm_spend: true, expected_sha256:s.plan_sha256 })).jobs)
    poll()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e); if (jobs.value.length) poll() } finally { busy.value = false }
}
const publishedUrl = (name: string) => `/api/media/published?working_dir=${encodeURIComponent(folder.value)}&name=${encodeURIComponent(name)}`
const bytes = (n: number) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`
async function clearUnused() {
  const st = storage.value
  if (!st || !st.unused_count || busy.value) return
  if (!window.confirm(`Delete ${st.unused_count} unused take${st.unused_count === 1 ? '' : 's'} (${bytes(st.unused_bytes)})? Published media and takes waiting for your decision are kept. This cannot be undone, and they cost money to make.`)) return
  busy.value = true; error.value = ''
  try {
    const r = await postJson<{ deleted: number; freed_bytes: number }>('/api/media/clear-unused', { working_dir: folder.value, confirm: true })
    clearNote.value = `Deleted ${r.deleted} unused take${r.deleted === 1 ? '' : 's'}, freeing ${bytes(r.freed_bytes)}.`
    await loadSlots()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
const candidateUrl = (name: string) => `/api/media/candidate?working_dir=${encodeURIComponent(folder.value)}&name=${encodeURIComponent(name)}`
const isVideo = (name: string) => /\.(mp4|webm)$/i.test(name)
function estimate(s: Slot) { const e = s.plans[tier.value[s.name] || 'standard'].estimate_usd; return e === null ? null : e * (count.value[s.name] || 1) }
async function generate(s: Slot, anotherTake = false, regenerate = false) {
  if (busy.value || savingPlan.value || editing.value) return
  if (!confirm.value) { needConfirm(s.name); return }
  const n = count.value[s.name] || 1, price = money(estimate(s))
  if (!window.confirm(`Generate ${n} for ${s.name} at the ${tier.value[s.name] || 'standard'} tier? Estimated cost ${price}. This spends from your fal account.`)) return
  busy.value = true; offerTake.value[s.name] = false
  note.value[s.name] = { ok: true, text: 'Requested. It appears here when fal finishes (about a minute for an image, a few for a clip).' }
  try {
    queue(s.name, (await postJson<{ jobs: string[] }>('/api/media/generate', { working_dir: folder.value, slot: s.name, tier: tier.value[s.name] || 'standard', count: n, confirm_spend: true, expected_sha256:s.plan_sha256, ...(anotherTake ? { another_take: true } : {}), ...(regenerate || s.published ? { regenerate: true } : {}) })).jobs)
    more.value[s.name] = false
    poll()
  } catch (e) {
    const text = e instanceof Error ? e.message : String(e)
    offerTake.value[s.name] = /Another take/.test(text)
    note.value[s.name] = { ok: false, text }
  } finally { busy.value = false }
}
async function refreshJobs() {
  let changed = false
  for (const j of jobs.value) {
    if (j.state === 'done' || j.state === 'failed') continue
    try { Object.assign(j, await getJson<Job>(`/api/media/jobs/${j.id}`)) } catch { j.state = 'failed'; j.error = 'MCD no longer knows this job; check the ledger.' }
    const after = (j as Job).state
    if (after === 'done' || after === 'failed') {
      changed = true
      if (after === 'failed') note.value[j.slot] = { ok: false, text: j.error || 'Generation failed.' }
    }
  }
  if (changed) await loadSlots()                                  // each result appears as soon as it is ready, not when the whole batch ends
  if (!unfinished.value) { clearInterval(timer); timer = undefined; await loadSlots(); await loadLedger() }
}
function poll() { if (!timer) timer = setInterval(() => void refreshJobs(), 3000) }
async function decide(s: Slot, event: 'skip' | 'unskip' | 'reject') {
  working.value[s.name] = true
  try {
    await postJson('/api/media/decision', { working_dir: folder.value, slot: s.name, event })
    if (event === 'reject') more.value[s.name] = true
    note.value[s.name] = { ok: true, text: event === 'skip' ? 'Skipped: the site ships on its fallback for this slot.' : event === 'unskip' ? 'Restored.' : 'Noted: none of these. Make another below.' }
    await loadSlots()
  } catch (e) { note.value[s.name] = { ok: false, text: e instanceof Error ? e.message : String(e) } } finally { working.value[s.name] = false }
}
const lastEvent = (s: Slot) => { const h = s.history?.[s.history.length - 1]; return h ? `${h.event}${h.detail ? ': ' + h.detail : ''}` : '' }
async function accept(s: Slot, candidate: string) {
  working.value[s.name] = true
  note.value[s.name] = { ok: true, text: `Accepting ${candidate}…` }
  try {
    await postJson('/api/media/pick', { working_dir: folder.value, slot: s.name, candidate })
    const r = await postJson<{ files: { path: string; bytes: number }[]; refreshed?: string[]; stale?: string[] }>('/api/media/publish', { working_dir: folder.value, slot: s.name })
    const copies = r.refreshed?.length ? ` Re-made the site's copies: ${r.refreshed.join(', ')}.` : ''
    const stale = r.stale?.length ? ` These copies still show the previous picture and need a story to rebuild them: ${r.stale.join(', ')}.` : ''
    note.value[s.name] = { ok: !stale, text: `Published: ${r.files.map(f => `${f.path} (${Math.max(1, Math.round(f.bytes / 1024))} KB)`).join(', ')}.${copies}${stale}` }
    await loadSlots(); await loadLedger()
  } catch (e) { note.value[s.name] = { ok: false, text: e instanceof Error ? e.message : String(e) } } finally { working.value[s.name] = false }
}
onMounted(async () => {
  void loadFolders(); void loadLedger()
  if (props.keySaved === undefined) { try { keyOk.value = !!(await getJson<{ fal_key_saved: boolean }>('/api/media/models')).fal_key_saved } catch { keyOk.value = false } }
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>
<template>
  <section class="media-gen" aria-labelledby="media-gen-title">
    <h3 id="media-gen-title">Media studio</h3>
    <p class="muted small">Make, preview and publish site art and video. Each run spends from your fal account, and nothing starts until you confirm.</p>
    <div v-if="slots.length" class="cost-strip" data-testid="cost-strip" role="group" aria-label="Media cost">
      <div><span class="k">Spent so far</span><strong>{{ spentLine }}</strong><small>estimate from finished runs</small></div>
      <div><span class="k">Left to make</span><strong>{{ leftLine }}</strong><small>{{ todo.length }} {{ todo.length === 1 ? 'item' : 'items' }} at the chosen tiers</small></div>
      <div><span class="k">To review</span><strong>{{ review.length }}</strong><small>waiting for your decision</small></div>
    </div>
    <div v-if="storage && slots.length" class="storage" data-testid="storage">
      <span class="small"><strong>Storage</strong> · published {{ bytes(storage.published_bytes) }} · unused takes {{ storage.unused_count ? `${bytes(storage.unused_bytes)} in ${storage.unused_count} file${storage.unused_count === 1 ? '' : 's'}` : 'none' }}</span>
      <button v-if="storage.unused_count" type="button" class="btn small-btn" :disabled="busy" data-testid="clear-unused" @click="clearUnused">Clear unused takes…</button>
      <span v-if="clearNote" class="ok-text small" role="status">{{ clearNote }}</span>
    </div>
    <NoteFold label="How media is made"><p class="muted small">
      MCD makes the call with your saved key, which never reaches an agent or the project folder. The folder's <code>media/slots.json</code> only supplies prompts and file names; no code from it is run.
      Make it, look at it, <strong>Accept</strong> the one you like, and it is published into the site. Published items stay out of the way.
    </p></NoteFold>
    <div v-if="!keyOk" class="key-needed" role="status"><RouterLink to="/profile#credentials-profile" class="btn">Add fal key in Settings</RouterLink><RouterLink to="/help?topic=fal-key" class="small">fal key how-to</RouterLink></div>
    <label v-if="!props.workingDir">Project folder
      <select v-model="folder" class="input" aria-label="Project folder" @change="loadSlots">
        <option value="">Choose a folder with media slots</option>
        <option v-for="f in folders" :key="f.path" :value="f.path">{{ f.name }}</option>
      </select>
    </label>
    <p v-if="!props.workingDir && folders.length === 0" class="muted small">No folder with <code>media/slots.json</code> was found in your allowed working directories.</p>
    <label class="check approve"><input ref="confirmBox" v-model="confirm" type="checkbox" /> I understand each run spends from my fal account. Estimates are shown, but fal's invoice is the truth, and nothing here limits spending.</label>
    <p v-if="slots.length" class="small" role="status" data-testid="summary">
      {{ published.length }} published · {{ skipped.length }} skipped · {{ review.length }} waiting for your decision · {{ todo.length }} not made yet<template v-if="unfinished"> · <strong>{{ unfinished }} generating now</strong></template>
    </p>
    <p v-if="summary && summary.complete" class="small ok-text" role="status" data-testid="complete">Every slot is decided: published or skipped. Record it as your decision on the media story.</p>
    <div v-if="todo.length" class="batch" data-testid="batch">
      <strong>Generate everything not made yet</strong>
      <span class="muted small">{{ eligible.length }} ready<template v-if="stillWaiting">, {{ stillWaiting }} more need an approved still first</template>. Slots you have already made or published are never regenerated here.</span>
      <div class="controls">
        <select v-model="batchTier" class="input" aria-label="Tier for all"><option value="each">each slot's own tier</option><option value="draft">draft (cheapest)</option><option value="standard">standard</option><option value="premium">premium</option></select>
        <span class="small">{{ eligible.length ? (batch.unknown ? `about $${batch.total.toFixed(2)} plus ${batch.unknown} with no listed price` : `about $${batch.total.toFixed(2)}`) : 'nothing to generate' }}</span>
        <button type="button" class="btn primary" :disabled="!keyOk || busy || savingPlan || !!editing || !eligible.length" @click="generateAll">Generate all missing</button>
      </div>
      <p class="muted small">Draft stills are too small to publish. Clips need their approved stills published first, so accept the stills, then run this again for the rest.</p>
    </div>

    <h4 v-if="review.length" class="group">Waiting for your decision ({{ review.length }})</h4>
    <div v-for="s in review" :key="s.name" class="slot" :data-slot="s.name">
      <div><strong>{{ s.name }}</strong> <span class="muted small">· {{ s.kind }}<template v-if="s.world"> · {{ s.world }}</template></span><p v-if="s.purpose" class="muted small">{{ s.purpose }}</p>
        <p v-if="s.published" class="small" data-testid="replaces">Published now. Accepting a new take replaces it; None of these keeps it.</p></div>
      <ul class="candidates">
        <li v-for="c in s.candidates" :key="c" class="candidate">
          <video v-if="isVideo(c)" :src="candidateUrl(c)" class="thumb" controls muted loop preload="metadata" :aria-label="`Preview of ${c}`" />
          <a v-else :href="candidateUrl(c)" target="_blank" rel="noopener" :aria-label="`Open ${c} full size`"><img :src="candidateUrl(c)" class="thumb" loading="lazy" :alt="`Candidate ${c}`" /></a>
          <span class="small">{{ c }}</span>
          <button type="button" class="btn primary" :disabled="working[s.name]" :aria-label="`Accept ${c}`" @click="accept(s, c)">{{ working[s.name] ? 'Working…' : 'Accept and publish' }}</button>
        </li>
      </ul>
      <div class="controls">
        <button type="button" class="btn" :disabled="working[s.name]" :aria-label="`None of these for ${s.name}`" @click="decide(s, 'reject')">None of these: make another…</button>
        <button v-if="!s.published" type="button" class="btn" :disabled="working[s.name]" :aria-label="`Skip ${s.name}`" @click="decide(s, 'skip')">Skip: use the fallback</button>
      </div>
      <div v-if="more[s.name]" class="controls">
        <select v-model="tier[s.name]" class="input" :aria-label="`${s.name} tier`"><option value="draft">draft (cheapest)</option><option value="standard">standard</option><option value="premium">premium</option></select>
        <input v-model.number="count[s.name]" class="input" type="number" min="1" max="4" :aria-label="`${s.name} how many`" />
        <span class="small">{{ money(estimate(s)) }}</span>
        <button type="button" class="btn primary" :disabled="!keyOk || busy || savingPlan || !!editing || activeFor(s.name)" @click="generate(s)">{{ activeFor(s.name) ? 'Generating…' : 'Generate' }}</button>
      </div>
      <p v-if="note[s.name]" class="small" :class="note[s.name]!.ok ? 'ok-text' : 'error-text'" :role="note[s.name]!.ok ? 'status' : 'alert'" :data-note="s.name">{{ note[s.name]!.text }}</p>
      <p v-for="(j, i) in jobsFor(s.name)" :key="j.id" class="job small" :class="j.state === 'failed' ? 'error-text' : j.state === 'done' ? 'ok-text' : ''" :role="j.state === 'failed' ? 'alert' : 'status'" :data-job="s.name">
        <span v-if="j.state === 'queued' || j.state === 'running'" class="spinner" aria-hidden="true"></span>{{ jobLine(j, i + 1, jobsFor(s.name).length) }}
      </p>
      <button v-if="offerTake[s.name]" type="button" class="btn" :disabled="busy" :aria-label="`Another take for ${s.name}`" @click="generate(s, true)">Another take (spends again)</button>
    </div>

    <h4 v-if="todo.length" class="group">Not made yet ({{ todo.length }})</h4>
    <div v-for="s in todo" :key="s.name" class="slot" :data-slot="s.name">
      <div>
        <strong>{{ s.name }}</strong> <span class="muted small">· {{ s.kind }}<template v-if="s.world"> · {{ s.world }}</template></span>
        <p v-if="s.purpose" class="muted small">{{ s.purpose }}</p>
        <p v-if="s.waiting_for_stills.length" class="small">Waiting for the approved still: {{ s.waiting_for_stills.join(', ') }} (accept it first).</p>
      </div>
      <button v-if="s.plan_sha256 && editing !== s.name" class="btn" type="button" :disabled="busy || savingPlan || unfinished > 0" @click="openPlan(s)">Edit asset plan</button>
      <MediaPlanForm v-if="editing === s.name" v-model="editPlan" :kind="s.kind" :saving="savingPlan" :busy="busy" @save="savePlan(s)" @cancel="editing = null" />
      <div class="controls">
        <select v-model="tier[s.name]" class="input" :aria-label="`${s.name} tier`"><option value="draft">draft (cheapest)</option><option value="standard">standard</option><option value="premium">premium</option></select>
        <input v-model.number="count[s.name]" class="input" type="number" min="1" max="4" :aria-label="`${s.name} how many`" />
        <span class="small">{{ money(estimate(s)) }}</span>
        <button type="button" class="btn primary" :disabled="!keyOk || busy || savingPlan || !!editing || activeFor(s.name) || s.waiting_for_stills.length > 0" @click="generate(s)">{{ activeFor(s.name) ? 'Generating…' : 'Generate' }}</button>
        <button type="button" class="btn" :disabled="working[s.name]" :aria-label="`Skip ${s.name}`" @click="decide(s, 'skip')">Skip: use the fallback</button>
      </div>
      <p v-if="note[s.name]" class="small" :class="note[s.name]!.ok ? 'ok-text' : 'error-text'" :role="note[s.name]!.ok ? 'status' : 'alert'" :data-note="s.name">{{ note[s.name]!.text }}</p>
      <p v-for="(j, i) in jobsFor(s.name)" :key="j.id" class="job small" :class="j.state === 'failed' ? 'error-text' : j.state === 'done' ? 'ok-text' : ''" :role="j.state === 'failed' ? 'alert' : 'status'" :data-job="s.name">
        <span v-if="j.state === 'queued' || j.state === 'running'" class="spinner" aria-hidden="true"></span>{{ jobLine(j, i + 1, jobsFor(s.name).length) }}
      </p>
      <button v-if="offerTake[s.name]" type="button" class="btn" :disabled="busy" :aria-label="`Another take for ${s.name}`" @click="generate(s, true)">Another take (spends again)</button>
    </div>

    <h4 v-if="skipped.length" class="group">Skipped ({{ skipped.length }})</h4>
    <div v-for="s in skipped" :key="s.name" class="slot done" :data-slot="s.name">
      <div class="controls">
        <span><strong>{{ s.name }}</strong> <span class="muted small">· {{ s.kind }} · skipped, the site uses its fallback</span></span>
        <button type="button" class="btn" :disabled="working[s.name]" :aria-label="`Restore ${s.name}`" @click="decide(s, 'unskip')">Restore</button>
      </div>
      <p v-if="note[s.name]" class="small" :class="note[s.name]!.ok ? 'ok-text' : 'error-text'" :data-note="s.name">{{ note[s.name]!.text }}</p>
      <p v-for="(j, i) in jobsFor(s.name)" :key="j.id" class="job small" :class="j.state === 'failed' ? 'error-text' : j.state === 'done' ? 'ok-text' : ''" :role="j.state === 'failed' ? 'alert' : 'status'" :data-job="s.name">
        <span v-if="j.state === 'queued' || j.state === 'running'" class="spinner" aria-hidden="true"></span>{{ jobLine(j, i + 1, jobsFor(s.name).length) }}
      </p>
    </div>

    <h4 v-if="published.length" class="group">Published ({{ published.length }})</h4>
    <div v-if="published.length" class="gallery" data-testid="gallery">
      <figure v-for="s in published" :key="s.name" class="piece slot done" :data-slot="s.name">
        <video v-if="s.kind === 'video'" :src="publishedUrl(s.name)" class="thumb" controls muted loop preload="metadata" :aria-label="`Preview of ${s.name}`" />
        <a v-else :href="publishedUrl(s.name)" target="_blank" rel="noopener" :aria-label="`Open ${s.name} full size`"><img :src="publishedUrl(s.name)" class="thumb" loading="lazy" :alt="`Published ${s.name}`" /></a>
        <figcaption>
          <strong>{{ s.name }}</strong>
          <span class="muted small">{{ s.kind }}<template v-if="s.published_bytes"> · {{ bytes(s.published_bytes) }}</template> <span class="ok-text">✓ published</span><template v-if="s.unreviewed"> · new take waiting</template></span>
        </figcaption>
        <details class="more-actions">
          <summary class="small muted">More</summary>
          <p v-if="lastEvent(s)" class="muted small">Last: {{ lastEvent(s) }}</p>
          <div class="controls">
            <button type="button" class="btn" :aria-label="`Regenerate ${s.name}`" @click="more[s.name] = !more[s.name]">{{ more[s.name] ? 'Cancel' : 'Regenerate…' }}</button>
            <button v-if="s.plan_sha256 && editing !== s.name" type="button" class="btn" :aria-label="`Revise the plan for ${s.name}`" :disabled="busy || savingPlan || unfinished > 0 || (s.unreviewed ?? 0) > 0" @click="openPlan(s)">Revise prompt…</button>
          </div>
          <MediaPlanForm v-if="editing === s.name" v-model="editPlan" :kind="s.kind" published :saving="savingPlan" :busy="busy" @save="savePlan(s)" @cancel="editing = null" />
          <div v-if="more[s.name]" class="controls">
            <select v-model="tier[s.name]" class="input" :aria-label="`${s.name} tier`"><option value="draft">draft (cheapest)</option><option value="standard">standard</option><option value="premium">premium</option></select>
            <input v-model.number="count[s.name]" class="input" type="number" min="1" max="4" :aria-label="`${s.name} how many`" />
            <span class="small">{{ money(estimate(s)) }}</span>
            <button type="button" class="btn primary" :disabled="!keyOk || busy || savingPlan || !!editing || activeFor(s.name)" @click="generate(s, (s.unreviewed ?? 0) > 0, true)">{{ activeFor(s.name) ? 'Generating…' : 'Generate' }}</button>
          </div>
          <p v-if="more[s.name]" class="muted small">New takes appear under Waiting for your decision. The published file stays until you accept one.</p>
        </details>
        <p v-if="note[s.name]" class="small" :class="note[s.name]!.ok ? 'ok-text' : 'error-text'" :role="note[s.name]!.ok ? 'status' : 'alert'" :data-note="s.name">{{ note[s.name]!.text }}</p>
        <p v-for="(j, i) in jobsFor(s.name)" :key="j.id" class="job small" :class="j.state === 'failed' ? 'error-text' : j.state === 'done' ? 'ok-text' : ''" :role="j.state === 'failed' ? 'alert' : 'status'" :data-job="s.name">
          <span v-if="j.state === 'queued' || j.state === 'running'" class="spinner" aria-hidden="true"></span>{{ jobLine(j, i + 1, jobsFor(s.name).length) }}
        </p>
        <button v-if="offerTake[s.name]" type="button" class="btn" :disabled="busy" :aria-label="`Another take for ${s.name}`" @click="generate(s, true)">Another take (spends again)</button>
      </figure>
    </div>

    <p v-if="error" class="error-text" role="alert">{{ error }}</p>
    <p v-if="ledger" class="muted small">{{ ledger.done }} of {{ ledger.runs }} runs finished; estimated spend up to about ${{ ledger.estimated_usd.toFixed(2) }}<template v-if="ledger.repeats">, of which {{ ledger.repeats }} {{ ledger.repeats === 1 ? 'was a repeat' : 'were repeats' }} of a slot already generated (about ${{ ledger.repeat_usd.toFixed(2) }})</template><template v-if="ledger.unpriced">; {{ ledger.unpriced }} {{ ledger.unpriced === 1 ? 'run has' : 'runs have' }} no price and {{ ledger.unpriced === 1 ? 'is' : 'are' }} not counted</template>. {{ ledger.note }}</p>
  </section>
</template>
<style scoped>
.storage { display: flex; align-items: center; flex-wrap: wrap; gap: var(--gap-sm); padding: var(--gap-xs) var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); }
.small-btn { padding: 0 var(--gap-sm); }
.key-needed { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-sm); }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: var(--gap); }
.piece { display: grid; gap: var(--gap-xs); align-content: start; margin: 0; padding: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--panel); min-width: 0; }
.piece .thumb { width: 100%; height: auto; max-height: 11rem; object-fit: cover; border-radius: var(--radius-sm); background: var(--bg); }
.piece figcaption { display: grid; gap: var(--gap-xs); }
.more-actions summary { cursor: pointer; width: fit-content; }
.cost-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: var(--gap-sm); }
.cost-strip > div { display: grid; gap: var(--gap-xs); padding: var(--gap-sm) var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--panel); }
.cost-strip .k { color: var(--text-muted); font-size: var(--font-size-xs); }
.cost-strip strong { font-size: var(--font-size-lg); }
.cost-strip small { color: var(--text-muted); font-size: var(--font-size-xs); }
.approve { padding: var(--gap-sm) var(--gap); border: 1px solid var(--warn); border-radius: var(--radius); }
.media-gen { display: flex; flex-direction: column; gap: var(--gap); padding-top: var(--gap); border-top: 1px solid var(--glass-border); }
.batch { display: flex; flex-direction: column; gap: var(--gap-xs); padding: var(--gap); border: 1px solid var(--glass-border); border-radius: var(--radius, 8px); }
.slot { display: flex; flex-direction: column; gap: var(--gap-xs); padding-bottom: var(--gap); border-bottom: 1px solid var(--glass-border); }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap); }
.controls input[type='number'] { width: 4rem; }
.job { margin: 0; display: flex; align-items: center; gap: var(--gap-xs); }
.spinner { flex: none; width: 0.9rem; height: 0.9rem; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: media-spin 0.9s linear infinite; }
@keyframes media-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; border-right-color: currentColor; opacity: 0.6; } }
.candidates { margin: 0; padding: 0; list-style: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: var(--gap); }
.candidate { display: flex; flex-direction: column; gap: var(--gap-xs); }
.group { margin: var(--gap) 0 0; font-size: var(--font-size-md, 1rem); }
.slot.done { padding-bottom: var(--gap-xs); }
.ok-text { color: var(--success, #3fb950); }
.thumb { width: 100%; max-height: 11rem; object-fit: contain; background: rgba(0, 0, 0, 0.35); border: 1px solid var(--glass-border); border-radius: 6px; display: block; }
label { display: flex; flex-direction: column; gap: var(--gap-xs); color: var(--text-muted); font-size: var(--font-size-sm); }
.check { flex-direction: row; align-items: center; }
p { margin: 0; }
</style>
