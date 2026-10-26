<script setup lang="ts">
import { computed, ref } from 'vue'
import { postFile, postJson } from '@/lib/api'
import type { Project } from '@/lib/projects'
import AppSelect from './AppSelect.vue'
import LoadingCard from './LoadingCard.vue'

const props = defineProps<{ workdirs: { path: string }[]; scratchRoot?: string | null }>()
const emit = defineEmits<{ created: [Project]; cancel: [] }>()
interface Review {
  import_id: string; schema: string; rule: string
  source: { product: string | null; version: string | null; host: string | null; project_id: number | null; revision: number | null; project_type: string | null; state: string | null; title: string | null }
  workspace: { path: string | null; repository: string | null; branch: string | null; head: string | null }
  freshness: { state?: string; reasons?: string[] }
  intent: { title: string; project_type: string | null; brief: string }
  stories: { key: string; title: string; status: string }[]
  documents: string[]; living_docs: string[]; references: string[]; published_media: string[]
  missing: { kind: string; path: string | null; slot: string | null; missing_reason: string | null }[]
}
const review = ref<Review | null>(null), busy = ref(''), error = ref('')
const workingDir = ref(props.scratchRoot || props.workdirs[0]?.path || ''), copyReferences = ref(true), understood = ref(false)
const accepted = computed(() => review.value?.stories.filter(s => s.status.startsWith('accepted')).length ?? 0)
const remaining = computed(() => (review.value?.stories.length ?? 0) - accepted.value)

async function choose(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  busy.value = 'Checking the packet…'; error.value = ''; review.value = null; understood.value = false
  try { review.value = await postFile<Review>('/api/projects/packet-import', new File([file], file.name, { type: 'application/zip' })) }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = '' }
}
async function create() {
  if (!review.value) return
  busy.value = 'Creating the continuation draft…'; error.value = ''
  try { emit('created', await postJson<Project>(`/api/projects/packet-import/${review.value.import_id}/create`, { working_dir: workingDir.value, copy_references: copyReferences.value })) }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = '' }
}
</script>

<template>
  <form class="packet-import" @submit.prevent="create">
    <h2 id="packet-import-title">Import project packet</h2>
    <p class="muted">Continue a project exported from MCD or RCD. Import creates a draft for you to review and plan. Nothing runs, and no tasks, approvals, model routes, branch access or spending decisions carry over.</p>
    <label>Packet file (.zip)<input type="file" accept=".zip,application/zip" :disabled="!!busy" data-testid="packet-file" @change="choose" /></label>
    <LoadingCard v-if="busy" :title="busy" detail="Checking file list, hashes, paths, sizes and images. Nothing in the packet is executed." :rows="2" />
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <template v-if="review">
      <section>
        <h3>{{ review.intent.title }}</h3>
        <p class="small">From {{ review.source.product }} {{ review.source.version }} · project {{ review.source.project_id }} revision {{ review.source.revision }} ({{ review.source.state }}) on {{ review.source.host }} · {{ review.intent.project_type || 'no type' }}</p>
        <p class="small">Source: {{ review.workspace.repository || 'no registered repository' }} · {{ review.workspace.branch || 'unknown branch' }} @ {{ review.workspace.head?.slice(0, 12) || 'unknown commit' }} · packet was {{ review.freshness.state || 'unknown' }} when exported</p>
        <p class="small">{{ accepted }} stories accepted and {{ remaining }} remaining in the source project. These are history, not local acceptance.</p>
        <p class="small">{{ review.documents.length }} documents · {{ review.living_docs.length }} living docs · {{ review.references.length }} reference images · {{ review.published_media.length }} published media</p>
        <div v-if="review.missing.length" class="notice-warn"><strong>Not in the packet</strong><p v-for="m in review.missing" :key="(m.path || m.slot || '') + m.kind" class="small">{{ m.path || m.slot }}: {{ m.missing_reason }}</p></div>
        <p class="muted small">{{ review.rule }}</p>
        <details><summary>Imported brief</summary><pre>{{ review.intent.brief }}</pre></details>
      </section>
      <label>Destination working directory<AppSelect v-model="workingDir" aria-label="Destination working directory"><option v-for="w in workdirs" :key="w.path" :value="w.path">{{ w.path === scratchRoot ? 'New private folder' : w.path }}</option></AppSelect></label>
      <p class="muted small">Source code is not in the packet. If the work continues from a repository, select its checkout on this host. A path from another host is never used.</p>
      <label class="check"><input v-model="copyReferences" type="checkbox" :disabled="!review.references.length" />Copy the {{ review.references.length }} reference images into this project’s media/references</label>
      <label class="check"><input v-model="understood" type="checkbox" data-testid="packet-understood" />I understand this creates a draft only. I will review the brief and plan it before any work starts.</label>
    </template>
    <div class="dialog-actions"><button type="button" class="btn" @click="emit('cancel')">Cancel</button><button class="btn primary" :disabled="!!busy || !review || !understood || !workingDir">Create continuation draft</button></div>
  </form>
</template>

<style scoped>
section{margin:var(--gap) 0}h3{font-size:var(--font-size-lg)}label{display:grid;gap:var(--gap-sm);margin:var(--gap) 0}
.check{display:flex;gap:var(--gap-sm);align-items:flex-start}.small{font-size:var(--font-size-xs)}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:16rem;overflow:auto}summary{cursor:pointer}
</style>
