<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import TemplateIcon from '@/components/TemplateIcon.vue'
import { deleteJson, getJson, postFile, postJson } from '@/lib/api'
import { categoryFor, splitLabel } from '@/lib/templateStore'

// The template store (Settings → Template store): data-only project templates (published in packs) and the tools they may
// require, offered from the signed packs release. Laid out like an app store: what is installed on top, what is available
// under it, then the tools. Every action is on the card; anything this host lacks is named on the card with a link to fix
// it, never a silent block. Templates update apart from the dashboard: Update all, What's new from each version's notes, and
// switching back to a version kept on this host. An own template can be imported unvetted, after the operator accepts the risk.
interface Service { id: string; label: string; credential: string | null; ready: boolean }
interface Need { kind: string; id: string; status: string; detail: string; link: string }
interface Offered { id: string; label: string; summary: string; version: string; service: Service | null; installed: string | null; update: boolean
  author: string | null; trust: 'official' | 'community' | null; settings: string[]; needs: Need[]; too_new: boolean; changes?: string; local_conflict?: boolean }
interface Installed { id: string; label: string; version: string; project_types: string[]; service: Service | null
  versions?: string[]; local?: boolean; imported_at?: string | null; summary?: string; changes?: string }
interface Tool { id: string; name: string; description: string; app_min: string | null; status: string; detail: string; link: string }
interface Body { repository: string; release: string | null; error: string | null; available: Offered[]; installed: Installed[]; tools?: Record<string, Tool[]> }

const KINDS: [string, string][] = [['agents', 'Agents'], ['system_tools', 'System tools'], ['providers', 'Providers'], ['checks', 'Dashboard checks'], ['services', 'Services']]
const STATUS: Record<string, string> = { ready: 'Ready', missing: 'Not set up', unknown: 'Needs a newer dashboard', info: 'Listed' }
const body = ref<Body | null>(null), loading = ref(true), busy = ref(''), error = ref(''), notice = ref(''), query = ref('')
const importOpen = ref(false), acceptRisk = ref(false), importFile = ref<HTMLInputElement | null>(null)
const emit = defineEmits<{ updates: [number] }>()

const matches = (label: string, summary = '') => !query.value.trim() || `${label} ${summary}`.toLowerCase().includes(query.value.trim().toLowerCase())
const addable = computed(() => (body.value?.available ?? []).filter(p => !p.installed))
const shownAvailable = computed(() => addable.value.filter(p => matches(p.label, p.summary)))
const shownInstalled = computed(() => (body.value?.installed ?? []).filter(p => matches(p.label, offerFor(p.id)?.summary)))
const offerFor = (id: string) => body.value?.available.find(p => p.id === id) ?? null
const needs = (s: Service | null) => (s && !s.ready ? `Needs your ${s.label} credential. Save it in General → Private credentials first.` : '')
const trustWord = (p: Offered) => (p.trust === 'official' ? 'Official' : p.trust === 'community' ? 'Community' : 'Unlabelled') + (p.author ? `, by ${p.author}` : '')
const kinds = computed(() => KINDS.filter(([k]) => body.value?.tools?.[k]?.length))
const lacking = (p: Offered | null) => (p?.needs ?? []).filter(n => n.kind !== 'app')
const linkFor = (n: { link: string }) => (n.link.startsWith('/profile') ? n.link : '')
const title = (label: string) => splitLabel(label).title
const tagline = (label: string) => splitLabel(label).tagline
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
const updates = computed(() => (body.value?.installed ?? []).filter(p => offerFor(p.id)?.update && !offerFor(p.id)!.too_new && !p.local))
const older = (p: Installed) => (p.versions ?? []).filter(v => v !== p.version)

async function load(refresh = false) {
  loading.value = true
  try { body.value = await getJson<Body>(`/api/pipeline-packs${refresh ? '?refresh=true' : ''}`); emit('updates', updates.value.length) }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { loading.value = false }
}
// One template after another, so each result is reported and a failure does not hide the rest.
async function updateAll() {
  if (busy.value || !updates.value.length) return
  error.value = ''; notice.value = ''
  const done: string[] = [], failed: string[] = []
  for (const p of [...updates.value]) {
    busy.value = p.id
    try { const r = await postJson<{ installed: string; version: string }>('/api/pipeline-packs/install', { id: p.id }); done.push(`${p.label} ${r.version}`) }
    catch (e) { failed.push(`${p.label}: ${e instanceof Error ? e.message : String(e)}`) }
  }
  busy.value = ''
  notice.value = done.length ? `Updated ${done.join(', ')}.` : ''
  error.value = failed.length ? `Not updated: ${failed.join(' ')}` : ''
  await load()
}
async function useVersion(p: Installed, version: string) {
  if (busy.value) return
  busy.value = p.id; error.value = ''; notice.value = ''
  try { await postJson(`/api/pipeline-packs/${encodeURIComponent(p.id)}/activate`, { version }); notice.value = `${p.label} now uses version ${version}.`; await load() }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = '' }
}
async function importOwn(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (importFile.value) importFile.value.value = ''
  if (!file || busy.value || !acceptRisk.value) return
  busy.value = 'import'; error.value = ''; notice.value = ''
  try {
    const r = await postFile<{ installed: string; version: string; project_types: string[] }>('/api/pipeline-packs/import?accept_risk=true', file)
    notice.value = `Imported your template ${r.installed} ${r.version}. New project type${r.project_types.length === 1 ? '' : 's'}: ${r.project_types.join(', ')}.`
    importOpen.value = false; acceptRisk.value = false
    await load()
  } catch (err) { error.value = err instanceof Error ? err.message : String(err) } finally { busy.value = '' }
}
async function install(id: string) {
  if (busy.value) return
  busy.value = id; error.value = ''; notice.value = ''
  try {
    const r = await postJson<{ installed: string; version: string; project_types: string[] }>('/api/pipeline-packs/install', { id })
    notice.value = `Added ${r.installed} ${r.version}. New project type${r.project_types.length === 1 ? '' : 's'}: ${r.project_types.join(', ')}.`
    await load()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = '' }
}
async function remove(p: Installed) {
  if (busy.value || !window.confirm(`Remove ${p.label}? Projects already planned keep their plans; new projects can no longer pick its type.`)) return
  busy.value = p.id; error.value = ''; notice.value = ''
  try { await deleteJson(`/api/pipeline-packs/${encodeURIComponent(p.id)}`); notice.value = `Removed ${p.label}.`; await load() }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = '' }
}
onMounted(() => load())
</script>

<template>
  <section id="pipeline-packs" class="store" aria-labelledby="pipeline-packs-title">
    <header class="head">
      <div class="intro">
        <h2 id="pipeline-packs-title">Template store</h2>
        <p class="muted small">Project templates for one kind of deliverable, such as a upubhub class. A template's plan, checks and sign-offs stay fixed; you choose only its settings when you start a project. Templates are data only and never run code on this host. They come signed from <code>{{ body?.repository ?? 'the template repository' }}</code>.</p>
      </div>
      <div class="tools-row">
        <input v-model="query" type="search" class="search" placeholder="Search templates" aria-label="Search templates" data-testid="packs-search" />
        <button type="button" class="btn" :disabled="loading || !!busy" @click="load(true)">Check the store</button>
        <button type="button" class="btn" :aria-expanded="importOpen" data-action="import-open" @click="importOpen = !importOpen">Import a template</button>
      </div>
    </header>
    <section v-if="importOpen" class="import card" aria-labelledby="packs-import-title" data-testid="packs-import">
      <h3 id="packs-import-title">Import your own template</h3>
      <p class="small">Use this to try a template you made, or one someone sent you, before it goes through the store. Your template is
        <strong>not vetted</strong>: the store's security scan, model review and rehearsal have not run, and nothing checked who made it.
        Its text goes to your AI models as planning guidance. It still has to be data only (JSON and Markdown, the same limits as the
        store), and it can never use a store or built-in id. It is marked <strong>Local, unvetted</strong> and never gets store updates;
        import a higher version to replace it. <RouterLink to="/help?topic=template-store">How to make one</RouterLink></p>
      <label class="risk small"><input v-model="acceptRisk" type="checkbox" data-testid="packs-accept-risk" /> I understand this template is unvetted and I use it at my own risk.</label>
      <div class="actions">
        <input ref="importFile" type="file" accept=".zip,.tar.gz,.tgz,application/zip,application/gzip" class="sr-only" data-testid="packs-import-file" @change="importOwn" />
        <button type="button" class="btn primary" :disabled="!acceptRisk || !!busy" data-action="import" @click="importFile?.click()">{{ busy === 'import' ? 'Importing…' : 'Choose a .zip or .tar.gz' }}</button>
        <button type="button" class="btn" @click="importOpen = false; acceptRisk = false">Cancel</button>
      </div>
    </section>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>
    <p v-if="notice" class="small" role="status">{{ notice }}</p>
    <p v-if="loading && !body" class="muted small">Loading…</p>

    <template v-if="body">
      <p v-if="body.error" class="notice-warn small" role="status" data-testid="packs-error">{{ body.error }}</p>

      <section class="shelf" aria-labelledby="packs-installed-title" data-testid="packs-installed">
        <div class="shelf-head">
          <h3 id="packs-installed-title" class="eyebrow">Installed <span class="count">{{ body.installed.length }}</span></h3>
          <button v-if="updates.length" type="button" class="btn primary" :disabled="!!busy" data-action="update-all" @click="updateAll">Update all ({{ updates.length }})</button>
        </div>
        <p v-if="!body.installed.length" class="muted small">No templates yet. Add one from Available below.</p>
        <p v-else-if="!shownInstalled.length" class="muted small">No installed template matches “{{ query }}”.</p>
        <ul v-else class="grid">
          <li v-for="p in shownInstalled" :key="p.id" class="tcard card" :class="{ working: busy === p.id }" :data-pack="p.id">
            <div class="top">
              <TemplateIcon :id="p.id" :title="title(p.label)" />
              <span class="category"><span v-if="p.local" class="local-badge" data-test="local">Local · unvetted</span><template v-else>{{ categoryFor(p.id) }}</template></span>
            </div>
            <h4>{{ title(p.label) }}</h4>
            <p v-if="tagline(p.label)" class="muted small">{{ tagline(p.label) }}</p>
            <p v-if="p.local" class="muted small">Imported {{ p.imported_at?.slice(0, 10) ?? '' }}. Never updated from the store.</p>
            <p class="meta small">
              <span data-test="version"><template v-if="offerFor(p.id)?.update">{{ p.version }} → {{ offerFor(p.id)!.version }}</template><template v-else>{{ p.version }}</template></span>
              · <span :class="offerFor(p.id)?.update ? 'warn' : 'ok'" data-test="word">{{ offerFor(p.id)?.update ? 'update available' : 'installed' }}</span>
            </p>
            <p class="small" :class="{ warn: needs(p.service) }">{{ needs(p.service) || `Project type${p.project_types.length === 1 ? '' : 's'}: ${p.project_types.join(', ')}` }}</p>
            <div v-if="offerFor(p.id)?.update && offerFor(p.id)!.changes" class="whats-new small" data-testid="packs-changes">
              <strong>What's new in {{ offerFor(p.id)!.version }}:</strong> {{ offerFor(p.id)!.changes }}
            </div>
            <label v-if="older(p).length" class="older small">Version
              <select class="input" :value="p.version" :disabled="!!busy" :aria-label="`Version of ${p.label} to use`" data-testid="packs-version" @change="useVersion(p, ($event.target as HTMLSelectElement).value)">
                <option :value="p.version">{{ p.version }} (in use)</option>
                <option v-for="v in older(p)" :key="v" :value="v">{{ v }}</option>
              </select>
            </label>
            <div class="actions">
              <button v-if="offerFor(p.id)?.update" type="button" class="btn primary" :disabled="!!busy || offerFor(p.id)!.too_new" data-action="update" @click="install(p.id)">{{ busy === p.id ? 'Updating…' : `Update to ${offerFor(p.id)!.version}` }}</button>
              <button type="button" class="btn" :disabled="!!busy" data-action="remove" @click="remove(p)">Remove</button>
            </div>
            <div v-if="busy === p.id" class="bar" role="progressbar" :aria-label="`${p.label} is working`" aria-busy="true"><span /></div>
          </li>
        </ul>
      </section>

      <section class="shelf" aria-labelledby="packs-available-title" data-testid="packs-add">
        <h3 id="packs-available-title" class="eyebrow">Available <span class="count">{{ addable.length }}</span></h3>
        <p v-if="!body.error && !addable.length" class="muted small" data-testid="packs-none">{{ body.installed.length ? 'Every published template is installed.' : 'No templates are published yet.' }}</p>
        <p v-else-if="!shownAvailable.length && addable.length" class="muted small">No available template matches “{{ query }}”.</p>
        <ul v-else class="grid">
          <li v-for="p in shownAvailable" :key="p.id" class="tcard card" :class="{ working: busy === p.id }" :data-offer="p.id">
            <div class="top">
              <TemplateIcon :id="p.id" :title="title(p.label)" />
              <span class="category">{{ categoryFor(p.id) }}</span>
            </div>
            <h4>{{ title(p.label) }}</h4>
            <p class="muted small summary">{{ p.summary || tagline(p.label) }}</p>
            <p class="meta small"><span class="badge" :data-trust="p.trust">{{ trustWord(p) }}</span> · version {{ p.version }}</p>
            <p v-if="p.changes" class="small whats-new">What's new: {{ p.changes }}</p>
            <p v-if="p.local_conflict" class="small warn">Your own template uses this id. Remove it to add the store version.</p>
            <p v-if="needs(p.service)" class="small warn" data-testid="packs-needs">{{ needs(p.service) }} <RouterLink to="/profile#credentials-profile">Open Private credentials</RouterLink></p>
            <p v-if="p.too_new" class="notice-warn small" data-testid="packs-too-new">{{ p.needs?.find(n => n.kind === 'app')?.detail }} <RouterLink to="/profile#updates">Check for updates</RouterLink></p>
            <details v-if="p.settings?.length || lacking(p).length" class="more small">
              <summary>Details</summary>
              <p v-if="p.settings?.length" data-testid="packs-settings">Settings you choose: {{ p.settings.join(', ') }}.</p>
              <template v-if="lacking(p).length">
                <p>You can add it now; projects that use it wait for:</p>
                <ul class="needs" data-testid="packs-lacking">
                  <li v-for="n in lacking(p)" :key="n.kind + n.id">{{ n.detail }} <RouterLink v-if="linkFor(n)" :to="linkFor(n)">Fix this</RouterLink></li>
                </ul>
              </template>
            </details>
            <div class="actions">
              <button type="button" class="btn primary" :disabled="!!busy || !!needs(p.service) || p.too_new || p.local_conflict" data-action="install" @click="install(p.id)">{{ busy === p.id ? 'Adding…' : 'Add' }}</button>
              <span v-if="lacking(p).length" class="muted small">{{ plural(lacking(p).length, 'tool') }} to set up</span>
            </div>
            <div v-if="busy === p.id" class="bar" role="progressbar" :aria-label="`${p.label} is being added`" aria-busy="true"><span /></div>
          </li>
        </ul>
      </section>

      <section class="shelf" aria-labelledby="packs-tools-title" data-testid="packs-tools">
        <h3 id="packs-tools-title" class="eyebrow">Tools templates use</h3>
        <p class="muted small">The tools a template may require, and whether this host has them. A template that needs something else waits for it to be added to this list.</p>
        <p v-if="!kinds.length" class="muted small">The store has not listed its tools yet.</p>
        <section v-for="[kind, heading] in kinds" :key="kind" class="kind card">
          <h4>{{ heading }}</h4>
          <ul class="tools">
            <li v-for="t in body.tools![kind]" :key="t.id" :data-tool="t.id">
              <div class="tool-head"><strong>{{ t.name }}</strong> <code>{{ t.id }}</code><span class="status small" :data-status="t.status">{{ STATUS[t.status] ?? t.status }}</span></div>
              <p class="muted small">{{ t.description }}</p>
              <p v-if="t.status === 'missing' || t.status === 'unknown'" class="small">{{ t.detail }} <RouterLink v-if="linkFor(t)" :to="linkFor(t)">Fix this</RouterLink></p>
            </li>
          </ul>
        </section>
      </section>
    </template>
  </section>
</template>

<style scoped>
.store { display: grid; gap: var(--gap-lg); min-width: 0; }
h2, h3, h4 { margin: 0; }
h4 { font-size: var(--font-size); }
.head { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: var(--gap); }
.intro { display: grid; gap: var(--gap-xs); flex: 1 1 28rem; min-width: 0; }
.tools-row { display: flex; flex-wrap: wrap; gap: var(--gap-sm); flex: 0 1 26rem; min-width: 0; }
.search { flex: 1 1 12rem; min-width: 0; min-height: var(--touch-target); padding: 0 var(--gap-sm); border: 1px solid var(--select-border); border-radius: var(--radius); background: var(--select-bg); color: var(--text); font: inherit; }
.small { font-size: var(--font-size-xs); margin: 0; }
.shelf { display: grid; gap: var(--gap-sm); min-width: 0; }
.eyebrow { font-size: var(--font-size-xs); letter-spacing: var(--nav-letter-spacing); text-transform: uppercase; color: var(--text-muted); }
.count { margin-left: var(--gap-xs); font-weight: var(--font-weight); }
.shelf-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--gap-sm); }
.import { display: grid; gap: var(--gap-sm); border-color: var(--warn); }
.import h3 { font-size: var(--font-size); }
.risk { display: flex; align-items: center; gap: var(--gap-xs); }
.local-badge { color: var(--warn); font-weight: var(--font-weight-strong); }
.whats-new { padding: var(--gap-xs) var(--gap-sm); border-radius: var(--radius-sm); background: var(--accent-soft); }
.older { display: flex; align-items: center; gap: var(--gap-xs); color: var(--text-muted); }
.older .input { inline-size: auto; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, var(--store-card-min-width)), 1fr)); gap: var(--gap); padding: 0; margin: 0; list-style: none; }
.tcard { position: relative; display: flex; flex-direction: column; gap: var(--gap-xs); min-width: 0; overflow: hidden; }
.tcard.working { opacity: var(--disabled-opacity); }
.top { display: flex; align-items: start; justify-content: space-between; gap: var(--gap-sm); margin-bottom: var(--gap-xs); }
.category { font-size: var(--font-size-xs); letter-spacing: var(--nav-letter-spacing); text-transform: uppercase; color: var(--text-muted); text-align: right; }
.summary { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.meta { color: var(--text-muted); }
.ok { color: var(--ok); }
.warn { color: var(--warn); }
.badge { font-weight: var(--font-weight-strong); color: var(--text); }
.more summary { cursor: pointer; color: var(--text-muted); }
.more p { margin: var(--gap-xs) 0 0; }
.needs { margin: var(--gap-xs) 0 0; padding-left: var(--gap); }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-sm); margin-top: auto; padding-top: var(--gap-xs); }
.bar { position: absolute; inset: auto 0 0; block-size: var(--meter-height); overflow: hidden; background: var(--accent-soft); }
.bar span { display: block; block-size: 100%; inline-size: 40%; background: var(--accent); animation: slide var(--pulse-duration) ease-in-out infinite; }
@keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
.kind { display: grid; gap: var(--gap-xs); }
.tools { display: grid; gap: var(--gap-sm); padding: 0; margin: 0; list-style: none; }
.tools li { display: grid; gap: 2px; min-width: 0; padding: var(--gap-xs) 0; border-bottom: 1px solid var(--surface-border); }
.tools li:last-child { border-bottom: 0; }
.tool-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--gap-xs); }
.status { margin-left: auto; color: var(--text-muted); }
.status[data-status="ready"] { color: var(--ok); }
.status[data-status="missing"], .status[data-status="unknown"] { color: var(--warn); }
@media (prefers-reduced-motion: reduce) { .bar span { animation: none; inline-size: 100%; } }
</style>
