<script setup lang="ts">
// Push to upubhub, on the push story of a project whose template enables the upubhub-push connector (upubhub class, textbook or
// lesson plan). The server decides everything: whether this is that story, whether the final sign-off is done, whether a upubhub
// token is saved, and whether the course package passes its check. This panel shows those answers and never sends the token.
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import { ApiError, getJson, postJson, type Card } from '@/lib/api'

interface Item { external_id?: string; url_path?: string; created?: boolean; visibility?: string; lesson?: string; assessment?: string }
interface Receipt { kind: string; pushed_at?: string; upubhub?: string; textbook?: Item | null; lesson_plans?: Item[]; class?: (Item & { assignments?: Item[] }) | null }
interface Plan { kind?: string; title?: string; lessons?: number; images?: number; error?: string }
interface Status { plan: Plan; blocked_by: string[]; token_saved: boolean; target: string; problems: string[]; last: Receipt | null }
const props = defineProps<{ card: Card }>()
const emit = defineEmits<{ changed: [] }>()
const status = ref<Status | null>(null), busy = ref(false), error = ref('')
const base = computed(() => `/api/projects/${props.card.project!.id}/stories/${props.card.id}/upubhub-push`)
// The same title rule as the server, so other stories never ask; the server still decides.
const candidate = computed(() => {
  const t = (props.card.title || '').toLowerCase()
  return !!props.card.project && t.includes('upubhub') && t.includes('push') && !t.includes('approve')
})
const blocked = computed(() => !!status.value && (status.value.blocked_by.length > 0 || props.card.blocked_by.length > 0))
const ready = computed(() => !!status.value && !blocked.value && status.value.token_saved && !status.value.problems.length && !status.value.plan.error)
const what = computed(() => ({ class: 'course', textbook: 'textbook', lesson_plan: 'lesson plan' } as Record<string, string>)[status.value?.plan.kind ?? ''] ?? 'package')
const link = (path?: string) => (status.value && path ? status.value.target.replace(/\/$/, '') + path : '')

async function load() {
  if (!candidate.value) { status.value = null; return }
  error.value = ''
  try { status.value = await getJson<Status>(base.value) }
  catch (e) { status.value = null; if (!(e instanceof ApiError && e.status === 404)) error.value = e instanceof Error ? e.message : String(e) }
}
async function push() {
  if (busy.value || !ready.value) return
  busy.value = true; error.value = ''
  try { await postJson<Receipt>(base.value); await load(); emit('changed') }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
onMounted(load)
watch(() => [props.card.id, props.card.project?.id], load)
</script>

<template>
  <section v-if="status || error" class="upubhub-push" aria-label="Push to upubhub" data-testid="upubhub-push" @click.stop>
    <h3>Push to upubhub</h3>
    <template v-if="status">
      <p class="muted small">Sends this {{ what }} to <code>{{ status.target }}</code> as private drafts<template v-if="status.plan.kind === 'class'"> and an invite-only, free class</template>.
        Nothing is published: you review it on upubhub and publish it there. Pushing again updates the same items.</p>
      <p v-if="status.plan.title" class="small">{{ status.plan.title }} · {{ status.plan.lessons }} lesson{{ status.plan.lessons === 1 ? '' : 's' }}<template v-if="status.plan.images"> · {{ status.plan.images }} image{{ status.plan.images === 1 ? '' : 's' }}</template></p>
      <p v-if="blocked" class="notice-warn small" data-testid="push-blocked">Finish the earlier stories first, including your final sign-off. {{ status.blocked_by.join(' ') }}</p>
      <p v-if="!status.token_saved" class="notice-warn small" data-testid="push-token">Save a upubhub token first: in upubhub open Connections, create a token with <strong>Also allow pushing classes</strong> ticked, then paste it in <RouterLink to="/profile#credentials-profile">Private credentials</RouterLink> as upubhub.</p>
      <p v-if="status.plan.error" class="error-text">{{ status.plan.error }}</p>
      <template v-if="status.problems.length">
        <p class="error-text">The {{ what }} package has {{ status.problems.length }} problem{{ status.problems.length === 1 ? '' : 's' }} to fix before it can be pushed:</p>
        <ul class="problems small" data-testid="push-problems"><li v-for="p in status.problems.slice(0, 12)" :key="p">{{ p }}</li></ul>
      </template>
      <div class="actions">
        <button type="button" class="btn primary" :disabled="busy || !ready" data-action="upubhub-push" @click="push"><AppIcon name="run" size="sm" />{{ busy ? 'Pushing…' : status.last ? 'Push again' : 'Push to upubhub' }}</button>
      </div>
      <div v-if="busy" class="bar" role="progressbar" aria-label="Pushing to upubhub" aria-busy="true"><span /></div>
      <div v-if="status.last" class="result small" role="status" data-testid="push-result">
        <p>Pushed {{ status.last.pushed_at?.replace('T', ' ').replace('Z', ' UTC') }}:</p>
        <ul>
          <li v-if="status.last.textbook">Textbook, {{ status.last.textbook.visibility }}: <a :href="link(status.last.textbook.url_path)" target="_blank" rel="noopener noreferrer">open on upubhub</a></li>
          <li v-for="lp in status.last.lesson_plans ?? []" :key="lp.external_id">Lesson plan {{ lp.lesson }}, {{ lp.visibility }}: <a :href="link(lp.url_path)" target="_blank" rel="noopener noreferrer">open on upubhub</a></li>
          <li v-if="status.last.class">Class, {{ status.last.class.visibility?.replace('_', ' ') }}: <a :href="link(status.last.class.url_path)" target="_blank" rel="noopener noreferrer">open on upubhub</a>
            <template v-if="status.last.class.assignments?.some(a => a.assessment === 'waiting')"> · some assessments wait for their lessons to pass moderation; push again once they are published.</template></li>
        </ul>
      </div>
    </template>
    <p v-if="error" class="error-text" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.upubhub-push { display: grid; gap: var(--gap-sm); padding: var(--gap); margin: var(--gap) 0; border: 1px solid var(--accent); border-radius: var(--radius); background: var(--accent-soft); }
.upubhub-push h3, .upubhub-push p { margin: 0; }
.actions { display: flex; gap: var(--gap-sm); flex-wrap: wrap; align-items: center; }
.error-text { margin: 0; color: var(--danger); font-size: var(--font-size-sm); }
.problems, .result ul { margin: 0; padding-left: var(--gap); }
.bar { block-size: var(--meter-height); overflow: hidden; background: var(--surface-border); border-radius: var(--radius-pill); }
.bar span { display: block; block-size: 100%; inline-size: 40%; background: var(--accent); animation: slide var(--pulse-duration) ease-in-out infinite; }
@keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
@media (prefers-reduced-motion: reduce) { .bar span { animation: none; inline-size: 100%; } }
</style>
