<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { HelpGuide } from '@/lib/help'
defineProps<{ guide: HelpGuide }>()
const emit = defineEmits<{ navigate: [] }>()
</script>
<template>
  <article class="guide">
    <h3>{{ guide.title }}</h3>
    <p>{{ guide.summary }}</p>
    <ol><li v-for="step in guide.steps" :key="step">{{ step }}</li></ol>
    <p v-if="guide.note" class="guide-note">{{ guide.note }}</p>
    <div class="guide-links"><RouterLink v-for="link in guide.links" :key="link.to" :to="link.to" class="btn" @click="emit('navigate')">{{ link.label }} <span aria-hidden="true">→</span></RouterLink></div>
  </article>
</template>
<style scoped>
.guide { display: grid; gap: var(--gap); min-width: 0; overflow-wrap: anywhere; }
.guide h3, .guide p, .guide ol { margin: 0; }
.guide h3 { font-size: var(--font-size-lg); }
.guide ol { padding-left: var(--gap-lg); display: grid; gap: var(--gap-sm); list-style-type: decimal; }
.guide-note { color: var(--text-muted); font-size: var(--font-size-sm); border-left: var(--severity-bar-width) solid var(--select-border); padding-left: var(--gap-sm); }
.guide-links { display: flex; flex-wrap: wrap; gap: var(--gap-sm); }
.guide-links .btn { white-space: normal; text-align: left; min-height: var(--touch-target); }
</style>
