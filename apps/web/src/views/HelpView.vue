<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import HelpGuideArticle from '@/components/HelpGuideArticle.vue'
import { helpGuides } from '@/lib/help'
import { useHelpStore } from '@/stores/help'
const route = useRoute()
const router = useRouter()
const help = useHelpStore()
const search = ref('')
const selected = computed(() => helpGuides.find(g => g.id === route.query.topic) ?? helpGuides[0]!)
const filtered = computed(() => {
  const words = search.value.toLowerCase().trim().split(/\s+/).filter(Boolean)
  return helpGuides.filter(g => words.every(word => [g.title, g.area, g.summary, ...g.keywords, ...g.steps].join(' ').toLowerCase().includes(word)))
})
function choose(id: string) { void router.replace({ path: '/help', query: { topic: id } }) }
</script>
<template>
  <section class="page" aria-labelledby="help-title">
    <p><RouterLink to="/setup" class="btn">New here? Open the setup wizard</RouterLink></p>
    <header class="help-page-header"><div><h1 id="help-title" class="page-title has-icon"><AppIcon name="chat" size="lg" />Help & how-tos</h1><p class="muted">Clear steps for every RCD feature, with links that open the right place.</p></div><button class="btn primary" @click="help.show(selected.id)"><AppIcon name="chat" />Ask help chat</button></header>
    <div class="help-layout"><nav class="card guide-catalog" aria-label="How-to topics"><label for="help-search">Find a how-to</label><input id="help-search" v-model="search" class="input" type="search" placeholder="Search features or questions…" /><p class="muted small">{{ filtered.length }} of {{ helpGuides.length }} guides</p><p v-if="!filtered.length" role="status">No matching guides. Try fewer words or ask help chat.</p><button v-for="guide in filtered" :key="guide.id" class="topic" :aria-current="selected.id === guide.id ? 'true' : undefined" @click="choose(guide.id)"><small>{{ guide.area }}</small><strong>{{ guide.title }}</strong></button></nav><div class="guide-reading"><div class="card"><HelpGuideArticle :guide="selected" /></div><p class="muted small">Help uses built-in guides and opens local RCD links. It does not run agents, grant permissions, send alerts or change settings.</p><p class="muted small">Tip: copy this page’s URL to keep a link to the selected guide. Use the header Help chat button from any feature.</p></div></div>
  </section>
</template>
<style scoped>
.help-page-header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: var(--gap); }
.help-page-header p { margin: var(--gap-sm) 0 0; }
.help-layout { display: grid; grid-template-columns: var(--help-catalog-width) minmax(0, 1fr); gap: var(--gap-lg); align-items: start; }
.guide-catalog { display: flex; flex-direction: column; gap: var(--gap-sm); max-height: var(--help-catalog-height); overflow-y: auto; }
.guide-catalog > p { margin: 0; }
.topic { display: grid; gap: var(--gap-xs); text-align: left; color: var(--text); background: transparent; border: 1px solid transparent; border-radius: var(--radius); padding: var(--gap-sm); cursor: pointer; min-height: var(--touch-target); }
.topic { flex-shrink: 0; }
.topic small { color: var(--text-muted); }
.topic:hover, .topic[aria-current] { background: var(--nav-active); border-color: var(--surface-border); }
.guide-reading { min-width: 0; }
@media (max-width: 767.98px) { .help-layout { grid-template-columns: minmax(0, 1fr); } .guide-catalog { max-height: var(--help-phone-catalog-height); } }
</style>
