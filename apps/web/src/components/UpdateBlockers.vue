<script setup lang="ts">
// Why an update has to wait, said where the Update button is, with the one action that clears the common case: pause the projects in
// progress. After the update it offers to resume exactly the projects it paused. The parent re-reads the update status on `changed`.
import { computed, onMounted, ref, watch } from 'vue'
import { getJson, postJson } from '@/lib/api'

interface Row { id: number; title: string; state: string }
const props = defineProps<{ blockers: string[]; busy?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const projects = ref<{ in_progress: Row[]; paused_for_update: Row[] } | null>(null)
const working = ref(false), error = ref(''), notice = ref('')
const active = computed(() => projects.value?.in_progress.filter(p => p.state === 'active') ?? [])

async function load() { try { projects.value = await getJson('/api/app-updates/projects') } catch { projects.value = null } }
async function act(path: string, done: (r: Record<string, Row[]>) => string) {
  if (working.value) return
  working.value = true; error.value = ''; notice.value = ''
  try { notice.value = done(await postJson<Record<string, Row[]>>(path, { confirm: true })); await load(); emit('changed') }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { working.value = false }
}
const pause = () => act('/api/app-updates/pause-projects', r => `Paused ${r.paused?.length ?? 0} project(s). Running stories may still finish; the update can start once nothing is running.`)
const resume = () => act('/api/app-updates/resume-projects', r => `Resumed ${r.resumed?.length ?? 0} project(s).`)
onMounted(load)
watch(() => props.blockers.join('|'), load)
</script>
<template>
  <div v-if="blockers.length || projects?.paused_for_update.length" class="update-blockers">
    <div v-if="blockers.length" class="notice-warn blocked" role="status" data-testid="update-blocked">
      <p><strong>Finish or pause this work first, then update.</strong> An update restarts the service, so it waits until nothing is running:</p>
      <ul><li v-for="b in blockers" :key="b">{{ b }}</li></ul>
      <template v-if="active.length">
        <p>Projects in progress: {{ active.map(p => p.title).join(', ') }}.</p>
        <div class="row"><button type="button" class="btn primary" data-action="pause-projects" :disabled="working || busy" @click="pause">{{ working ? 'Pausing…' : `Pause ${active.length === 1 ? 'this project' : `these ${active.length} projects`} for the update` }}</button>
          <span class="muted small">They resume from here after the update.</span></div>
      </template>
      <p class="small">Tasks are on <RouterLink to="/tasks">Tasks</RouterLink>; projects on <RouterLink to="/projects">Projects</RouterLink>. <button type="button" class="link-btn" :disabled="working" @click="emit('changed')">Check again</button></p>
    </div>
    <div v-if="!blockers.length && projects?.paused_for_update.length" class="notice resume" role="status" data-testid="update-resume">
      <p>Paused for the update: {{ projects.paused_for_update.map(p => p.title).join(', ') }}.</p>
      <button type="button" class="btn primary" data-action="resume-projects" :disabled="working || busy" @click="resume">{{ working ? 'Resuming…' : 'Resume them' }}</button>
    </div>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
  </div>
</template>
<style scoped>
.update-blockers { display: grid; gap: var(--gap-sm); }
.blocked, .resume { display: grid; gap: var(--gap-xs); }
.blocked p, .blocked ul, .resume p { margin: 0; }
.blocked ul { padding-left: 1.2rem; }
.row { display: flex; flex-wrap: wrap; gap: var(--gap-sm); align-items: center; }
.resume { padding: var(--gap-sm) var(--gap); border: 1px solid var(--accent); border-radius: var(--radius); }
.link-btn { background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; font: inherit; text-decoration: underline; }
.small { font-size: var(--font-size-xs); }
</style>
