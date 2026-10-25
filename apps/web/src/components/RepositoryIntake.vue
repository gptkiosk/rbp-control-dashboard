<script setup lang="ts">
import { ref } from 'vue'
import { getJson } from '@/lib/api'
import AppSelect from './AppSelect.vue'
import LoadingCard from './LoadingCard.vue'
defineProps<{ workdirs: { path: string }[] }>()
const emit = defineEmits<{ imported: [{ working_dir: string; brief: string }] }>()
interface Inventory {
  brief: string; workspace: { path: string; head: string }; languages: string[]; scanned_files: number; omitted_files: number
  documentation: string[]; manifests: string[]; required_tools: string[]; changed_during_scan: boolean
  dependencies: { name: string; version: string; source: string }[]
  variables: { name: string; references: string[] }[]; limits: string
}
const open = ref(false), folder = ref(''), busy = ref(false), error = ref(''), data = ref<Inventory | null>(null)
async function scan() {
  busy.value = true; error.value = ''; data.value = null
  try { data.value = await getJson(`/api/projects/coordinator?operation=repository_intake&working_dir=${encodeURIComponent(folder.value)}`) }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
function use() {
  if (!data.value) return
  emit('imported', { working_dir: data.value.workspace.path, brief: data.value.brief }); open.value = false
}
</script>
<template>
  <section class="intake">
    <button type="button" class="btn" :aria-expanded="open" @click="open = !open">{{ open ? 'Close repository intake' : 'Import existing project…' }}</button>
    <template v-if="open">
      <p class="muted small">Map an existing repository without changing its files. Then describe the changes you want.</p>
      <label>Repository on this host<AppSelect v-model="folder" editable :disabled="busy" aria-label="Repository to import" placeholder="Choose the repository root"><option v-for="w in workdirs" :key="w.path" :value="w.path">{{ w.path }}</option></AppSelect></label>
      <button type="button" class="btn" :disabled="busy || !folder" @click="scan">Inspect repository</button>
      <LoadingCard v-if="busy" title="Mapping repository…" detail="Reading tracked source, dependency manifests, docs and variable names. No scripts run." :rows="2" />
      <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
      <template v-if="data">
        <p>{{ data.languages.join(', ') || 'No language detected' }} · {{ data.scanned_files }} files mapped · {{ data.omitted_files }} omitted</p>
        <p class="muted small">Tools to confirm: {{ data.required_tools.join(', ') || 'Review with the planner' }}. Branch permissions still apply.</p>
        <p v-if="data.changed_during_scan" class="notice-warn">Repository state changed during intake. Inspect it again before using this map.</p>
        <details><summary>Dependency, documentation and configuration map</summary><h3>Manifests</h3><p>{{ data.manifests.join(', ') || 'None detected' }}</p><h3>Declared dependencies</h3><p v-for="(d, i) in data.dependencies" :key="i">{{ d.name }} · {{ d.version }} · {{ d.source }}</p><h3>Documentation</h3><p v-for="d in data.documentation" :key="d">{{ d }}</p><h3>Configuration names</h3><p v-for="v in data.variables" :key="v.name">{{ v.name }} · {{ v.references.join(', ') }}</p><p class="muted small">{{ data.limits }}</p></details>
        <button type="button" class="btn primary" :disabled="data.changed_during_scan" @click="use">Use this repository</button>
      </template>
    </template>
  </section>
</template>
<style scoped>
.intake{margin:var(--gap) 0}label{display:grid;gap:var(--gap-sm);margin:var(--gap) 0}details{margin:var(--gap) 0;overflow-wrap:anywhere}summary{cursor:pointer}.small{font-size:var(--font-size-xs)}
</style>
