<script setup lang="ts">
// A template's icon, or a monogram tile in its place until an icon file exists (see lib/templateStore.ts).
import { computed } from 'vue'
import { iconFor, monogram, seriesFor } from '@/lib/templateStore'

const props = defineProps<{ id: string; title: string }>()
const src = computed(() => iconFor(props.id))
const series = computed(() => `var(--series-${seriesFor(props.id)})`)
const seriesSoft = computed(() => `var(--series-${seriesFor(props.id)}-soft)`)
</script>

<template>
  <img v-if="src" class="ticon" :src="src" alt="" aria-hidden="true" data-test="icon" />
  <span v-else class="ticon placeholder" aria-hidden="true" data-test="icon-placeholder" :title="`Icon placeholder: assets/template-icons/${id}.png`"
    :style="{ color: series, background: seriesSoft, borderColor: series }">{{ monogram(title) }}</span>
</template>

<style scoped>
.ticon { inline-size: var(--store-icon-size); block-size: var(--store-icon-size); flex: none; border-radius: var(--radius); object-fit: cover; }
.placeholder { display: grid; place-items: center; border: 1px dashed; font-weight: var(--font-weight-strong); font-size: var(--font-size-sm); letter-spacing: var(--nav-letter-spacing); }
</style>
