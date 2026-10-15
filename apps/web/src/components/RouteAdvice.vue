<script setup lang="ts">
import { ref, watch } from 'vue'
import { getJson } from '@/lib/api'

// Advice on a plan's routes from this installation's own track record and listed model facts. It never blocks anything: the gates,
// risk floors and approvals do that. Failing to ask shows nothing rather than a false all-clear.
const props = defineProps<{ projectId: number; revision?: number }>()
const advice = ref<{ key: string; level: 'info' | 'warn'; text: string }[]>([])
async function load() {
  try { advice.value = (await getJson<{ advice?: { key: string; level: 'info' | 'warn'; text: string }[] }>(`/api/models/advice?project_id=${props.projectId}`)).advice ?? [] } catch { advice.value = [] }
}
watch(() => [props.projectId, props.revision], load, { immediate: true })
</script>
<template>
  <section v-if="advice.length" class="advice" aria-label="Route advice" data-testid="route-advice">
    <p class="small"><strong>Route advice</strong> <span class="muted">(from your own runs and listed model facts; nothing is blocked)</span></p>
    <ul class="small">
      <li v-for="a in advice" :key="a.key + a.text" :class="a.level === 'warn' ? 'notice-warn' : 'muted'"><code>{{ a.key }}</code>: {{ a.text }}</li>
    </ul>
  </section>
</template>
<style scoped>
.advice { display: grid; gap: var(--gap-xs); }
.small { font-size: var(--font-size-sm); margin: 0; }
ul { margin: 0; padding-left: 1.2rem; display: grid; gap: var(--gap-xs); }
</style>
