<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'

// Lets agents commit and push ONE branch of ONE repository for this project. The branch is always project-<id>/<name>; the main branch is never allowed.
interface Clone { dir: string; repo: string; branch: string }
const props = defineProps<{ projectId: number }>()
const clones = ref<Clone[]>([]), repos = ref<string[]>([])
const repo = ref(''), dir = ref(''), slug = ref('setup'), confirmed = ref(false)
const busy = ref(false), error = ref(''), notice = ref('')
const branch = computed(() => `project-${props.projectId}/${slug.value || 'setup'}`)

function message(e: unknown) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return 'Operator sign-in is required.'
  return e instanceof Error ? e.message : 'That did not complete.'
}
async function load() {
  try {
    clones.value = (await getJson<{ clones: Clone[] }>(`/api/projects/${props.projectId}/git-grant`)).clones
    repos.value = ((await getJson<{ repos?: string[] }>('/api/github/status')).repos ?? [])
    if (!repo.value && repos.value.length) repo.value = repos.value[repos.value.length - 1]!
    error.value = ''
  } catch (e) { error.value = message(e) }
}
watch(repo, r => { if (!dir.value || repos.value.some(x => x.split('/')[1] === dir.value)) dir.value = r.split('/')[1] ?? '' })
async function grant() {
  if (busy.value || !confirmed.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    clones.value = (await postJson<{ clones: Clone[] }>(`/api/projects/${props.projectId}/git-grant`, { repo: repo.value, dir: dir.value, slug: slug.value, confirm: true })).clones
    notice.value = 'Agents can now commit and push that branch for this project. They still cannot merge, tag or touch the main branch.'; confirmed.value = false
  } catch (e) { error.value = message(e) }
  finally { busy.value = false }
}
onMounted(load)
watch(() => props.projectId, load)
</script>

<template>
  <details class="card git-access" aria-labelledby="git-access-title">
    <summary id="git-access-title">Repository access for agents</summary>
    <p class="muted small">Setup and story work that commits code needs a grant from you: one repository, one folder under the project's working directory, one branch. The branch is always <code>project-{{ projectId }}/&lt;name&gt;</code>, so the main branch can never be named.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" class="note" role="status">{{ notice }}</p>
    <ul v-if="clones.length" class="plain" data-testid="git-clones">
      <li v-for="c in clones" :key="c.dir"><span class="mono">{{ c.repo }}</span> in <span class="mono">{{ c.dir }}</span> on <span class="mono">{{ c.branch }}</span></li>
    </ul>
    <p v-else class="muted small">No branch access has been granted for this project.</p>
    <form class="grid" @submit.prevent="grant">
      <label>Repository<select v-model="repo" class="input"><option v-for="r in repos" :key="r" :value="r">{{ r }}</option></select></label>
      <label>Folder (a clone directly under the working directory)<input v-model="dir" class="input" maxlength="80" required /></label>
      <label>Branch name<input v-model="slug" class="input" maxlength="40" required /></label>
      <p class="small" data-testid="git-branch">Agents may push only <span class="mono">{{ branch }}</span> of <span class="mono">{{ repo || 'the repository' }}</span>.</p>
      <label class="check"><input v-model="confirmed" type="checkbox" />I have read this and want to give agents push access to exactly that branch.</label>
      <div class="actions"><button type="submit" class="btn" :disabled="!confirmed || busy || !repo || !dir">Grant branch access</button></div>
    </form>
  </details>
</template>

<style scoped>
.grid { display: flex; flex-direction: column; gap: var(--gap); }
label { display: flex; flex-direction: column; gap: var(--gap-xs); }
label.check { flex-direction: row; align-items: flex-start; gap: var(--gap-sm); }
.plain { margin: 0; padding-left: 1.2rem; }
.actions { display: flex; gap: var(--gap); }
</style>
