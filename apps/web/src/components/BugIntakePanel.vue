<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, getJson, postJson } from '@/lib/api'

// Bug reports that reached GitHub. A maintainer label is the moderation gate: only issues labelled bug-report and accepted become tasks.
interface Created { number: number; card_id: number; urgency: string }
interface Waiting { number: number; title: string; url: string | null }
interface Intake { enabled: boolean; repository: string; checked_at: number | null; error: string | null; created: Created[]; waiting: Waiting[]; already: number }

const data = ref<Intake | null>(null)
const busy = ref(false), error = ref('')
const when = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleString() : 'not yet')
const safe = (u: string | null, repo: string) => !!u && u.startsWith(`https://github.com/${repo}/`)
function message(e: unknown) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return 'Operator sign-in is required.'
  return e instanceof Error ? e.message : 'That did not complete.'
}
async function load() {
  try { data.value = await getJson<Intake>('/api/bug-reports/intake'); error.value = '' }
  catch (e) { error.value = message(e) }
}
async function refresh() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { data.value = await postJson<Intake>('/api/bug-reports/intake/refresh') }
  catch (e) { error.value = message(e) }
  finally { busy.value = false }
}
onMounted(load)
</script>

<template>
  <section id="bug-reports" class="card bug-intake" aria-labelledby="bug-intake-title">
    <h2 id="bug-intake-title" class="section-title">Bug reports</h2>
    <p class="muted lead">Reports from the bug icon arrive as GitHub issues on {{ data?.repository ?? 'the official repository' }}. An issue becomes a Backlog task only when a maintainer labels it <code>bug-report</code> and <code>accepted</code>; add <code>break-fix</code> when it blocks people and needs a release now, otherwise it is staged for the next release.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="data && !data.enabled" class="small" data-testid="intake-off">Intake is off. To have accepted reports turned into tasks, set <code>MAC_CONTROL_BUG_INTAKE_ENABLED=true</code> and restart the service.</p>
    <template v-if="data?.enabled">
      <p class="small" data-testid="intake-status">Last checked: {{ when(data.checked_at) }}. {{ data.created.length }} new task{{ data.created.length === 1 ? '' : 's' }} this pass, {{ data.already }} already handled.</p>
      <p v-if="data.error" class="notice-warn" role="alert">{{ data.error }}</p>
      <div class="actions"><button class="btn" :disabled="busy" @click="refresh">Check GitHub now</button></div>
      <h3 v-if="data.created.length">New tasks</h3>
      <ul v-if="data.created.length" class="plain" data-testid="intake-created">
        <li v-for="c in data.created" :key="c.number">Issue #{{ c.number }} ({{ c.urgency === 'blocker' ? 'break-fix' : 'non-essential' }}) · <RouterLink :to="`/tasks?card=${c.card_id}`">open task #{{ c.card_id }}</RouterLink></li>
      </ul>
      <h3 v-if="data.waiting.length">Needs moderation</h3>
      <p v-if="data.waiting.length" class="muted small">Nothing runs from these until a maintainer adds the <code>accepted</code> label on GitHub.</p>
      <ul v-if="data.waiting.length" class="plain" data-testid="intake-waiting">
        <li v-for="w in data.waiting" :key="w.number">#{{ w.number }} {{ w.title }} <a v-if="safe(w.url, data.repository)" :href="w.url!" target="_blank" rel="noopener noreferrer">view on GitHub</a></li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.bug-intake h3 { margin: 0; font-size: var(--font-size); font-weight: var(--font-weight-strong); }
.bug-intake p { margin: 0; }
.plain { margin: 0; padding-left: 1.2rem; display: flex; flex-direction: column; gap: var(--gap-xs); }
.actions { display: flex; gap: var(--gap-sm); flex-wrap: wrap; }
</style>
