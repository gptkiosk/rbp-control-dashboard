<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ tag: string }>()

const TONES = 6

/** The same tag always gets the same colour, so a tag is recognisable across rows. */
const tone = computed(() => {
  let h = 0
  for (const ch of props.tag) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return (h % TONES) + 1
})
</script>

<template>
  <span class="tag-pill" :data-tone="tone" data-testid="tag-pill"><slot>{{ tag }}</slot></span>
</template>

<style scoped>
.tag-pill {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-xs);
  max-width: 100%;
  padding: 0 var(--gap-sm);
  border-radius: var(--radius-pill);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-strong);
  line-height: var(--line-height);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  background: var(--series-1-soft);
  color: var(--series-1);
}

.tag-pill[data-tone='2'] {
  background: var(--series-2-soft);
  color: var(--series-2);
}

.tag-pill[data-tone='3'] {
  background: var(--series-3-soft);
  color: var(--series-3);
}

.tag-pill[data-tone='4'] {
  background: var(--series-4-soft);
  color: var(--series-4);
}

.tag-pill[data-tone='5'] {
  background: var(--series-5-soft);
  color: var(--series-5);
}

.tag-pill[data-tone='6'] {
  background: var(--series-6-soft);
  color: var(--series-6);
}
</style>
