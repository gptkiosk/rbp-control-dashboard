<script setup lang="ts">
// One picker for every place a runtime and model are chosen. It lists only what the route policy allows for the feature (memberships first,
// paid API last), with provider, cost class and recent reliability, and can show the hidden routes with the reason each is hidden.
import { computed, toRef } from 'vue'
import AppSelect from './AppSelect.vue'
import { costLabel, parseKey, providerLabel, reliabilityLabel, routeKey, routeLabel, useRoutes, type Choice, type Feature } from '@/lib/routes'

const props = withDefaults(defineProps<{ feature: Feature; projectId?: number | null; modelValue?: Choice | null; label?: string; disabled?: boolean; automatic?: string }>(), { projectId: null, modelValue: null, label: '', automatic: '' })
const emit = defineEmits<{ 'update:modelValue': [value: Choice | null] }>()
const { data, error, load } = useRoutes(props.feature, toRef(props, 'projectId'))
defineExpose({ load })
const selected = computed(() => props.modelValue ? routeKey(props.modelValue) : '')
const current = computed(() => data.value?.allowed.find(r => routeKey(r) === selected.value) ?? null)
const outside = computed(() => props.modelValue && data.value && !current.value ? data.value.hidden.find(r => routeKey(r) === selected.value) ?? null : null)
function pick(value: string | number) { emit('update:modelValue', value === '' ? null : parseKey(String(value))) }
</script>

<template>
  <div class="route-picker" :data-feature="feature">
    <label>{{ label || data?.label || feature }}
      <AppSelect :model-value="selected" :disabled="disabled || !data" :aria-label="(label || feature) + ' route'" :placeholder="data?.empty_reason ? 'No allowed route' : 'Choose a route…'" @update:model-value="pick">
        <option v-if="automatic" value="" :data-description="automatic">Automatic</option>
        <option v-for="r in data?.allowed ?? []" :key="routeKey(r)" :value="routeKey(r)"
                :data-description="`${providerLabel(r.provider)} · ${costLabel(r.cost_class)} · ${reliabilityLabel(r.reliability)}`">{{ routeLabel(r) }}</option>
        <option v-if="outside" :value="selected" disabled>{{ routeLabel(outside) }} (not allowed)</option>
      </AppSelect>
    </label>
    <p v-if="current" class="muted small route-facts" data-testid="route-facts">{{ providerLabel(current.provider) }} · {{ costLabel(current.cost_class) }} · {{ reliabilityLabel(current.reliability) }}</p>
    <p v-if="outside" class="notice-warn small" role="alert">{{ routeLabel(outside) }} is not allowed: {{ outside.hidden_because }}.</p>
    <p v-if="data?.empty_reason" class="notice-warn small" role="alert">{{ data.empty_reason }} <RouterLink to="/profile#models-providers">Models &amp; providers</RouterLink></p>
    <p v-else-if="data?.default_note" class="muted small">{{ data.default_note }}.</p>
    <p v-if="error" class="notice-warn small" role="alert">{{ error }}</p>
    <details v-if="data?.hidden.length" class="hidden-routes"><summary class="small">Show hidden ({{ data.hidden.length }})</summary>
      <ul class="small"><li v-for="r in data.hidden" :key="routeKey(r) + r.target">{{ routeLabel(r) }}: <span class="muted">{{ r.hidden_because }}</span></li></ul>
    </details>
  </div>
</template>

<style scoped>
.route-picker{display:grid;gap:var(--gap-xs)}label{display:grid;gap:var(--gap-xs)}.small{font-size:var(--font-size-xs)}
.hidden-routes ul{margin:var(--gap-xs) 0 0;padding-left:1.2em;max-height:12rem;overflow:auto}summary{cursor:pointer}
</style>
