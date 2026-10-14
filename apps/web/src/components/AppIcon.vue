<script setup lang="ts">
import { computed } from 'vue'
import { ICONS, type IconName } from '@/icons/icons'

const props = withDefaults(
  defineProps<{
    name: IconName
    size?: 'sm' | 'md' | 'lg'
    /** Accessible name. Leave unset for a decorative icon next to visible text. */
    label?: string
  }>(),
  { size: 'md', label: undefined },
)

const elements = computed(() => ICONS[props.name])
</script>

<template>
  <svg
    class="icon"
    :class="`icon-${size}`"
    :data-icon="name"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    :role="label ? 'img' : undefined"
    :aria-label="label || undefined"
    :aria-hidden="label ? undefined : 'true'"
    :focusable="label ? undefined : 'false'"
  >
    <component :is="el.tag" v-for="(el, i) in elements" :key="i" v-bind="el.attrs" />
  </svg>
</template>

<style scoped>
.icon {
  flex-shrink: 0;
  display: inline-block;
}

.icon-sm {
  width: var(--icon-size-sm);
  height: var(--icon-size-sm);
}

.icon-md {
  width: var(--icon-size-md);
  height: var(--icon-size-md);
}

.icon-lg {
  width: var(--icon-size-lg);
  height: var(--icon-size-lg);
}
</style>
