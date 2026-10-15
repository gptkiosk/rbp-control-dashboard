<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import StackedBars from '@/components/StackedBars.vue'
import { ApiError, deleteJson, getJson, postJson } from '@/lib/api'
import type { ModelProfile, Profiles, RefreshResult } from '@/lib/models'
import { money, seconds, percent } from '@/lib/telemetry'

// What each model can do (facts), how it has actually done here (observed) and what people noted about it. Facts and observed numbers are
// computed; notes are only ever people's, with a source and a date. Refreshing reads OpenRouter's public list and changes nothing else.
const data = ref<Profiles | null>(null)
const result = ref<RefreshResult | null>(null)
const error = ref(''), busy = ref(false)
const note = ref({ model: '', text: '', source: '', date: new Date().toISOString().slice(0, 10) })

async function load() {
  try { data.value = await getJson<Profiles>('/api/models/profiles') } catch { data.value = null }
}
function fail(e: unknown) { error.value = e instanceof ApiError || e instanceof Error ? e.message : 'That did not work.' }
async function refresh() {
  busy.value = true; error.value = ''
  try { result.value = await postJson<RefreshResult>('/api/models/refresh', { confirm: true }); await load() } catch (e) { fail(e) } finally { busy.value = false }
}
async function addNote() {
  busy.value = true; error.value = ''
  try { await postJson('/api/models/notes', note.value); note.value = { ...note.value, model: '', text: '', source: '' }; await load() } catch (e) { fail(e) } finally { busy.value = false }
}
async function removeNote(id: string) {
  busy.value = true; error.value = ''
  try { await deleteJson(`/api/models/notes/${id}`); await load() } catch (e) { fail(e) } finally { busy.value = false }
}
const observed = computed(() => (data.value?.models ?? []).filter(m => m.observed))
const withNotes = computed(() => (data.value?.models ?? []).filter(m => m.notes.length))
const route = (m: ModelProfile) => (m.free === null ? 'not recorded' : m.free ? 'free' : 'paid')
const flags = (m: ModelProfile) => [m.tools ? 'tools' : null, m.structured ? 'structured output' : null, m.reasoning ? 'reasoning' : null].filter(Boolean).join(', ') || '–'
const when = (ts: number) => new Date(ts * 1000).toLocaleDateString()
onMounted(load)
</script>
<template>
  <section v-if="data" class="models" aria-label="Models">
    <h2 class="section-title">Models</h2>
    <p class="muted small">Facts come from the price catalog and OpenRouter's public list; observed numbers come from your own runs; notes are only ever people's, with a source and a date. A model with fewer than {{ data.proven_runs }} runs of a kind is unproven for it.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>

    <StackedBars title="Observed success by model" :parts="[{ key: 'ok', label: 'Succeeded', color: 'var(--ok)' }, { key: 'bad', label: 'Did not succeed', color: 'var(--danger)' }]"
      :rows="observed.map(m => ({ label: `${m.id}${m.observed!.proven ? '' : ' (unproven)'}`, values: { ok: Math.round(m.observed!.runs * m.observed!.success_rate), bad: m.observed!.runs - Math.round(m.observed!.runs * m.observed!.success_rate) }, hint: `${route(m)}, ${percent(m.observed!.success_rate)} of ${m.observed!.runs} runs, median ${seconds(m.observed!.median_seconds)}` }))"
      empty="No runs yet, so nothing is proven for any model." />

    <div class="refresh card">
      <p class="small"><strong>Free models:</strong> {{ data.snapshot ? `${data.snapshot.free} free of ${data.snapshot.count} on OpenRouter, read ${when(data.snapshot.fetched_at)}` : 'the list has not been read yet' }}.
        <button type="button" class="btn" :disabled="busy" @click="refresh">Refresh free models</button></p>
      <div v-if="result" class="small" data-testid="refresh-result">
        <p>Read {{ result.count }} models ({{ result.free }} free). Nothing was changed: adopting or dropping a model is a normal reviewed change.</p>
        <p v-if="result.diff.new_free.length"><strong>New free models:</strong> {{ result.diff.new_free.join(', ') }}</p>
        <p v-if="result.diff.no_longer_free.length"><strong>In the catalog but no longer free or listed:</strong> {{ result.diff.no_longer_free.join(', ') }}</p>
        <p v-if="result.diff.changed.length"><strong>Changed since the last read:</strong> {{ result.diff.changed.map(c => `${c.id} (${c.fields.join(', ')})`).join('; ') }}</p>
        <p v-if="!result.diff.new_free.length && !result.diff.no_longer_free.length && !result.diff.changed.length" class="muted">No differences from the catalog.</p>
      </div>
    </div>

    <details class="card detail" aria-label="Model profiles table">
      <summary>Model profiles: the numbers</summary>
      <div class="table-scroll"><table class="data-table">
        <caption class="sr-only">Model profiles</caption>
        <thead><tr><th>Model</th><th>Route</th><th class="num">Context</th><th>Can do</th><th class="num">Runs</th><th class="num">Success</th><th>Proven for</th><th class="num">Notes</th></tr></thead>
        <tbody><tr v-for="m in data.models" :key="m.id">
          <td :title="m.name">{{ m.id }}</td><td>{{ route(m) }}{{ m.price_in != null && m.free === false ? ` · $${m.price_in}/$${m.price_out} per M` : '' }}</td>
          <td class="num">{{ m.context ? m.context.toLocaleString() : '–' }}</td><td>{{ flags(m) }}</td>
          <td class="num">{{ m.observed?.runs ?? 0 }}</td><td class="num">{{ m.observed ? percent(m.observed.success_rate) : '–' }}</td>
          <td>{{ m.kinds.filter(k => k.proven).map(k => k.kind).join(', ') || (m.observed ? 'unproven' : '–') }}</td><td class="num">{{ m.notes.length }}</td>
        </tr></tbody>
      </table></div>
    </details>

    <details class="card detail" aria-label="Model notes">
      <summary>Notes{{ data.stale_notes ? ` (${data.stale_notes} stale)` : '' }}</summary>
      <ul v-if="withNotes.length" class="notes small">
        <template v-for="m in withNotes" :key="m.id">
          <li v-for="n in m.notes" :key="n.id"><strong>{{ n.model }}</strong>: {{ n.text }} <span class="muted">({{ n.source }}, {{ n.date }}{{ n.stale ? ', stale' : '' }})</span>
            <button type="button" class="btn" :disabled="busy" @click="removeNote(n.id)">Delete</button></li>
        </template>
      </ul>
      <p v-else class="muted small">No notes. Add one only for something you tried or read, with where it came from.</p>
      <form class="note-form" @submit.prevent="addNote">
        <label>Model id<input v-model="note.model" class="input" maxlength="120" required placeholder="for example google/gemma-4-31b-it:free" /></label>
        <label>Note<input v-model="note.text" class="input" maxlength="400" required /></label>
        <label>Source<input v-model="note.source" class="input" maxlength="200" required placeholder="where this came from" /></label>
        <label>Date<input v-model="note.date" class="input" type="date" required /></label>
        <button class="btn primary" :disabled="busy">Add note</button>
      </form>
    </details>
  </section>
</template>
<style scoped>
.models { display: grid; gap: var(--gap); }
h2 { margin: 0; }
.small { font-size: var(--font-size-sm); margin: 0; }
.refresh { gap: var(--gap-sm); }
.notes { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--gap-sm); }
.note-form { display: flex; flex-direction: row; flex-wrap: wrap; gap: var(--gap); align-items: end; }
.note-form label { display: grid; gap: var(--gap-xs); font-size: var(--font-size-sm); }
.detail summary { cursor: pointer; font-weight: 600; }
</style>
