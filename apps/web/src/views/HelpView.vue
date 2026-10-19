<script setup lang="ts">
import NoteFold from '@/components/NoteFold.vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import PageHead from '@/components/PageHead.vue'
import HelpGuideArticle from '@/components/HelpGuideArticle.vue'
import { helpGuides } from '@/lib/help'
import { useHelpStore } from '@/stores/help'
const route = useRoute()
const router = useRouter()
const help = useHelpStore()
const search = ref('')
const compact = ref(false)
let mobileQuery: MediaQueryList | undefined
function updateCompact() { compact.value = mobileQuery?.matches ?? false }
onMounted(() => { if (typeof window.matchMedia !== 'function') return; mobileQuery = window.matchMedia('(max-width: 767.98px)'); updateCompact(); mobileQuery.addEventListener('change', updateCompact) })
onBeforeUnmount(() => mobileQuery?.removeEventListener('change', updateCompact))
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
    <PageHead id="help-title" title="Help &amp; how-tos" icon="chat" sub="Clear steps for every RCD feature, with links that open the right place."><button class="btn primary" @click="help.show(selected.id)"><AppIcon name="chat" />Ask help chat</button></PageHead>
    <div class="help-layout"><details class="card guide-catalog" :open="!compact"><summary>Browse how-tos · {{ filtered.length }} of {{ helpGuides.length }}</summary><div class="catalog-content"><label for="help-search">Find a how-to</label><input id="help-search" v-model="search" class="input" type="search" placeholder="Search features or questions…" /><p v-if="!filtered.length" role="status">No matching guides. Try fewer words or ask help chat.</p><button v-for="guide in filtered" :key="guide.id" class="topic" :aria-current="selected.id === guide.id ? 'true' : undefined" @click="choose(guide.id)"><small>{{ guide.area }}</small><strong>{{ guide.title }}</strong></button></div></details><div class="guide-reading"><div class="card"><HelpGuideArticle :guide="selected" /></div><p class="muted small">Help uses built-in guides and opens local RCD links. It does not run agents, grant permissions, send alerts or change settings.</p><NoteFold label="Tips"><p class="muted small">Tip: copy this page’s URL to keep a link to the selected guide. Use the header Help chat button from any feature.</p></NoteFold></div></div>
  </section>
</template>
<style scoped>
.help-page-header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: var(--gap); }
.help-page-header p { margin: var(--gap-sm) 0 0; }
.help-layout { display: grid; grid-template-columns: var(--help-catalog-width) minmax(0, 1fr); gap: var(--gap-lg); align-items: start; }
.guide-catalog { max-height: var(--help-catalog-height); overflow-y: auto; }
.guide-catalog > summary { cursor: pointer; font-weight: 600; }
.catalog-content { display: flex; flex-direction: column; gap: var(--gap-sm); margin-top: var(--gap-sm); }
.catalog-content > p { margin: 0; }
.topic { display: grid; gap: var(--gap-xs); text-align: left; color: var(--text); background: transparent; border: 1px solid transparent; border-radius: var(--radius); padding: var(--gap-sm); cursor: pointer; min-height: var(--touch-target); }
.topic { flex-shrink: 0; }
.topic small { color: var(--text-muted); }
.topic:hover, .topic[aria-current] { background: var(--nav-active); border-color: var(--surface-border); }
.guide-reading { min-width: 0; }
@media (max-width: 767.98px) { .help-layout { grid-template-columns: minmax(0, 1fr); } .guide-catalog { max-height: var(--help-phone-catalog-height); } }
</style>
