<script setup lang="ts">
import { computed } from 'vue'
import { NOT_REPORTED } from '@/lib/format'

const props = defineProps<{
  value: string | number | null | undefined
  /** Formats a numeric value; strings are shown as they are. */
  format?: (v: number) => string
  /** Muted text to show instead of "not reported" (for example "None"). */
  empty?: string
}>()

const missing = computed(() => props.value === null || props.value === undefined || props.value === '')
const text = computed(() => {
  const v = props.value
  if (v === null || v === undefined || v === '') return props.empty ?? NOT_REPORTED
  return typeof v === 'number' && props.format ? props.format(v) : String(v)
})
</script>

<template>
  <span :class="{ muted: missing }" :data-missing="missing ? 'true' : undefined">{{ text }}</span>
</template>
