<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { computed, watch } from 'vue'
import type { ConfiguredAgent } from '@/lib/api'
import { agentName } from '@/lib/selectLabels'
const props = defineProps<{ id: string; modelValue: string; agents?: ConfiguredAgent[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const selected = computed(() => props.agents?.find((a) => a.id === props.modelValue))
watch(
  () => props.agents,
  (options) => {
    if (options?.length && !options.some((a) => a.id === props.modelValue))
      emit('update:modelValue', (options.find((a) => a.default) ?? options[0])!.id)
  },
  { immediate: true },
)
</script>
<template>
  <div class="field">
    <label :for="id">OpenClaw agent</label>
    <AppSelect
      v-if="agents?.length"
      :id="id"
      class="input"
      :value="modelValue"
      @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
    >
      <option v-for="a in agents" :key="a.id" :value="a.id" :data-label="agentName(a.name, a.id)" :data-description="`${a.id}${a.default ? ' · Default' : ''}`">
        {{ a.name || a.id }} · {{ a.id }}{{ a.default ? ' (default)' : '' }}
      </option>
    </AppSelect>
    <input
      v-else
      :id="id"
      class="input"
      :value="modelValue"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <p class="hint">
      {{
        agents?.length
          ? `Configured model: ${selected?.model || 'not reported'}`
          : 'Agent catalog is unavailable. Enter the configured agent ID, or use mm-main.'
      }}
    </p>
  </div>
</template>
<style scoped>
.field {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}
.hint {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--text-muted);
  overflow-wrap: anywhere;
}
</style>
