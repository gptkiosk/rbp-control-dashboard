<script setup lang="ts">
// A labelled on/off switch. A real checkbox underneath, so keyboard, screen readers and form tests behave as they do for any checkbox.
defineOptions({ inheritAttrs: false })
defineProps<{ modelValue?: boolean; label: string; hint?: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; change: [value: boolean] }>()
function toggle(event: Event) {
  const on = (event.target as HTMLInputElement).checked
  emit('update:modelValue', on); emit('change', on)
}
</script>
<template>
  <label class="switch" :class="{ off: disabled }" :title="hint">
    <input v-bind="$attrs" type="checkbox" role="switch" :checked="modelValue" :disabled="disabled" @change="toggle" />
    <span class="track" aria-hidden="true"><span class="knob" /></span>
    <span class="text">{{ label }}</span>
  </label>
</template>
<style scoped>
.switch { display: flex; align-items: center; gap: var(--gap-sm); margin: 0; color: var(--text); font-size: var(--font-size-sm); cursor: pointer; min-width: 0; }
.switch.off { opacity: var(--disabled-opacity, 0.5); cursor: default; }
input { position: absolute; opacity: 0; width: 1px; height: 1px; }
.track { flex: none; position: relative; width: 2.2rem; height: 1.2rem; border-radius: var(--radius-pill); background: var(--select-border, var(--surface-border)); transition: background 0.15s; }
.knob { position: absolute; top: 0.15rem; left: 0.15rem; width: 0.9rem; height: 0.9rem; border-radius: 50%; background: var(--panel, #fff); transition: transform 0.15s; box-shadow: var(--surface-shadow); }
input:checked + .track { background: var(--accent); }
input:checked + .track .knob { transform: translateX(1rem); }
input:focus-visible + .track { outline: var(--focus-ring-width, 2px) solid var(--focus-ring, var(--accent)); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .track, .knob { transition: none; } }
.text { min-width: 0; overflow-wrap: anywhere; }
</style>
