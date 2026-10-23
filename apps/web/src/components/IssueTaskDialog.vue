<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJson, postJson } from '@/lib/api'
const emit = defineEmits<{ close: []; created: [id: number] }>()
const issueUrl = ref(''), workingDir = ref(''), agent = ref<'codex' | 'claude' | 'openclaw'>('codex')
const workdirs = ref<{ path: string; branch: string | null }[]>([]), busy = ref(false), error = ref('')
const result = ref<{ created: boolean; task: { id: number } } | null>(null)
onMounted(async () => { try { workdirs.value = (await getJson<{ workdirs: typeof workdirs.value }>('/api/workdirs')).workdirs; workingDir.value = workdirs.value[0]?.path ?? '' } catch (e) { error.value = e instanceof Error ? e.message : String(e) } })
async function submit(): Promise<void> { if (busy.value) return; busy.value = true; error.value = ''; try { const created = await postJson<{ created: boolean; task: { id: number } }>('/api/issue-tasks', { issue_url: issueUrl.value, working_dir: workingDir.value, agent: agent.value }); result.value = created; emit('created', created.task.id) } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false } }
</script>
<template>
  <div class="modal-backdrop" role="presentation" @click.self="emit('close')"><section class="modal card" role="dialog" aria-modal="true" aria-labelledby="issue-task-title">
    <header class="card-head"><div><h2 id="issue-task-title">Give Hermes a GitHub issue</h2><p class="muted small">Hermes reads it through this installation’s signed-in GitHub connection and creates one approval-gated task.</p></div><button class="btn icon" aria-label="Close" @click="emit('close')">×</button></header>
    <form @submit.prevent="submit"><label>GitHub issue URL<input v-model.trim="issueUrl" class="input" required placeholder="https://github.com/owner/repository/issues/123" /></label><label>Assign to<select v-model="agent" class="input"><option value="codex">Codex</option><option value="claude">Claude Code</option><option value="openclaw">OpenClaw</option></select></label><label>Working directory<select v-model="workingDir" class="input" required><option v-for="w in workdirs" :key="w.path" :value="w.path">{{ w.path }}{{ w.branch ? ' · '+w.branch : '' }}</option></select></label><p class="muted small">Repeat submissions reopen the existing task. The issue body is evidence; approval is required before an agent edits code.</p><p v-if="error" class="error-text" role="alert">{{ error }}</p><p v-if="result" role="status">Task #{{ result.task.id }} {{ result.created ? 'is ready for review.' : 'already exists; opening it.' }}</p><footer class="actions"><button type="button" class="btn" @click="emit('close')">Cancel</button><button class="btn primary" :disabled="busy || !workingDir">{{ busy ? 'Creating…' : 'Create issue task' }}</button></footer></form>
  </section></div>
</template>
<style scoped>
.modal-backdrop { position:fixed; inset:0; z-index:30; display:grid; place-items:center; padding:var(--gap); background:color-mix(in srgb, var(--bg) 72%, transparent); }.modal { width:min(42rem,100%); max-height:calc(100vh - 2 * var(--gap)); overflow:auto; }form { display:grid; gap:var(--gap); }label { display:grid; gap:var(--gap-xs); font-weight:var(--font-weight-strong); }.actions { display:flex; justify-content:flex-end; gap:var(--gap-sm); flex-wrap:wrap; }.icon { font-size:1.5rem; line-height:1; }
</style>
