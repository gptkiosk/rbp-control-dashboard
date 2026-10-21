<script setup lang="ts">
// Amend the brief of a project in progress. The approved plan and its scope stay frozen; stories that start from now on follow the
// amendments (newest first), and the full brief file keeps every one.
import { ref } from 'vue'
import { postJson } from '@/lib/api'
import type { Project } from '@/lib/projects'

const props = defineProps<{ projectId: number; amendments: { id: number; text: string; actor: string; created_at: number }[] }>()
const emit = defineEmits<{ updated: [project: Project] }>()
const text = ref(''), busy = ref(false), error = ref(''), notice = ref('')
const when = (t: number) => new Date(t * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

async function add() {
  if (!text.value.trim() || busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    emit('updated', await postJson<Project>(`/api/projects/${props.projectId}/amendments`, { text: text.value.trim() }))
    text.value = ''; notice.value = 'Amendment added. Stories that start from now on follow it.'
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
</script>
<template>
  <section class="amend full" aria-labelledby="amend-title" data-testid="brief-amendments">
    <h3 id="amend-title">Amend brief</h3>
    <p class="muted small">The approved plan and its scope stay as they are. Stories that start after you add an amendment follow it, newest first, where it differs from the brief. Use it for corrections such as originality rules or answered questions.</p>
    <ol v-if="amendments.length" class="list">
      <li v-for="a in amendments" :key="a.id"><span class="muted small">{{ when(a.created_at) }}</span><p>{{ a.text }}</p></li>
    </ol>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <label>New amendment<textarea v-model="text" class="input" rows="3" maxlength="4000" placeholder="For example: all characters are original; no button eyes on any face." data-test="amend-text" /></label>
    <div class="actions"><button type="button" class="btn primary" data-action="amend" :disabled="busy || !text.trim()" @click="add">{{ busy ? 'Adding…' : 'Add amendment' }}</button><span class="muted small">{{ text.length }} / 4000</span></div>
  </section>
</template>
<style scoped>
.amend { display: grid; gap: var(--gap-sm); border-top: 1px solid var(--surface-border); padding-top: var(--gap); }
h3 { margin: 0; }
p { margin: 0; }
.list { display: grid; gap: var(--gap-sm); margin: 0; padding-left: 1.2rem; }
.list p { white-space: pre-wrap; overflow-wrap: anywhere; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-sm); }
.small { font-size: var(--font-size-xs); }
</style>
