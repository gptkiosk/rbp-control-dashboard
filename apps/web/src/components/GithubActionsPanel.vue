<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'

// Drafts waiting for a decision. Hermes can only draft; nothing runs until the operator has read the exact preview and confirms it here.
interface Preview { kind: string; repo: string; destination: string; payload: Record<string, unknown> }
interface Pending { id: string; fingerprint: string; preview: Preview; state: string }

const actions = ref<Pending[]>([])
const writesEnabled = ref(true)
const confirmed = ref<Record<string, boolean>>({})
const busy = ref(''), error = ref(''), done = ref<{ id: string; url: string | null } | null>(null)

const KIND: Record<string, string> = { repository: 'Create a private repository', issue: 'File an issue', comment: 'Add a comment', pr: 'Open a pull request', merge: 'Merge a pull request', publication: 'Publish a release' }
const safe = (u: string | null | undefined) => !!u && u.startsWith('https://github.com/')
function message(e: unknown) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return 'Operator sign-in is required.'
  return e instanceof Error ? e.message : 'That did not complete.'
}
async function load() {
  try {
    const got = await getJson<{ actions: Pending[]; writes_enabled: boolean }>('/api/github/actions')
    actions.value = got.actions; writesEnabled.value = got.writes_enabled; error.value = ''
  } catch (e) { error.value = message(e) }
}
async function run(a: Pending) {
  if (busy.value || !confirmed.value[a.id]) return
  busy.value = a.id; error.value = ''; done.value = null
  try {
    const out = await postJson<{ state: string; result: { html_url?: string } }>(`/api/github/actions/${a.id}/run`, { fingerprint: a.fingerprint, confirm: true })
    done.value = { id: a.id, url: out.result?.html_url ?? null }
    await load()
  } catch (e) { error.value = message(e) }
  finally { busy.value = '' }
}
onMounted(load)
</script>

<template>
  <section id="github-actions" class="card github-actions" aria-labelledby="github-actions-title">
    <h2 id="github-actions-title" class="section-title">GitHub actions waiting for you</h2>
    <p class="muted lead">Anything that would write to GitHub is drafted first, by you, Hermes or a form, and waits here. Read the exact request, tick the confirmation, then run it once. Hermes and other agents can draft but cannot approve.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="!writesEnabled" class="small" data-testid="writes-off">GitHub writes are off on this install (<code>MAC_CONTROL_GITHUB_WRITES_ENABLED</code>), so nothing here can run.</p>
    <p v-if="done" class="note" role="status" data-testid="action-done">Done. <a v-if="safe(done.url)" :href="done.url!" target="_blank" rel="noopener noreferrer">View it on GitHub</a></p>
    <p v-if="!actions.length" class="muted small">Nothing is waiting.</p>
    <article v-for="a in actions" :key="a.id" class="pending" :data-testid="`action-${a.id}`">
      <h3>{{ KIND[a.preview.kind] ?? a.preview.kind }}: <span class="mono">{{ a.preview.repo }}</span></h3>
      <p v-if="a.preview.kind === 'repository'" class="small">Creates a <strong>private</strong> repository with an initial README commit, and adds it to this install's GitHub list so it can be read and used. It is always private. Deleting a repository is never done from here.</p>
      <p class="muted small">Destination: <span class="mono">{{ a.preview.destination }}</span></p>
      <pre class="log-window" :aria-label="`Exact request for ${a.id}`">{{ JSON.stringify(a.preview.payload, null, 2) }}</pre>
      <label class="check"><input v-model="confirmed[a.id]" type="checkbox" :disabled="!writesEnabled" /><span>I have read this exact request and want it run once.</span></label>
      <div class="actions"><button type="button" class="btn primary" :disabled="!writesEnabled || !confirmed[a.id] || !!busy" @click="run(a)">Approve and run</button></div>
    </article>
  </section>
</template>

<style scoped>
.pending { border: 1px solid var(--surface-border); border-radius: var(--radius); padding: var(--gap); display: flex; flex-direction: column; gap: var(--gap); margin-top: var(--gap); }
.pending h3 { margin: 0; font-size: var(--font-size); font-weight: var(--font-weight-strong); }
.pending p { margin: 0; }
.actions { display: flex; justify-content: flex-end; gap: var(--gap-sm); flex-wrap: wrap; }
label.check { display: flex; flex-direction: row; align-items: flex-start; gap: var(--gap-sm); font-size: var(--font-size-sm); }
label.check input { margin-top: 0.2rem; flex-shrink: 0; }
</style>
