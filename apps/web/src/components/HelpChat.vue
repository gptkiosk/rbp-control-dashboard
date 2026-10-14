<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useHelpStore } from '@/stores/help'
import ModalShell from '@/components/ModalShell.vue'
import AppIcon from '@/components/AppIcon.vue'
import HelpGuideArticle from '@/components/HelpGuideArticle.vue'
import { findGuides, helpGuides, pageGuide, type HelpGuide } from '@/lib/help'

const help = useHelpStore()
const route = useRoute()
const draft = ref('')
const scroller = ref<HTMLElement | null>(null)
interface Exchange { question: string; guide?: HelpGuide; related: HelpGuide[] }
const exchanges = ref<Exchange[]>([])
const lastTopic = ref<string>()
const current = computed(() => pageGuide(route.path))
const suggestions = computed(() => [...new Set([current.value.id, 'agent-tasks', 'agent-explorer', 'subscriptions', 'hermes-access'])].slice(0, 4).map(id => helpGuides.find(g => g.id === id)!))
const selectedTopic = computed(() => help.topic ? helpGuides.find(g => g.id === help.topic) : undefined)

async function answer(question: string, guide?: HelpGuide) {
  const text = question.trim().slice(0, 1000)
  if (!text) return
  const matches = guide ? [guide] : findGuides(text, lastTopic.value)
  exchanges.value = [...exchanges.value.slice(-19), { question: text, guide: matches[0], related: matches.slice(1) }]
  if (matches[0]) lastTopic.value = matches[0].id
  draft.value = ''
  await nextTick()
  const transcript = scroller.value
  const latest = transcript?.querySelector<HTMLElement>('.exchange:last-child')
  if (transcript && latest) {
    transcript.scrollTo?.({ top: transcript.scrollTop + latest.getBoundingClientRect().top - transcript.getBoundingClientRect().top })
  }
}
function send() { void answer(draft.value) }
function clear() { exchanges.value = []; lastTopic.value = undefined; draft.value = '' }
watch(selectedTopic, (guide) => { if (guide) void answer(guide.title, guide) })
function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send() }
}
</script>
<template>
  <ModalShell v-if="help.open" labelledby="help-chat-title" variant="help" @close="help.close">
    <header class="help-header"><div><h2 id="help-chat-title" class="section-title has-icon"><AppIcon name="chat" />RCD help</h2><p class="muted small">Answers from the built-in how-to guides.</p></div><button class="btn icon-only" aria-label="Close help chat" @click="help.close"><AppIcon name="close" /></button></header>
    <div ref="scroller" class="help-transcript" role="log" aria-label="Help conversation" aria-live="polite" aria-relevant="additions">
      <div v-if="!exchanges.length" class="greeting"><h3>What would you like to do?</h3><p>Ask about a feature, or choose a topic. I’ll show the steps and a link to the right place.</p><p class="muted small">You’re on {{ current.area }}. Help runs locally; it doesn’t send messages to an agent or change your dashboard.</p><div class="suggestions"><button v-for="guide in suggestions" :key="guide.id" class="btn" @click="answer(guide.title, guide)">{{ guide.title }}</button></div></div>
      <section v-for="(exchange, i) in exchanges" :key="i" class="exchange">
        <p class="question"><span class="muted small">You</span>{{ exchange.question }}</p>
        <div class="answer"><span class="muted small">RCD guide</span><HelpGuideArticle v-if="exchange.guide" :guide="exchange.guide" @navigate="help.close" /><template v-else><p>I couldn’t match that question to a guide. Try a feature name such as “dependencies,” “OpenRouter cost,” or “Hermes access,” or browse all how-tos.</p><RouterLink class="btn" to="/help" @click="help.close">Browse all how-tos</RouterLink></template><div v-if="exchange.related.length" class="related"><span class="muted small">Related help</span><button v-for="guide in exchange.related" :key="guide.id" class="btn" @click="answer(guide.title, guide)">{{ guide.title }}</button></div></div>
      </section>
    </div>
    <footer class="help-composer"><form @submit.prevent="send"><label class="sr-only" for="help-question">Ask about RCD</label><textarea id="help-question" v-model="draft" class="input" rows="2" maxlength="1000" placeholder="How do I track OpenRouter costs?" data-autofocus @keydown="keydown"></textarea><button class="btn primary" type="submit" :disabled="!draft.trim()" aria-label="Send help question"><AppIcon name="send" /></button></form><div class="help-tools"><RouterLink to="/help" @click="help.close">All how-tos</RouterLink><button class="text-button" :disabled="!exchanges.length" @click="clear">Clear conversation</button></div><p class="muted small">Guide answers · no model usage · conversation clears when you sign out or reload.</p></footer>
  </ModalShell>
</template>
<style scoped>
.help-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--gap); padding: var(--gap); border-bottom: 1px solid var(--surface-border); flex: none; }
.help-header p { margin: var(--gap-xs) 0 0; }
.help-transcript { flex: 1; min-height: 0; overflow-y: auto; padding: var(--gap); display: flex; flex-direction: column; gap: var(--gap-lg); }
.greeting h3 { font-size: var(--font-size-lg); margin: 0; }
.greeting, .exchange { flex-shrink: 0; }
.suggestions, .related { display: flex; flex-wrap: wrap; gap: var(--gap-sm); }
.suggestions .btn, .related .btn { text-align: left; white-space: normal; min-height: var(--touch-target); }
.exchange { display: grid; gap: var(--gap-sm); }
.question { margin: 0; padding: var(--gap-sm) var(--gap); background: var(--accent-soft); border-radius: var(--radius); overflow-wrap: anywhere; white-space: pre-wrap; }
.question > span { display: block; margin-bottom: var(--gap-xs); }
.answer { display: grid; gap: var(--gap); padding: var(--gap); background: var(--glass-bg); border: 1px solid var(--surface-border); border-radius: var(--radius); }
.answer p { margin: 0; }
.related > span { flex-basis: 100%; }
.help-composer { padding: var(--gap); border-top: 1px solid var(--surface-border); flex: none; }
.help-composer form { display: flex; align-items: stretch; gap: var(--gap-sm); }
.help-composer textarea { flex: 1; min-width: 0; resize: none; min-height: var(--select-height); }
.help-tools { display: flex; justify-content: space-between; gap: var(--gap); margin-top: var(--gap-sm); font-size: var(--font-size-sm); }
.text-button { border: 0; color: var(--text-muted); background: transparent; cursor: pointer; }
.text-button:disabled { opacity: var(--disabled-opacity); cursor: default; }
.help-composer > p { margin: var(--gap-sm) 0 0; }
</style>
