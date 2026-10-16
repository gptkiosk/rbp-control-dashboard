<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
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
    <form class="form" @submit.prevent="makePreview">
      <header class="head">
        <div class="intro">
          <span class="mark"><AppIcon name="bug" size="lg" /></span>
          <div>
            <h2 id="bug-report-title" class="section-title">Report a bug</h2>
            <p class="hint">Say what went wrong and what you expected.</p>
          </div>
        </div>
        <button type="button" class="btn close" aria-label="Close" @click="close"><AppIcon name="close" /></button>
      </header>

      <template v-if="filed">
        <p role="status">Thanks. Your report was filed on GitHub.</p>
        <p><a v-if="safeUrl(filed.url, caps?.repository)" :href="filed.url" target="_blank" rel="noopener noreferrer">View the issue on GitHub</a></p>
        <div class="actions"><button type="button" class="btn primary" @click="reset(); close()">Close</button></div>
      </template>

      <template v-else>
        <p class="muted small">You will see exactly what is sent before anything leaves this page. Paths, emails, addresses and anything that looks like a key are removed first.</p>
        <p v-if="caps" class="mode small" data-testid="bug-mode">{{ caps.reason }}</p>
        <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>

        <div class="field"><label for="bug-title">Short title</label><input id="bug-title" v-model="form.title" class="input" maxlength="120" required /></div>
        <div class="field"><label for="bug-what">What happened</label><textarea id="bug-what" v-model="form.what" class="input" rows="4" maxlength="3000" required /></div>
        <div class="field"><label for="bug-expected">What you expected</label><textarea id="bug-expected" v-model="form.expected" class="input" rows="2" maxlength="2000" /></div>
        <div class="field"><label for="bug-steps">Steps to reproduce</label><textarea id="bug-steps" v-model="form.steps" class="input" rows="3" maxlength="3000" /></div>
        <div class="field"><label for="bug-impact">How much does it affect you?</label>
          <select id="bug-impact" v-model="form.impact" class="input"><option v-for="[v, l] in IMPACTS" :key="v" :value="v">{{ l }}</option></select>
        </div>
        <label class="check"><input v-model="includeEnvironment" type="checkbox" /><span>Include the product version, system type and which agent runtimes are installed</span></label>

        <section v-if="preview" class="preview" aria-label="What will be sent">
          <h3 class="preview-title">This is what will be sent</h3>
          <p class="mono small">{{ preview.title }}</p>
          <pre class="log-window" data-testid="bug-preview-body">{{ preview.body }}</pre>
          <p v-if="preview.scrubbed.length" class="muted small" data-testid="bug-scrubbed">Removed before sending: {{ preview.scrubbed.join('; ') }}.</p>
          <p v-if="preview.truncated" class="muted small">The text was shortened to fit a link; you can add the rest on GitHub.</p>
          <label v-if="preview.mode === 'direct'" class="check"><input v-model="confirmed" type="checkbox" /><span>I have read this and want it filed on GitHub as my signed-in account.</span></label>
          <p v-else class="muted small">This opens GitHub in a new tab with the report filled in. You submit it there with your own GitHub account.</p>
        </section>

        <div class="actions">
          <button type="button" class="btn" @click="close">Cancel</button>
          <button type="submit" class="btn" :class="{ primary: !preview }" :disabled="!canPreview">Preview what will be sent</button>
          <button v-if="preview && preview.mode === 'direct'" type="button" class="btn primary" :disabled="!confirmed || busy" @click="file">Send to GitHub</button>
          <a v-if="preview && preview.mode !== 'direct' && safeUrl(preview.url, preview.repository)" class="btn primary" :href="preview.url" target="_blank" rel="noopener noreferrer">Open GitHub to submit</a>
        </div>
      </template>
    </form>
  </ModalShell>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--gap); padding: var(--gap-lg); }
.head { display: flex; align-items: center; justify-content: space-between; gap: var(--gap); }
.intro { display: flex; gap: var(--gap); align-items: center; min-width: 0; }
.intro .hint { margin: var(--gap-xs) 0 0; color: var(--text-muted); font-size: var(--font-size-sm); }
.mark { display: flex; align-items: center; justify-content: center; flex-shrink: 0; width: var(--dialog-icon-size); height: var(--dialog-icon-size); color: var(--accent); background: var(--accent-soft); border: 1px solid var(--select-border); border-radius: var(--radius); }
.close { width: var(--dialog-icon-size); min-width: var(--dialog-icon-size); padding: 0; }
p { margin: 0; }
.mode { padding: var(--gap-sm) var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); background: var(--accent-soft); }
.field { display: flex; flex-direction: column; gap: var(--gap-xs); min-width: 0; }
.field > label { font-size: var(--font-size-sm); font-weight: var(--font-weight-strong); color: var(--text-muted); }
.field .input { padding: var(--gap-sm) var(--gap); }
.check { display: flex; align-items: flex-start; gap: var(--gap-sm); font-size: var(--font-size-sm); }
.check input { margin-top: 0.2rem; flex-shrink: 0; }
.preview { display: flex; flex-direction: column; gap: var(--gap-sm); padding: var(--gap); border: 1px solid var(--select-border); border-radius: var(--radius); background: var(--glass-bg); }
.preview-title { margin: 0; font-size: var(--font-size); font-weight: var(--font-weight-strong); }
.actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: var(--gap-sm); padding-top: var(--gap-lg); border-top: 1px solid var(--glass-border); }
.actions .btn { min-height: var(--select-height); text-decoration: none; }
@media (max-width: 600px) {
  .form { padding: var(--gap); }
  .actions { padding-top: var(--gap); }
  .actions .btn { flex: 1 1 100%; }
}
</style>
