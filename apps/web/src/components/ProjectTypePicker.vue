<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getJson, postJson } from '@/lib/api'
interface PType { id: string; label: string; summary: string; failure_points: string[]; human_signoffs: string[]; visual_checks: string }
const props = defineProps<{ modelValue: string | null | undefined; text: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()
const types = ref<PType[]>([])
const suggested = ref<string | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
onMounted(async () => { try { types.value = (await getJson<{ types: PType[] }>('/api/project-types')).types } catch { types.value = [] } })
watch(() => props.text, (t) => {
  clearTimeout(timer)
  suggested.value = null
  if (!t || t.trim().length < 20 || props.modelValue) return
  timer = setTimeout(async () => {
    try { suggested.value = (await postJson<{ suggested: string | null }>('/api/project-types/suggest', { text: t })).suggested } catch { suggested.value = null }
  }, 600)
})
onBeforeUnmount(() => clearTimeout(timer))
const current = () => types.value.find(t => t.id === props.modelValue)
const label = (id: string | null) => types.value.find(t => t.id === id)?.label ?? id
</script>
<template>
  <div v-if="types.length" class="type-picker">
    <label>Project type
      <select class="input" :value="modelValue || ''" :disabled="disabled" aria-label="Project type" @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value || null)">
        <option value="">General (no template)</option>
        <option v-for="t in types" :key="t.id" :value="t.id">{{ t.label }}</option>
      </select>
    </label>
    <p v-if="suggested && !modelValue" class="small" role="status">
      This looks like a <strong>{{ label(suggested) }}</strong>.
      <button type="button" class="btn" @click="emit('update:modelValue', suggested)">Use that type</button>
    </p>
    <p v-if="current()" class="muted small">{{ current()!.summary }} The planner is told this type's known failure points, and the plan is checked against where a person should look and sign off.</p>
  </div>
</template>
<style scoped>
.type-picker { display: flex; flex-direction: column; gap: var(--gap-xs); }
label { display: flex; flex-direction: column; gap: var(--gap-xs); color: var(--text-muted); font-size: var(--font-size-sm); }
p { margin: 0; }
</style>
