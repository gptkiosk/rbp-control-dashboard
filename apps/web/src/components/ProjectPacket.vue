<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { downloadFile, getJson } from '@/lib/api'
import type { Project } from '@/lib/projects'
import LoadingCard from './LoadingCard.vue'

const props = defineProps<{ project: Project }>()
interface PacketView {
  folder: string; start_here: string
  manifest: {
    schema: string; generator: { product: string; version: string }
    freshness: { generated_at: number; state: 'current' | 'stale' | 'in_progress' | 'unknown'; reasons: string[] }
    workspace: { path: string; branch: string | null; head: string | null }
    living_docs: { path: string; files: { path: string | null; bytes?: number; note?: string }[] }
    documents: { path: string; purpose: string; bytes: number; truncated: boolean }[]
    assets: { kind: string; path?: string; slot?: string; published?: boolean }[]
    limits: { source_map: string | null; omitted_files: number | null }
  }
}
const LABELS = { current: 'Current', stale: 'Stale', in_progress: 'Work in progress', unknown: 'Unknown' }
const packet = ref<PacketView | null>(null), busy = ref(''), error = ref(''), message = ref('')
const includeMedia = ref(false)
let sequence = 0
const fresh = computed(() => packet.value?.manifest.freshness)
const living = computed(() => packet.value?.manifest.living_docs.files.filter(f => f.path) ?? [])
const references = computed(() => packet.value?.manifest.assets.filter(a => a.kind === 'reference').length ?? 0)
const published = computed(() => packet.value?.manifest.assets.filter(a => a.kind === 'slot' && a.published).length ?? 0)
const kb = (n: number) => n < 1024 ? `${n} B` : `${Math.round(n / 1024)} KB`

async function load(rescan = false) {
  const request = ++sequence
  busy.value = rescan ? 'Rescanning the source and rebuilding the packet…' : 'Preparing the project packet…'; error.value = ''; message.value = ''
  try {
    const result = await getJson<PacketView>(`/api/projects/${props.project.id}/packet${rescan ? '?refresh_source=true' : ''}`)
    if (request === sequence) packet.value = result
  } catch (e) { if (request === sequence) { packet.value = null; error.value = String(e instanceof Error ? e.message : e) } }
  finally { if (request === sequence) busy.value = '' }
}
watch(() => [props.project.id, props.project.revision, props.project.state, props.project.updated_at], () => { void load() }, { immediate: true })
async function download() {
  busy.value = 'Building the packet archive…'; error.value = ''; message.value = ''
  try {
    const name = await downloadFile(`/api/projects/${props.project.id}/packet.zip${includeMedia.value ? '?include_media=true' : ''}`, `project-${props.project.id}-packet.zip`)
    message.value = `Downloaded ${name}. Items left out are listed in its PACKET.json with the reason.`
  } catch (e) { error.value = String(e instanceof Error ? e.message : e) }
  finally { busy.value = '' }
}
async function copyStart() {
  if (!packet.value) return
  try { await navigator.clipboard.writeText(packet.value.start_here); message.value = 'START-HERE copied.' }
  catch { message.value = 'Copy blocked by the browser. Open “Start here” below and copy it.' }
}
</script>

<template>
  <section class="packet" aria-labelledby="packet-title">
    <header><h3 id="packet-title">Project packet</h3><span v-if="fresh" class="freshness" :class="`fresh-${fresh.state}`" data-testid="packet-freshness">{{ LABELS[fresh.state] }}</span></header>
    <p class="muted small">Continuation documents for another project, host or coding app. The app keeps them in its private data folder and never writes into this workspace. Agents keep <code>docs/project/</code> current.</p>
    <LoadingCard v-if="busy" :title="busy" detail="Reading recorded project state and Git facts on this host." :rows="2" />
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <template v-if="packet && fresh">
      <ul v-if="fresh.reasons.length" class="reasons"><li v-for="r in fresh.reasons" :key="r">{{ r }}</li></ul>
      <p class="small">Generated {{ new Date(fresh.generated_at * 1000).toLocaleString() }} by {{ packet.manifest.generator.product }} {{ packet.manifest.generator.version }} · {{ packet.manifest.documents.length }} documents · {{ living.length }} living docs · {{ references }} reference images · {{ published }} published media</p>
      <div class="actions">
        <button class="btn primary" :disabled="!!busy" @click="download">Download packet (.zip)</button>
        <button class="btn" :disabled="!!busy" @click="copyStart">Copy START-HERE</button>
        <button class="btn" :disabled="!!busy" @click="load(true)">Rescan source</button>
      </div>
      <label class="check"><input v-model="includeMedia" type="checkbox" :disabled="!!busy" data-testid="packet-media" />Include published media (reference images are always included, within the 64 MB packet limit)</label>
      <p class="muted small">Source code is not in the packet. It names the repository, branch and commit to continue from.</p>
      <details><summary>Start here</summary><pre>{{ packet.start_here }}</pre></details>
      <details><summary>Documents</summary>
        <p v-for="d in packet.manifest.documents" :key="d.path" class="small"><strong>{{ d.path }}</strong> · {{ kb(d.bytes) }}{{ d.truncated ? ' · truncated' : '' }} · {{ d.purpose }}</p>
        <p v-if="packet.manifest.limits.source_map" class="muted small">Source scan: {{ packet.manifest.limits.source_map }}</p>
      </details>
    </template>
    <p v-if="message" role="status">{{ message }}</p>
  </section>
</template>

<style scoped>
header,.actions{display:flex;align-items:center;gap:var(--gap);flex-wrap:wrap}header{justify-content:space-between}h3{font-size:var(--font-size-lg)}
.packet{margin-top:var(--gap);border-top:1px solid var(--surface-border);padding-top:var(--gap)}
.freshness{font-size:var(--font-size-xs);padding:2px var(--gap-sm);border-radius:999px;border:1px solid var(--surface-border)}
.fresh-current{color:var(--ok);background:var(--ok-soft)}.fresh-stale{color:var(--warn);background:var(--warn-soft)}.fresh-unknown,.fresh-in_progress{color:var(--text-muted)}
.reasons{margin:var(--gap-sm) 0;padding-left:1.2em;font-size:var(--font-size-xs)}.check{display:flex;gap:var(--gap-sm);align-items:flex-start;margin:var(--gap) 0}
details{margin-top:var(--gap-sm)}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere}.small{font-size:var(--font-size-xs)}
</style>
