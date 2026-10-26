<script setup lang="ts">
import { computed, useId } from 'vue'
import { planningBiasLabel, planningBiasHint } from '@/lib/projects'
const props = defineProps<{ modelValue: number; disabled?: boolean; mapped?: boolean; compact?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: number] }>()
const id = useId()
const label = computed(() => planningBiasLabel(props.modelValue))
</script>

<template>
  <div class="planning-preference" :class="{ disabled, compact }">
    <div class="preference-heading"><label :for="id">Model matching preference</label><output :for="id">{{ label }}</output></div>
    <input :id="id" type="range" min="0" max="100" step="25" :value="modelValue" :disabled="disabled"
      :aria-valuetext="label" :aria-describedby="compact ? `${id}-hint` : `${id}-hint ${id}-note`"
      :style="{ '--bias-fill': `${modelValue}%` }" @input="emit('update:modelValue', Number(($event.target as HTMLInputElement).value))" />
    <div class="preference-endpoints" aria-hidden="true"><span><strong>Economy</strong><small>Cost and speed</small></span><span class="midpoint"><strong>Balanced</strong><small>Task fit</small></span><span><strong>Capability</strong><small>Stronger reasoning</small></span></div>
    <p :id="`${id}-hint`" class="preference-hint">{{ planningBiasHint(modelValue) }}</p>
    <p v-if="!compact" :id="`${id}-note`" class="preference-note">{{ mapped ? 'Save and replan to use a new preference. Existing story assignments stay as edited; new stories use this default.' : 'Sets a model classification threshold, not a provider or fixed model. The Coordinator matches specialty, complexity, cost and speed per task.' }} Membership quota and API spending approvals stay separate. Planner quality is selected independently.</p>
  </div>
</template>

<style scoped>
.planning-preference { margin-top: var(--gap-lg); padding: var(--gap); border: 1px solid var(--surface-border); border-radius: var(--surface-radius); background: var(--agent-glass); }
.preference-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--gap-sm); }
.preference-heading label { margin: 0; color: var(--text); font-size: var(--font-size-sm); font-weight: 600; }
output { color: var(--accent); background: var(--accent-soft); border-radius: var(--radius-pill); padding: var(--gap-xs) var(--gap-sm); font-size: var(--font-size-xs); }
input { display: block; appearance: none; width: 100%; height: var(--planning-slider-hit-height); margin: var(--gap-xs) 0; padding: 0; background: transparent; cursor: pointer; }
input::-webkit-slider-runnable-track { height: var(--planning-slider-track); border-radius: var(--radius-pill); background: linear-gradient(to right, var(--accent) var(--bias-fill), var(--select-border) var(--bias-fill)); }
input::-moz-range-track { height: var(--planning-slider-track); border-radius: var(--radius-pill); background: linear-gradient(to right, var(--accent) var(--bias-fill), var(--select-border) var(--bias-fill)); }
input::-webkit-slider-thumb { appearance: none; width: var(--planning-slider-thumb); height: var(--planning-slider-thumb); margin-top: calc((var(--planning-slider-track) - var(--planning-slider-thumb)) / 2); border: var(--focus-ring-width) solid var(--accent); border-radius: var(--radius-pill); background: var(--panel); box-shadow: var(--surface-shadow); }
input::-moz-range-thumb { width: var(--planning-slider-thumb); height: var(--planning-slider-thumb); border: var(--focus-ring-width) solid var(--accent); border-radius: var(--radius-pill); background: var(--panel); box-shadow: var(--surface-shadow); }
input:focus-visible { outline: var(--focus-ring-width) solid var(--focus-ring); outline-offset: var(--focus-ring-offset); border-radius: var(--radius); }
.preference-endpoints { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: var(--gap); font-size: var(--font-size-sm); }
.preference-endpoints span { display: grid; gap: var(--gap-xs); }
.preference-endpoints .midpoint { text-align: center; }
.preference-endpoints span:last-child { text-align: right; }
.preference-endpoints small, .preference-note { color: var(--text-muted); font-size: var(--font-size-xs); }
.preference-hint, .preference-note { margin: var(--gap-xs) 0 0; line-height: var(--line-height); }
.preference-note { margin-top: var(--gap); }
.preference-hint { font-size: var(--font-size-sm); color: var(--text); }
.compact { margin-top: var(--gap); }
.compact .preference-endpoints small { display: none; }
.disabled { opacity: var(--disabled-opacity); }
input:disabled { cursor: default; }
</style>
