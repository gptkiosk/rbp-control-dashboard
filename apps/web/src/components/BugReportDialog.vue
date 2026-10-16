<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ModalShell from '@/components/ModalShell.vue'
import { ApiError, getJson, postJson } from '@/lib/api'
import { useBugReportStore } from '@/stores/bugReport'

interface Caps { repository: string; mode: 'direct' | 'prefilled'; reason: string }
interface Preview { title: string; body: string; scrubbed: string[]; url: string; truncated: boolean; mode: 'direct' | 'prefilled'; reason: string; repository: string }

const store = useBugReportStore()
const route = useRoute()
const caps = ref<Caps | null>(null)
const form = ref({ title: '', what: '', expected: '', steps: '', impact: 'annoying' })
const includeEnvironment = ref(true)
const preview = ref<Preview | null>(null)
const confirmed = ref(false)
const busy = ref(false)
const error = ref('')
const filed = ref<{ url: string } | null>(null)

const IMPACTS: [string, string][] = [['blocks', 'Blocks my work'], ['annoying', 'Annoying'], ['idea', 'Idea or small improvement']]
const safeUrl = (u: string | undefined, repo: string | undefined) => !!u && !!repo && u.startsWith(`https://github.com/${repo}/`)
const canPreview = computed(() => form.value.title.trim().length > 0 && form.value.what.trim().length > 0 && !busy.value)

function message(e: unknown): string {
  if (e instanceof ApiError) return e.message
  return e instanceof Error ? e.message : String(e)
}
function payload() { return { ...form.value, page: route.path, include_environment: includeEnvironment.value } }

watch(() => store.open, async (isOpen) => {
  if (!isOpen) return
  error.value = ''; preview.value = null; filed.value = null; confirmed.value = false
  try { caps.value = await getJson<Caps>('/api/bug-reports/capabilities') } catch { caps.value = null }
})

async function makePreview() {
  busy.value = true; error.value = ''; confirmed.value = false
  try { preview.value = await postJson<Preview>('/api/bug-reports/preview', payload()) }
  catch (e) { error.value = message(e) }
  finally { busy.value = false }
}
async function file() {
  busy.value = true; error.value = ''
  try {
    const done = await postJson<{ state: string; url: string }>('/api/bug-reports/file', { ...payload(), confirm: true })
    filed.value = { url: done.url }
  } catch (e) { error.value = message(e) }
  finally { busy.value = false }
}
function close() { store.close() }
function reset() { form.value = { title: '', what: '', expected: '', steps: '', impact: 'annoying' }; preview.value = null; filed.value = null; confirmed.value = false }
</script>

<template>
  <ModalShell v-if="store.open" labelledby="bug-report-title" @close="close">
    <div class="bug-dialog">
      <h2 id="bug-report-title" class="dialog-title">Report a bug</h2>

      <template v-if="filed">
        <p role="status">Thanks. Your report was filed on GitHub.</p>
        <p><a v-if="safeUrl(filed.url, caps?.repository)" :href="filed.url" target="_blank" rel="noopener noreferrer">View the issue on GitHub</a></p>
        <div class="actions"><button type="button" class="btn" @click="reset(); close()">Close</button></div>
      </template>

      <template v-else>
        <p class="muted small">Describe what went wrong. You will see exactly what is sent before anything leaves this page. Paths, emails, addresses and anything that looks like a key are removed first.</p>
        <p v-if="caps" class="muted small" data-testid="bug-mode">{{ caps.reason }}</p>
        <p v-if="error" class="error-text" role="alert">{{ error }}</p>

        <form class="grid" @submit.prevent="makePreview">
          <label>Short title<input v-model="form.title" class="input" maxlength="120" required /></label>
          <label>What happened<textarea v-model="form.what" class="input" rows="4" maxlength="3000" required /></label>
          <label>What you expected<textarea v-model="form.expected" class="input" rows="2" maxlength="2000" /></label>
          <label>Steps to reproduce<textarea v-model="form.steps" class="input" rows="3" maxlength="3000" /></label>
          <label>How much does it affect you?
            <select v-model="form.impact" class="input"><option v-for="[v, l] in IMPACTS" :key="v" :value="v">{{ l }}</option></select>
          </label>
          <label class="check"><input v-model="includeEnvironment" type="checkbox" />Include the product version, system type and which agent runtimes are installed</label>
          <div class="actions"><button type="submit" class="btn" :disabled="!canPreview">Preview what will be sent</button></div>
        </form>

        <section v-if="preview" class="preview" aria-label="What will be sent">
          <h3>This is what will be sent</h3>
          <p class="mono small">{{ preview.title }}</p>
          <pre class="body" data-testid="bug-preview-body">{{ preview.body }}</pre>
          <p v-if="preview.scrubbed.length" class="muted small" data-testid="bug-scrubbed">Removed before sending: {{ preview.scrubbed.join('; ') }}.</p>
          <p v-if="preview.truncated" class="muted small">The text was shortened to fit a link; you can add the rest on GitHub.</p>

          <template v-if="preview.mode === 'direct'">
            <label class="check"><input v-model="confirmed" type="checkbox" />I have read this and want it filed on GitHub as my signed-in account.</label>
            <div class="actions"><button type="button" class="btn primary" :disabled="!confirmed || busy" @click="file">Send to GitHub</button></div>
          </template>
          <template v-else>
            <p class="muted small">This opens GitHub in a new tab with the report filled in. You submit it there with your own GitHub account.</p>
            <div class="actions">
              <a v-if="safeUrl(preview.url, preview.repository)" class="btn primary" :href="preview.url" target="_blank" rel="noopener noreferrer">Open GitHub to submit</a>
            </div>
          </template>
        </section>
        <div class="actions"><button type="button" class="btn" @click="close">Cancel</button></div>
      </template>
    </div>
  </ModalShell>
</template>

<style scoped>
.bug-dialog { display: flex; flex-direction: column; gap: var(--gap); max-width: 44rem; }
.grid { display: flex; flex-direction: column; gap: var(--gap); }
label { display: flex; flex-direction: column; gap: var(--gap-xs); }
label.check { flex-direction: row; align-items: flex-start; gap: var(--gap-sm); }
.actions { display: flex; gap: var(--gap); flex-wrap: wrap; }
.preview { border: 1px solid var(--surface-border); border-radius: var(--radius); padding: var(--gap); display: flex; flex-direction: column; gap: var(--gap); }
.body { white-space: pre-wrap; max-height: 16rem; overflow: auto; margin: 0; font-size: var(--text-sm, 0.85rem); }
</style>
