<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getJson } from '@/lib/api'
interface Question { id: string; label: string; prompt: string; required?: boolean; type?: 'integer' | 'choice' | 'multi' | 'boolean' | 'text'; min?: number; max?: number; options?: string[]; default?: unknown; allowed?: string }
interface Intake { questions: Question[]; answer_limit: number; total_answer_limit: number }
const props = defineProps<{ projectType?: string | null; modelValue: Record<string, string>; disabled?: boolean; optional?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, string>]; ready: [value: boolean] }>()
const data = ref<Intake | null>(null), loading = ref(false), error = ref('')
const cache = new Map<string, Record<string, string>>()
let request = 0, loadedType = ''
const required = computed(() => data.value?.questions.filter(q => q.required && !typed(q)) || [])
const extras = computed(() => data.value?.questions.filter(q => !q.required && !typed(q)) || [])
const settings = computed(() => data.value?.questions.filter(typed) || [])
const total = computed(() => Object.values(props.modelValue).reduce((n, value) => n + value.length, 0))
const ready = computed(() => !!data.value && !loading.value && !error.value && total.value <= data.value.total_answer_limit &&
  (props.optional || [...required.value, ...settings.value.filter(q => q.required)].every(q => props.modelValue[q.id]?.trim())))
watch(ready, value => emit('ready', !!value), { immediate: true })
watch(() => props.projectType, async kind => {
  const id = ++request
  if (loadedType) cache.set(loadedType, { ...props.modelValue })
  const initial = !loadedType ? { ...props.modelValue } : {}
  const common = Object.fromEntries(Object.entries(props.modelValue).filter(([key]) => ['audience', 'boundaries'].includes(key)))
  data.value = null; error.value = ''; loading.value = true
  try {
    const result = await getJson<Intake>(`/api/projects/coordinator?operation=intake_questions&project_type=${encodeURIComponent(kind || '')}`)
    if (request !== id) return
    data.value = result; loadedType = kind || 'general'
    const source = { ...initial, ...cache.get(loadedType), ...common }
    if (!props.disabled) emit('update:modelValue', Object.fromEntries(result.questions.filter(q => source[q.id] && allowed(q, source[q.id]!)).map(q => [q.id, source[q.id]!])) )
  } catch { if (request === id) error.value = 'Intake questions could not load. Try again by selecting the template, or save a draft.' }
  finally { if (request === id) loading.value = false }
}, { immediate: true })
function answer(id: string, event: Event) {
  emit('update:modelValue', { ...props.modelValue, [id]: (event.target as HTMLTextAreaElement).value })
}
// A template setting keeps only a value its template allows; the server checks again on save.
function allowed(q: Question, value: string) {
  if (q.type === 'integer') return /^-?\d+$/.test(value.trim()) && +value >= (q.min ?? -Infinity) && +value <= (q.max ?? Infinity)
  if (q.type === 'choice') return !!q.options?.includes(value)
  if (q.type === 'multi') return value.split(',').map(v => v.trim()).filter(Boolean).every(v => q.options?.includes(v))
  if (q.type === 'boolean') return ['yes', 'no'].includes(value)
  return true
}
function typed(q: Question) { return !!q.type && q.type !== 'text' }
const shown = (q: Question) => props.modelValue[q.id] ?? (q.default === undefined ? '' : q.type === 'boolean' ? (q.default ? 'yes' : 'no') : Array.isArray(q.default) ? q.default.join(', ') : String(q.default))
function set(id: string, value: string) { emit('update:modelValue', { ...props.modelValue, [id]: value }) }
function toggle(q: Question, option: string, on: boolean) {
  const now = new Set(shown(q).split(',').map(v => v.trim()).filter(Boolean)); if (on) now.add(option); else now.delete(option)
  set(q.id, (q.options || []).filter(o => now.has(o)).join(', '))
}
</script>
<template>
  <section class="project-intake" aria-label="Project details">
    <p v-if="loading" class="muted small" role="status">Loading template questions…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="data">
      <p class="muted small">A few details shape the plan. “Help me decide” is fine. Do not enter passwords or API keys.</p>
      <label v-for="q in required" :key="q.id">{{ q.label }}<span v-if="optional" class="muted small">Optional for an existing brief</span>
        <textarea class="input" rows="2" :value="modelValue[q.id] || ''" :placeholder="q.prompt" :maxlength="q.type === 'text' ? q.max : data.answer_limit" :required="!optional" :disabled="disabled" @input="answer(q.id, $event)" />
      </label>
      <fieldset v-if="settings.length" class="settings"><legend>Template settings</legend>
        <template v-for="q in settings" :key="q.id">
          <label v-if="q.type === 'integer'">{{ q.label }}<input class="input" type="number" :min="q.min" :max="q.max" step="1" :value="shown(q)" :disabled="disabled" @input="set(q.id, ($event.target as HTMLInputElement).value)" /></label>
          <label v-else-if="q.type === 'choice'">{{ q.label }}<select class="input" :value="shown(q)" :disabled="disabled" @change="set(q.id, ($event.target as HTMLSelectElement).value)"><option v-if="!shown(q)" value="">Choose…</option><option v-for="o in q.options" :key="o" :value="o">{{ o }}</option></select></label>
          <label v-else-if="q.type === 'boolean'" class="check"><input type="checkbox" :checked="shown(q) === 'yes'" :disabled="disabled" @change="set(q.id, ($event.target as HTMLInputElement).checked ? 'yes' : 'no')" />{{ q.label }}</label>
          <fieldset v-else class="multi"><legend>{{ q.label }}</legend><label v-for="o in q.options" :key="o" class="check"><input type="checkbox" :checked="shown(q).split(', ').includes(o)" :disabled="disabled" @change="toggle(q, o, ($event.target as HTMLInputElement).checked)" />{{ o }}</label></fieldset>
        </template>
        <p class="muted small">These are the template's only adjustable parts; its stories, checks and sign-offs stay as published.</p>
      </fieldset>
      <details v-if="extras.length"><summary>More details (optional)</summary>
        <label v-for="q in extras" :key="q.id">{{ q.label }}
          <textarea class="input" rows="2" :value="modelValue[q.id] || ''" :placeholder="q.prompt" :maxlength="q.type === 'text' ? q.max : data.answer_limit" :disabled="disabled" @input="answer(q.id, $event)" />
        </label>
      </details>
      <p v-if="total > data.total_answer_limit" role="alert">Keep these answers under {{ data.total_answer_limit.toLocaleString() }} characters in total.</p>
      <p class="muted small">Spending preferences here do not approve charges. Media and other paid actions use their separate approval controls.</p>
    </template>
  </section>
</template>
<style scoped>
.project-intake { min-width: 0; display: grid; gap: var(--gap-sm); }
.settings, .multi { min-width: 0; display: grid; gap: var(--gap-sm); border: 1px solid var(--border); border-radius: var(--radius); padding: var(--gap-sm); margin: 0; }
.multi { border: 0; padding: 0; } legend { color: var(--text); font-size: var(--font-size-sm); }
.check { display: flex; align-items: center; gap: var(--gap-xs); }
label { display: grid; gap: var(--gap-xs); color: var(--text-muted); font-size: var(--font-size-sm); }
textarea { width: 100%; min-width: 0; resize: vertical; box-sizing: border-box; }
p { margin: 0; } summary { cursor: pointer; color: var(--text); }
details label { margin-top: var(--gap-sm); }
</style>
