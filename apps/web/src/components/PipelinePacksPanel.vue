<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppSelect from '@/components/AppSelect.vue'
import ManagedItem from '@/components/ManagedItem.vue'
import { deleteJson, getJson, postJson } from '@/lib/api'

// Optional pipeline packs: data-only project types and guides for one kind of deliverable (such as a upubhub class), offered from the signed
// packs release. A pack for a service needs that service's credential saved first, and says so next to its disabled button.
interface Service { id: string; label: string; credential: string | null; ready: boolean }
interface Offered { id: string; label: string; summary: string; version: string; service: Service | null; installed: string | null; update: boolean }
interface Installed { id: string; label: string; version: string; project_types: string[]; service: Service | null }
interface Body { repository: string; release: string | null; error: string | null; available: Offered[]; installed: Installed[] }

const body = ref<Body | null>(null), loading = ref(true), busy = ref(''), error = ref(''), notice = ref(''), choice = ref('')
const addable = computed(() => (body.value?.available ?? []).filter(p => !p.installed))
const chosen = computed(() => addable.value.find(p => p.id === choice.value) ?? null)
const offerFor = (id: string) => body.value?.available.find(p => p.id === id) ?? null
const needs = (s: Service | null) => (s && !s.ready ? `Needs your ${s.label} credential. Save it in General → Private credentials first.` : '')

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
    notice.value = `Installed ${r.installed} ${r.version}. New project type${r.project_types.length === 1 ? '' : 's'}: ${r.project_types.join(', ')}.`
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
      <h3 id="pipeline-packs-title">Pipeline packs</h3>
      <button type="button" class="btn small-btn" :disabled="loading || !!busy" @click="load(true)">Check for packs</button>
    </header>
    <p class="muted small">Optional project types for one kind of deliverable, such as a upubhub class. A pack is planner guidance and checks only; it never runs code on this host. Packs come signed from <code>{{ body?.repository ?? 'the packs repository' }}</code>.</p>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>
    <p v-if="notice" class="small" role="status">{{ notice }}</p>
    <p v-if="loading && !body" class="muted small">Loading…</p>
    <template v-if="body">
      <p v-if="body.error" class="notice-warn small" role="status" data-testid="packs-error">{{ body.error }}</p>
      <div v-else-if="addable.length" class="add" data-testid="packs-add">
        <label class="pick">Add a pack
          <AppSelect v-model="choice" aria-label="Pipeline pack to add" :disabled="!!busy">
            <option v-for="p in addable" :key="p.id" :value="p.id" :data-description="p.summary">{{ p.label }} · {{ p.version }}</option>
          </AppSelect>
        </label>
        <button type="button" class="btn primary" :disabled="!chosen || !!busy || !!needs(chosen.service)" data-action="install" @click="chosen && install(chosen.id)">{{ busy === chosen?.id ? 'Installing…' : 'Install' }}</button>
        <p v-if="chosen && needs(chosen.service)" class="small" data-testid="packs-needs">{{ needs(chosen.service) }} <RouterLink to="/profile#credentials-profile">Open Private credentials</RouterLink></p>
        <p v-else-if="chosen?.summary" class="muted small">{{ chosen.summary }}</p>
      </div>
      <p v-else-if="!body.installed.length" class="muted small" data-testid="packs-none">No packs are published yet.</p>
      <ul v-if="body.installed.length" class="items">
        <ManagedItem v-for="p in body.installed" :key="p.id" :data-pack="p.id" :name="p.label" :mark="needs(p.service) ? 'warn' : 'ok'"
          :word="offerFor(p.id)?.update ? 'update available' : 'installed'" :version="p.version" :latest="offerFor(p.id)?.update ? offerFor(p.id)!.version : null"
          :detail="needs(p.service) || `Project type${p.project_types.length === 1 ? '' : 's'}: ${p.project_types.join(', ')}`" :busy="busy === p.id" health-disabled>
          <button v-if="offerFor(p.id)?.update" type="button" class="btn primary" :disabled="!!busy" data-action="update" @click="install(p.id)">Update to {{ offerFor(p.id)!.version }}</button>
          <button type="button" class="btn" :disabled="!!busy" data-action="remove" @click="remove(p)">Remove</button>
        </ManagedItem>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.packs { display: grid; gap: var(--gap-sm); }
h3 { margin: 0; }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--gap); }
.small { font-size: var(--font-size-xs); margin: 0; }
.items { display: grid; gap: var(--gap-sm); padding: 0; margin: 0; list-style: none; }
.add { display: flex; flex-wrap: wrap; align-items: end; gap: var(--gap-sm); }
.add .pick { display: grid; gap: var(--gap-xs); flex: 1 1 16rem; min-width: 0; }
.add p { flex-basis: 100%; }
.small-btn { padding: 0 var(--gap-sm); }
</style>
