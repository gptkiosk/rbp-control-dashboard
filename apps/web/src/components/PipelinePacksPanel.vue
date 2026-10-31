<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppSelect from '@/components/AppSelect.vue'
import ManagedItem from '@/components/ManagedItem.vue'
import { deleteJson, getJson, postJson } from '@/lib/api'

// The template store: data-only project templates (published in packs) and the tools they may require, offered from the signed packs release.
// A template is added from a dropdown. Anything this host lacks is named next to it with a link to fix it, never a silent block.
interface Service { id: string; label: string; credential: string | null; ready: boolean }
interface Need { kind: string; id: string; status: string; detail: string; link: string }
interface Offered { id: string; label: string; summary: string; version: string; service: Service | null; installed: string | null; update: boolean
  author: string | null; trust: 'official' | 'community' | null; settings: string[]; needs: Need[]; too_new: boolean }
interface Installed { id: string; label: string; version: string; project_types: string[]; service: Service | null }
interface Tool { id: string; name: string; description: string; app_min: string | null; status: string; detail: string; link: string }
interface Body { repository: string; release: string | null; error: string | null; available: Offered[]; installed: Installed[]; tools?: Record<string, Tool[]> }

const KINDS: [string, string][] = [['agents', 'Agents'], ['system_tools', 'System tools'], ['providers', 'Providers'], ['checks', 'Dashboard checks'], ['services', 'Services']]
const STATUS: Record<string, string> = { ready: 'Ready', missing: 'Not set up', unknown: 'Needs a newer dashboard', info: 'Listed' }
const body = ref<Body | null>(null), loading = ref(true), busy = ref(''), error = ref(''), notice = ref(''), choice = ref(''), view = ref<'templates' | 'tools'>('templates')
const addable = computed(() => (body.value?.available ?? []).filter(p => !p.installed))
const chosen = computed(() => addable.value.find(p => p.id === choice.value) ?? null)
const offerFor = (id: string) => body.value?.available.find(p => p.id === id) ?? null
const needs = (s: Service | null) => (s && !s.ready ? `Needs your ${s.label} credential. Save it in General → Private credentials first.` : '')
const trustWord = (p: Offered) => (p.trust === 'official' ? 'Official' : p.trust === 'community' ? 'Community' : 'Unlabelled') + (p.author ? `, by ${p.author}` : '')
const kinds = computed(() => KINDS.filter(([k]) => body.value?.tools?.[k]?.length))
const lacking = (p: Offered | null) => (p?.needs ?? []).filter(n => n.kind !== 'app')
const linkFor = (n: { link: string }) => (n.link.startsWith('/profile') ? n.link : '')

async function load(refresh = false) {
  loading.value = true
  try {
    body.value = await getJson<Body>(`/api/pipeline-packs${refresh ? '?refresh=true' : ''}`)
    if (!addable.value.some(p => p.id === choice.value)) choice.value = addable.value[0]?.id ?? ''
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { loading.value = false }
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
  <section id="pipeline-packs" class="card packs" aria-labelledby="pipeline-packs-title">
    <header class="head">
      <h3 id="pipeline-packs-title">Template store</h3>
      <button type="button" class="btn small-btn" :disabled="loading || !!busy" @click="load(true)">Check the store</button>
    </header>
    <p class="muted small">Project templates for one kind of deliverable, such as a upubhub class. A template's plan, checks and sign-offs stay fixed; you choose only its settings when you start a project. Templates are data only and never run code on this host. They come signed from <code>{{ body?.repository ?? 'the template repository' }}</code>.</p>
    <nav class="tabs" role="tablist" aria-label="Template store sections">
      <button type="button" role="tab" class="tab" :class="{ on: view === 'templates' }" :aria-selected="view === 'templates'" data-view="templates" @click="view = 'templates'">Templates</button>
      <button type="button" role="tab" class="tab" :class="{ on: view === 'tools' }" :aria-selected="view === 'tools'" data-view="tools" @click="view = 'tools'">Tools</button>
    </nav>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>
    <p v-if="notice" class="small" role="status">{{ notice }}</p>
    <p v-if="loading && !body" class="muted small">Loading…</p>
    <template v-if="body">
      <p v-if="body.error" class="notice-warn small" role="status" data-testid="packs-error">{{ body.error }}</p>
      <div v-show="view === 'templates'" role="tabpanel" aria-label="Templates" class="panel">
        <div v-if="!body.error && addable.length" class="add" data-testid="packs-add">
          <label class="pick">Add a template
            <AppSelect v-model="choice" aria-label="Template to add" :disabled="!!busy">
              <option v-for="p in addable" :key="p.id" :value="p.id" :data-description="p.summary">{{ p.label }} · {{ p.version }}</option>
            </AppSelect>
          </label>
          <button type="button" class="btn primary" :disabled="!chosen || !!busy || !!needs(chosen.service) || chosen.too_new" data-action="install" @click="chosen && install(chosen.id)">{{ busy === chosen?.id ? 'Adding…' : 'Add' }}</button>
          <div v-if="chosen" class="detail" data-testid="packs-detail">
            <p class="small"><span class="badge" :data-trust="chosen.trust">{{ trustWord(chosen) }}</span> · version {{ chosen.version }}</p>
            <p v-if="chosen.summary" class="muted small">{{ chosen.summary }}</p>
            <p v-if="chosen.settings?.length" class="small" data-testid="packs-settings">Settings you choose: {{ chosen.settings.join(', ') }}.</p>
            <p v-if="needs(chosen.service)" class="small" data-testid="packs-needs">{{ needs(chosen.service) }} <RouterLink to="/profile#credentials-profile">Open Private credentials</RouterLink></p>
            <p v-if="chosen.too_new" class="notice-warn small" data-testid="packs-too-new">{{ chosen.needs?.find(n => n.kind === 'app')?.detail }} <RouterLink to="/profile#updates">Check for updates</RouterLink></p>
            <template v-if="lacking(chosen).length">
              <p class="small">You can add it now; projects that use it wait for:</p>
              <ul class="needs small" data-testid="packs-lacking">
                <li v-for="n in lacking(chosen)" :key="n.kind + n.id">{{ n.detail }} <RouterLink v-if="linkFor(n)" :to="linkFor(n)">Fix this</RouterLink></li>
              </ul>
            </template>
          </div>
        </div>
        <p v-else-if="!body.error && !body.installed.length" class="muted small" data-testid="packs-none">No templates are published yet.</p>
        <ul v-if="body.installed.length" class="items">
          <ManagedItem v-for="p in body.installed" :key="p.id" :data-pack="p.id" :name="p.label" :mark="needs(p.service) ? 'warn' : 'ok'"
            :word="offerFor(p.id)?.update ? 'update available' : 'installed'" :version="p.version" :latest="offerFor(p.id)?.update ? offerFor(p.id)!.version : null"
            :detail="needs(p.service) || `Project type${p.project_types.length === 1 ? '' : 's'}: ${p.project_types.join(', ')}`" :busy="busy === p.id" health-disabled>
            <button v-if="offerFor(p.id)?.update" type="button" class="btn primary" :disabled="!!busy || offerFor(p.id)!.too_new" data-action="update" @click="install(p.id)">Update to {{ offerFor(p.id)!.version }}</button>
            <button type="button" class="btn" :disabled="!!busy" data-action="remove" @click="remove(p)">Remove</button>
          </ManagedItem>
        </ul>
      </div>
      <div v-show="view === 'tools'" role="tabpanel" aria-label="Tools" class="panel" data-testid="packs-tools">
        <p class="muted small">The tools a template may require, and whether this host has them. A template that needs something else waits for it to be added to this list.</p>
        <p v-if="!kinds.length" class="muted small">The store has not listed its tools yet.</p>
        <section v-for="[kind, title] in kinds" :key="kind" class="kind">
          <h4>{{ title }}</h4>
          <ul class="tools">
            <li v-for="t in body.tools![kind]" :key="t.id" :data-tool="t.id">
              <div class="tool-head"><strong>{{ t.name }}</strong> <code>{{ t.id }}</code><span class="status small" :data-status="t.status">{{ STATUS[t.status] ?? t.status }}</span></div>
              <p class="muted small">{{ t.description }}</p>
              <p v-if="t.status === 'missing' || t.status === 'unknown'" class="small">{{ t.detail }} <RouterLink v-if="linkFor(t)" :to="linkFor(t)">Fix this</RouterLink></p>
            </li>
          </ul>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.packs { display: grid; gap: var(--gap-sm); min-width: 0; }
h3, h4 { margin: 0; }
h4 { font-size: var(--font-size-sm); }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--gap); }
.small { font-size: var(--font-size-xs); margin: 0; }
.panel { display: grid; gap: var(--gap-sm); min-width: 0; }
.tabs { display: flex; gap: var(--gap-xs); border-bottom: 1px solid var(--surface-border); }
.tab { padding: var(--gap-xs) var(--gap-sm); border: 0; border-bottom: 2px solid transparent; background: none; color: var(--text-muted); font: inherit; cursor: pointer; }
.tab.on { color: var(--text); border-bottom-color: var(--accent); font-weight: var(--font-weight-strong); }
.items, .tools { display: grid; gap: var(--gap-sm); padding: 0; margin: 0; list-style: none; }
.add { display: flex; flex-wrap: wrap; align-items: end; gap: var(--gap-sm); }
.add .pick { display: grid; gap: var(--gap-xs); flex: 1 1 16rem; min-width: 0; }
.detail { flex-basis: 100%; display: grid; gap: var(--gap-xs); min-width: 0; }
.needs { margin: 0; padding-left: var(--gap); }
.badge { font-weight: var(--font-weight-strong); }
.kind { display: grid; gap: var(--gap-xs); }
.tools li { display: grid; gap: 2px; min-width: 0; padding: var(--gap-xs) 0; border-bottom: 1px solid var(--surface-border); }
.tool-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--gap-xs); }
.status { margin-left: auto; color: var(--text-muted); }
.status[data-status="ready"] { color: var(--ok); }
.status[data-status="missing"], .status[data-status="unknown"] { color: var(--warn); }
.small-btn { padding: 0 var(--gap-sm); }
</style>
