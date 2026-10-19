<script setup lang="ts">
// A human story that asks for pictures or video points at the media studio, and says what it will cost before anyone opens it.
import { computed } from 'vue'
import { costWords, type ProjectMedia } from '@/composables/useProjectMedia'
const props = defineProps<{ media: ProjectMedia | null; link: string; compact?: boolean; chip?: boolean }>()
const words = computed(() => costWords(props.media?.cost))
const published = computed(() => props.media?.summary ? `${props.media.summary.published} of ${props.media.summary.total} published` : '')
</script>
<template>
  <RouterLink v-if="media?.available && chip" :to="link" class="media-chip" data-testid="media-chip" title="Make and preview media. Estimates only: fal's invoice is the truth." @click.stop>
    Media studio<template v-if="words.short"> · {{ words.short }}</template> →
  </RouterLink>
  <RouterLink v-else-if="media?.available && compact" :to="link" class="media-link" data-testid="media-link" title="Estimates only: fal's invoice is the truth." @click.stop>
    Open media studio<template v-if="published || words.left"> ({{ [published, words.left].filter(Boolean).join(' · ') }})</template> →
  </RouterLink>
  <section v-else-if="media?.available" class="media-callout" data-testid="media-callout" aria-label="Media studio">
    <header><strong>Make and review media</strong><span class="spend">spends from your fal account</span></header>
    <dl class="nums">
      <div v-if="published"><dt>Published</dt><dd>{{ published }}</dd></div>
      <div v-if="words.left"><dt>Left to make</dt><dd>{{ words.leftValue }}</dd></div>
      <div v-if="words.spent"><dt>Spent so far</dt><dd>{{ words.spentValue }}</dd></div>
    </dl>
    <div class="go">
      <RouterLink :to="link" class="btn primary" data-testid="media-link">Open media studio →</RouterLink>
      <small class="muted">Nothing is generated until you confirm there. Estimates only; fal's invoice is the truth.</small>
    </div>
  </section>
</template>
<style scoped>
.media-chip { display: inline-flex; align-items: center; padding: 0 var(--gap-sm); border: 1px solid var(--warn); border-radius: var(--radius-pill); color: var(--warn); font-size: var(--font-size-xs); white-space: nowrap; text-decoration: none; }
.media-link { display: inline-block; margin-top: var(--gap-xs); font-size: var(--font-size-sm); }
.media-callout { display: grid; gap: var(--gap-sm); padding: var(--gap); border: 1px solid var(--surface-border); border-left: 4px solid var(--warn); border-radius: var(--radius); background: var(--panel); }
header { display: flex; align-items: center; flex-wrap: wrap; gap: var(--gap-sm); }
header strong { flex: 1 1 auto; }
.spend { padding: 0 var(--gap-sm); border: 1px solid var(--warn); border-radius: var(--radius-pill); color: var(--warn); font-size: var(--font-size-xs); }
.nums { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: var(--gap-sm); margin: 0; }
.nums div { display: grid; gap: var(--gap-xs); }
dt { color: var(--text-muted); font-size: var(--font-size-xs); }
dd { margin: 0; font-size: var(--font-size-sm); }
.go { display: flex; align-items: center; flex-wrap: wrap; gap: var(--gap-sm); }
.go small { font-size: var(--font-size-xs); }
</style>
