<script setup lang="ts">
// Reference art for a project: drop or choose images, see them as thumbnails, remove one. They live in the project's media/references/,
// and the planner and every story are told to follow them for style. Uploads go one image at a time so each can be refused on its own.
import { computed, onMounted, ref } from 'vue'
import { getJson, postFile, postJson } from '@/lib/api'
import { formatBytes } from '@/lib/format'

interface Ref { name: string; size: number; path: string }
interface Usage { references_bytes: number; candidates_bytes: number; media_bytes: number; disk_free_bytes: number | null; disk_total_bytes: number | null }
const props = defineProps<{ workingDir: string }>()
const usage = ref<Usage | null>(null)
const items = ref<Ref[]>([]), maxBytes = ref(10 * 1024 * 1024), maxCount = ref(24)
const busy = ref(false), dragging = ref(false), error = ref(''), notice = ref(''), progress = ref('')
const input = ref<HTMLInputElement | null>(null)
const q = (extra: Record<string, string> = {}) => new URLSearchParams({ working_dir: props.workingDir, ...extra }).toString()
const thumb = (r: Ref) => `/api/media/reference?${q({ name: r.name })}`
const room = computed(() => Math.max(0, maxCount.value - items.value.length))
// How full the disk is, for the bar; low free space is called out so a big media run does not fill the host.
const diskUsed = computed(() => usage.value?.disk_total_bytes ? 1 - (usage.value.disk_free_bytes ?? 0) / usage.value.disk_total_bytes : null)
const diskLow = computed(() => diskUsed.value !== null && diskUsed.value > 0.9)
const mb = (n: number) => `${(n / (1024 * 1024)).toFixed(n < 1024 * 1024 ? 2 : 1)} MB`

async function load() {
  const r = await getJson<{ references: Ref[]; max_bytes: number; max_count: number; usage: Usage }>(`/api/media/references?${q()}`)
  items.value = r.references; maxBytes.value = r.max_bytes; maxCount.value = r.max_count; usage.value = r.usage
}
async function add(files: FileList | File[] | null | undefined) {
  const list = Array.from(files ?? []).filter(f => f.type.startsWith('image/'))
  if (!list.length) { error.value = 'Choose PNG, JPEG, WebP or GIF images.'; return }
  busy.value = true; error.value = ''; notice.value = ''
  const refused: string[] = []; let added = 0
  for (const [i, f] of list.entries()) {
    progress.value = `Uploading ${i + 1} of ${list.length}: ${f.name}`
    if (f.size > maxBytes.value) { refused.push(`${f.name} (over ${mb(maxBytes.value)})`); continue }
    try { await postFile(`/api/media/references?${q({ name: f.name })}`, f); added++ } catch (e) { refused.push(`${f.name} (${e instanceof Error ? e.message : String(e)})`) }
  }
  progress.value = ''
  try { await load() } catch { /* the list refreshes on the next visit */ }
  busy.value = false
  if (added) notice.value = `Added ${added} reference image${added === 1 ? '' : 's'}. Stories that start from now on are told to follow them.`
  if (refused.length) error.value = `Not added: ${refused.join('; ')}`
  if (input.value) input.value.value = ''
}
async function remove(r: Ref) {
  busy.value = true; error.value = ''; notice.value = ''
  try { const res = await postJson<{ references: Ref[]; usage: Usage }>('/api/media/references/remove', { working_dir: props.workingDir, name: r.name }); items.value = res.references; usage.value = res.usage }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
function drop(e: DragEvent) { dragging.value = false; void add(e.dataTransfer?.files) }
onMounted(() => { load().catch(e => { error.value = e instanceof Error ? e.message : String(e) }) })
</script>
<template>
  <section class="refs" aria-labelledby="refs-title" data-testid="reference-art">
    <header><h3 id="refs-title">Reference art</h3><p class="muted small">Images that show the look you want: palette, type, mood. The planner and every story are told to follow them. A media slot can also list one in its <code>refs</code>, so generated images match it.</p></header>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="drop" :class="{ over: dragging }" data-test="drop" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="drop">
      <p>Drop images here, or</p>
      <button type="button" class="btn primary" data-action="choose" :disabled="busy || !room" @click="input?.click()">Choose images</button>
      <input ref="input" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden data-test="file" @change="add(($event.target as HTMLInputElement).files)" />
      <p class="muted small">PNG, JPEG, WebP or GIF, up to {{ mb(maxBytes) }} each. {{ room }} of {{ maxCount }} places left.</p>
      <p v-if="progress" class="small" role="status">{{ progress }}</p>
    </div>
    <div v-if="usage" class="space" data-test="space">
      <p class="small"><strong>Space used by this project's media:</strong> {{ formatBytes(usage.media_bytes) }} (reference art {{ formatBytes(usage.references_bytes) }}, generated takes {{ formatBytes(usage.candidates_bytes) }})<template v-if="usage.disk_free_bytes !== null">. Disk: {{ formatBytes(usage.disk_free_bytes) }} free of {{ formatBytes(usage.disk_total_bytes) }}.</template></p>
      <div v-if="diskUsed !== null" class="bar" :class="{ low: diskLow }" role="meter" :aria-valuenow="Math.round(diskUsed * 100)" aria-valuemin="0" aria-valuemax="100" aria-label="Disk space used"><span :style="{ width: `${Math.round(diskUsed * 100)}%` }" /></div>
      <p v-if="diskLow" class="notice-warn small" role="status">The disk is over 90% full. Clear generated takes you no longer need (Housekeeping lists the largest projects).</p>
    </div>
    <ul v-if="items.length" class="grid" data-test="items">
      <li v-for="r in items" :key="r.name">
        <img :src="thumb(r)" :alt="`Reference art ${r.name}`" loading="lazy" />
        <span class="name small" :title="r.path">{{ r.name }}</span>
        <button type="button" class="btn small-btn" :disabled="busy" :aria-label="`Remove ${r.name}`" @click="remove(r)">Remove</button>
      </li>
    </ul>
    <p v-else class="muted small">No reference art yet.</p>
  </section>
</template>
<style scoped>
.refs { display: grid; gap: var(--gap-sm); }
header h3 { margin: 0; }
header p { margin: var(--gap-xs) 0 0; }
.drop { display: grid; justify-items: center; gap: var(--gap-xs); padding: var(--gap); border: 2px dashed var(--surface-border); border-radius: var(--radius); text-align: center; }
.drop.over { border-color: var(--accent); background: var(--accent-soft); }
.drop p { margin: 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr)); gap: var(--gap-sm); padding: 0; margin: 0; list-style: none; }
.grid li { display: grid; gap: var(--gap-xs); padding: var(--gap-xs); border: 1px solid var(--surface-border); border-radius: var(--radius); min-width: 0; }
.grid img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: var(--radius-sm); background: var(--bg); }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.small { font-size: var(--font-size-xs); }
.space { display: grid; gap: var(--gap-xs); }
.space p { margin: 0; }
.bar { height: 0.4rem; border-radius: var(--radius-pill); background: var(--surface-border); overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--accent); }
.bar.low span { background: var(--warn); }
.small-btn { padding: 0 var(--gap-sm); }
</style>
