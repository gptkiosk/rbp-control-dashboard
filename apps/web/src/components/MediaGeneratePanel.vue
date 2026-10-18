<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getJson, postJson } from '@/lib/api'
interface Plan { endpoint: string; estimate_usd: number | null }
interface Slot { name: string; kind: 'image' | 'video'; world: string | null; purpose: string; prompt: string; published: boolean; inbox?: string | null; candidates: string[]; waiting_for_stills: string[]; plans: Record<Tier, Plan> }
interface Job { id: string; state: 'queued' | 'running' | 'done' | 'failed'; progress: string; slot: string; error: string | null; files: { path: string; bytes: number }[] }
type Tier = 'draft' | 'standard' | 'premium'
const props = defineProps<{ keySaved: boolean }>()
const folders = ref<{ path: string; name: string }[]>([])
const folder = ref('')
const slots = ref<Slot[]>([])
const tier = ref<Record<string, Tier>>({}), count = ref<Record<string, number>>({})
const jobs = ref<Job[]>([])
const confirm = ref(false), error = ref(''), busy = ref(false)
// Feedback belongs beside the button that was pressed, not at the bottom of a long panel.
const note = ref<Record<string, { ok: boolean; text: string }>>({}), chosen = ref<Record<string, string>>({}), working = ref<Record<string, boolean>>({})
const ledger = ref<{ runs: number; done: number; estimated_usd: number; note: string } | null>(null)
let timer: ReturnType<typeof setInterval> | undefined
const money = (v: number | null) => (v === null ? 'price not listed' : `about $${v.toFixed(2)}`)
async function loadFolders() { try { folders.value = (await getJson<{ folders: { path: string; name: string }[] }>('/api/media/folders')).folders; if (folders.value.length === 1) { folder.value = folders.value[0]!.path; await loadSlots() } } catch (e) { error.value = String(e instanceof Error ? e.message : e) } }
async function loadSlots() {
  error.value = ''
  if (!folder.value) { slots.value = []; return }
  try {
    const data = await getJson<{ slots: Slot[] }>(`/api/media/slots?working_dir=${encodeURIComponent(folder.value)}`)
    slots.value = data.slots
    for (const s of data.slots) { tier.value[s.name] ||= 'standard'; count.value[s.name] ||= 1 }
  } catch (e) { error.value = e instanceof Error ? e.message : String(e); slots.value = [] }
}
async function loadLedger() { try { ledger.value = await getJson('/api/media/ledger') } catch { ledger.value = null } }
// One batch for everything still missing: slots with nothing published, no candidate yet and no approved still they wait for.
const batchTier = ref<Tier>('standard')
const eligible = computed(() => slots.value.filter(s => !s.published && s.candidates.length === 0 && s.waiting_for_stills.length === 0))
const stillWaiting = computed(() => slots.value.filter(s => !s.published && s.candidates.length === 0 && s.waiting_for_stills.length > 0).length)
const batch = computed(() => {
  let total = 0, unknown = 0
  for (const s of eligible.value) { const e = s.plans[batchTier.value].estimate_usd; if (e === null) unknown++; else total += e }
  return { total, unknown }
})
async function generateAll() {
  if (!confirm.value || busy.value || !eligible.value.length) return
  const n = eligible.value.length, tierName = batchTier.value
  const price = batch.value.unknown ? `about $${batch.value.total.toFixed(2)} plus ${batch.value.unknown} with no listed price` : `about $${batch.value.total.toFixed(2)}`
  if (!window.confirm(`Generate ${n} item${n === 1 ? '' : 's'} at the ${tierName} tier? Estimated cost ${price}. This spends from your fal account and cannot be undone; fal's invoice is the truth.`)) return
  busy.value = true; error.value = ''
  try {
    for (const s of eligible.value) {
      const r = await postJson<{ jobs: string[] }>('/api/media/generate', { working_dir: folder.value, slot: s.name, tier: tierName, count: 1, confirm_spend: true })
      for (const id of r.jobs) jobs.value.push({ id, state: 'queued', progress: '', slot: s.name, error: null, files: [] })
    }
    poll()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e); if (jobs.value.length) poll() } finally { busy.value = false }
}
const candidateUrl = (name: string) => `/api/media/candidate?working_dir=${encodeURIComponent(folder.value)}&name=${encodeURIComponent(name)}`
const isVideo = (name: string) => /\.(mp4|webm)$/i.test(name)
function estimate(s: Slot) { const e = s.plans[tier.value[s.name] || 'standard'].estimate_usd; return e === null ? null : e * (count.value[s.name] || 1) }
async function generate(s: Slot) {
  if (!confirm.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    const r = await postJson<{ jobs: string[] }>('/api/media/generate', { working_dir: folder.value, slot: s.name, tier: tier.value[s.name] || 'standard', count: count.value[s.name] || 1, confirm_spend: true })
    for (const id of r.jobs) jobs.value.push({ id, state: 'queued', progress: '', slot: s.name, error: null, files: [] })
    poll()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
async function refreshJobs() {
  let pending = false
  for (const j of jobs.value) {
    if (j.state === 'done' || j.state === 'failed') continue
    try { Object.assign(j, await getJson<Job>(`/api/media/jobs/${j.id}`)) } catch { j.state = 'failed'; j.error = 'MCD no longer knows this job; check the ledger.' }
    if (j.state === 'queued' || j.state === 'running') pending = true
  }
  if (!pending) { clearInterval(timer); timer = undefined; await loadSlots(); await loadLedger() }
}
function poll() { if (!timer) timer = setInterval(() => void refreshJobs(), 3000) }
async function pick(s: Slot, candidate: string) {
  working.value[s.name] = true
  try {
    await postJson('/api/media/pick', { working_dir: folder.value, slot: s.name, candidate })
    chosen.value[s.name] = candidate
    note.value[s.name] = { ok: true, text: `Chosen: ${candidate}. Press Publish to make it part of the site.` }
    await loadSlots()
  } catch (e) { note.value[s.name] = { ok: false, text: e instanceof Error ? e.message : String(e) } } finally { working.value[s.name] = false }
}
async function publish(s: Slot) {
  working.value[s.name] = true
  try {
    const r = await postJson<{ files: { path: string; bytes: number }[] }>('/api/media/publish', { working_dir: folder.value, slot: s.name })
    note.value[s.name] = { ok: true, text: `Published: ${r.files.map(f => `${f.path} (${Math.max(1, Math.round(f.bytes / 1024))} KB)`).join(', ')}` }
    await loadSlots(); await loadLedger()
  } catch (e) { note.value[s.name] = { ok: false, text: e instanceof Error ? e.message : String(e) } } finally { working.value[s.name] = false }
}
onMounted(() => { void loadFolders(); void loadLedger() })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>
<template>
  <section class="media-gen" aria-labelledby="media-gen-title">
    <h3 id="media-gen-title">Generate media with your saved fal key</h3>
    <p class="muted small">
      MCD makes the call with your saved key, which never reaches an agent or the project folder. The folder's <code>media/slots.json</code> only supplies prompts and file names; no code from it is run.
      Results appear as candidates; pick one, then run the project's own <code>ingest</code> step.
    </p>
    <p v-if="!props.keySaved" class="small" role="status">Save your fal key first (Profile, Private credentials).</p>
    <label>Project folder
      <select v-model="folder" class="input" aria-label="Project folder" @change="loadSlots">
        <option value="">Choose a folder with media slots</option>
        <option v-for="f in folders" :key="f.path" :value="f.path">{{ f.name }}</option>
      </select>
    </label>
    <p v-if="folders.length === 0" class="muted small">No folder with <code>media/slots.json</code> was found in your allowed working directories.</p>
    <label class="check"><input v-model="confirm" type="checkbox" /> I understand each run spends from my fal account. Estimates are shown, but fal's invoice is the truth, and nothing here limits spending.</label>
    <div v-if="slots.length" class="batch" data-testid="batch">
      <strong>Generate everything still missing</strong>
      <span class="muted small">{{ eligible.length }} ready<template v-if="stillWaiting">, {{ stillWaiting }} more need an approved still first</template>.</span>
      <div class="controls">
        <select v-model="batchTier" class="input" aria-label="Tier for all"><option value="draft">draft (cheapest)</option><option value="standard">standard</option><option value="premium">premium</option></select>
        <span class="small">{{ eligible.length ? (batch.unknown ? `about $${batch.total.toFixed(2)} plus ${batch.unknown} with no listed price` : `about $${batch.total.toFixed(2)}`) : 'nothing to generate' }}</span>
        <button type="button" class="btn primary" :disabled="!props.keySaved || !confirm || busy || !eligible.length" @click="generateAll">Generate all missing</button>
      </div>
      <p class="muted small">Stills usually deserve a look at the draft tier first; draft stills are too small to publish. Clips need their approved stills published, so run the stills, pick, ingest, then run this again for the rest.</p>
    </div>
    <div v-for="s in slots" :key="s.name" class="slot" :data-slot="s.name">
      <div>
        <strong>{{ s.name }}</strong> <span class="muted small">· {{ s.kind }}<template v-if="s.world"> · {{ s.world }}</template> · {{ s.published ? 'published' : 'not published' }}</span>
        <p v-if="s.purpose" class="muted small">{{ s.purpose }}</p>
        <p v-if="s.waiting_for_stills.length" class="small">Waiting for the approved still: {{ s.waiting_for_stills.join(', ') }} (generate, pick and ingest it first).</p>
      </div>
      <div class="controls">
        <select v-model="tier[s.name]" class="input" :aria-label="`${s.name} tier`"><option value="draft">draft (cheapest)</option><option value="standard">standard</option><option value="premium">premium</option></select>
        <input v-model.number="count[s.name]" class="input" type="number" min="1" max="4" :aria-label="`${s.name} how many`" />
        <span class="small">{{ money(estimate(s)) }}</span>
        <button type="button" class="btn primary" :disabled="!props.keySaved || !confirm || busy || s.waiting_for_stills.length > 0" @click="generate(s)">Generate</button>
      </div>
      <ul v-if="s.candidates.length" class="candidates">
        <li v-for="c in s.candidates" :key="c" class="candidate">
          <video v-if="isVideo(c)" :src="candidateUrl(c)" class="thumb" controls muted loop preload="metadata" :aria-label="`Preview of ${c}`" />
          <a v-else :href="candidateUrl(c)" target="_blank" rel="noopener" :aria-label="`Open ${c} full size`"><img :src="candidateUrl(c)" class="thumb" loading="lazy" :alt="`Candidate ${c}`" /></a>
          <span class="small">{{ c }}</span>
          <button type="button" class="btn" :class="{ primary: chosen[s.name] === c }" :disabled="working[s.name]" :aria-label="`Use ${c}`" @click="pick(s, c)">{{ chosen[s.name] === c ? '✓ Chosen' : 'Use this one' }}</button>
        </li>
      </ul>
      <div v-if="s.inbox" class="small chosen-row">
        <span>Waiting in the inbox: <strong>{{ s.inbox }}</strong><template v-if="chosen[s.name]"> (from {{ chosen[s.name] }})</template></span>
        <button type="button" class="btn primary" :disabled="working[s.name]" :aria-label="`Publish ${s.name}`" @click="publish(s)">{{ working[s.name] ? 'Working…' : s.published ? 'Publish again' : 'Publish' }}</button>
      </div>
      <p v-if="note[s.name]" class="small" :class="note[s.name]!.ok ? 'ok-text' : 'error-text'" :role="note[s.name]!.ok ? 'status' : 'alert'" :data-note="s.name">{{ note[s.name]!.text }}</p>
    </div>
    <ul v-if="jobs.length" class="jobs" aria-live="polite">
      <li v-for="j in jobs" :key="j.id">{{ j.slot }}: {{ j.state }}<template v-if="j.progress && j.state !== 'done'"> ({{ j.progress }})</template><template v-if="j.error"> · {{ j.error }}</template></li>
    </ul>
    <p v-if="error" class="error-text" role="alert">{{ error }}</p>
    <p v-if="ledger" class="muted small">{{ ledger.done }} of {{ ledger.runs }} runs finished; estimated spend about ${{ ledger.estimated_usd.toFixed(2) }}. {{ ledger.note }}</p>
  </section>
</template>
<style scoped>
.media-gen { display: flex; flex-direction: column; gap: var(--gap); padding-top: var(--gap); border-top: 1px solid var(--glass-border); }
.batch { display: flex; flex-direction: column; gap: var(--gap-xs); padding: var(--gap); border: 1px solid var(--glass-border); border-radius: var(--radius, 8px); }
.slot { display: flex; flex-direction: column; gap: var(--gap-xs); padding-bottom: var(--gap); border-bottom: 1px solid var(--glass-border); }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap); }
.controls input[type='number'] { width: 4rem; }
.jobs { margin: 0; padding-left: 1.2rem; }
.candidates { margin: 0; padding: 0; list-style: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: var(--gap); }
.candidate { display: flex; flex-direction: column; gap: var(--gap-xs); }
.chosen-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap); }
.ok-text { color: var(--success, #3fb950); }
.thumb { width: 100%; max-height: 11rem; object-fit: contain; background: rgba(0, 0, 0, 0.35); border: 1px solid var(--glass-border); border-radius: 6px; display: block; }
label { display: flex; flex-direction: column; gap: var(--gap-xs); color: var(--text-muted); font-size: var(--font-size-sm); }
.check { flex-direction: row; align-items: center; }
p { margin: 0; }
</style>
