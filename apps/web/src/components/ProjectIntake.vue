<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getJson } from '@/lib/api'
interface Question { id: string; label: string; prompt: string; required?: boolean }
interface Intake { questions: Question[]; answer_limit: number; total_answer_limit: number }
const props = defineProps<{ projectType?: string | null; modelValue: Record<string, string>; disabled?: boolean; optional?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, string>]; ready: [value: boolean] }>()
const data = ref<Intake | null>(null), loading = ref(false), error = ref('')
const cache = new Map<string, Record<string, string>>()
let request = 0, loadedType = ''
const required = computed(() => data.value?.questions.filter(q => q.required) || [])
const extras = computed(() => data.value?.questions.filter(q => !q.required) || [])
const total = computed(() => Object.values(props.modelValue).reduce((n, value) => n + value.length, 0))
const ready = computed(() => !!data.value && !loading.value && !error.value && total.value <= data.value.total_answer_limit &&
  (props.optional || required.value.every(q => props.modelValue[q.id]?.trim())))
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
    if (!props.disabled) emit('update:modelValue', Object.fromEntries(result.questions.filter(q => source[q.id]).map(q => [q.id, source[q.id]!])) )
  } catch { if (request === id) error.value = 'Intake questions could not load. Try again by selecting the template, or save a draft.' }
  finally { if (request === id) loading.value = false }
}, { immediate: true })
function answer(id: string, event: Event) {
  emit('update:modelValue', { ...props.modelValue, [id]: (event.target as HTMLTextAreaElement).value })
}
</script>
<template>
  <section class="project-intake" aria-label="Project details">
    <p v-if="loading" class="muted small" role="status">Loading template questions…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="data">
      <p class="muted small">A few details shape the plan. “Help me decide” is fine. Do not enter passwords or API keys.</p>
      <label v-for="q in required" :key="q.id">{{ q.label }}<span v-if="optional" class="muted small">Optional for an existing brief</span>
        <textarea class="input" rows="2" :value="modelValue[q.id] || ''" :placeholder="q.prompt" :maxlength="data.answer_limit" :required="!optional" :disabled="disabled" @input="answer(q.id, $event)" />
      </label>
      <details v-if="extras.length"><summary>More details (optional)</summary>
        <label v-for="q in extras" :key="q.id">{{ q.label }}
          <textarea class="input" rows="2" :value="modelValue[q.id] || ''" :placeholder="q.prompt" :maxlength="data.answer_limit" :disabled="disabled" @input="answer(q.id, $event)" />
        </label>
      </details>
      <p v-if="total > data.total_answer_limit" role="alert">Keep these answers under {{ data.total_answer_limit.toLocaleString() }} characters in total.</p>
      <p class="muted small">Spending preferences here do not approve charges. Media and other paid actions use their separate approval controls.</p>
    </template>
  </section>
</template>
<style scoped>
.project-intake { min-width: 0; display: grid; gap: var(--gap-sm); }
label { display: grid; gap: var(--gap-xs); color: var(--text-muted); font-size: var(--font-size-sm); }
textarea { width: 100%; min-width: 0; resize: vertical; box-sizing: border-box; }
p { margin: 0; } summary { cursor: pointer; color: var(--text); }
details label { margin-top: var(--gap-sm); }
</style>
