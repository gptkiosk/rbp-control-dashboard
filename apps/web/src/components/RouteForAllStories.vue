<script setup lang="ts">
// One route for every agent story, plus the backups each story fails over to, chosen once before the run instead of story by story.
// The parent sends the choice (the server saves it as a new revision) and shows the result.
import { computed, onMounted, ref } from 'vue'
import { getJson } from '@/lib/api'
import { agentLabel } from '@/lib/cards'
import type { RecoveryInfo, RecoveryRoute } from '@/lib/routeRecovery'

defineProps<{ busy: boolean; disabled?: boolean }>()
const emit = defineEmits<{ apply: [main: RecoveryRoute, backups: RecoveryRoute[]] }>()
const info = ref<RecoveryInfo | null>(null), main = ref(''), backups = ref<string[]>([]), error = ref('')
const key = (r: RecoveryRoute) => `${r.agent}|${r.model}`
// Subscription routes first: they are the steadiest choice when one is configured; then free ones.
const routes = computed(() => (info.value?.options ?? []).filter(r => r.allowed)
  .sort((a, b) => Number(a.price_class !== 'subscription') - Number(b.price_class !== 'subscription')))
const byKey = computed(() => Object.fromEntries(routes.value.map(r => [key(r), r])))
const label = (r: RecoveryRoute & { price_class?: string }) => `${agentLabel(r.agent)} · ${r.model}${r.price_class ? ` (${r.price_class})` : ''}`
function toggle(k: string) {
  backups.value = backups.value.includes(k) ? backups.value.filter(b => b !== k) : backups.value.length < 5 ? [...backups.value, k] : backups.value
}
function send() {
  const pick = (k: string) => ({ agent: byKey.value[k]!.agent, model: byKey.value[k]!.model })
  emit('apply', pick(main.value), backups.value.filter(b => b !== main.value).map(pick))
}
onMounted(async () => { try { info.value = await getJson<RecoveryInfo>('/api/profile/route-reliability') } catch (e) { error.value = e instanceof Error ? e.message : String(e) } })
</script>
<template>
  <details class="card route-all" data-testid="route-all">
    <summary><strong>Use one route for all stories</strong> <span class="muted small">Pick the model every agent story runs on, and the backups it fails over to, instead of one story at a time.</span></summary>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-else-if="info && !routes.length" class="muted small">No route is available yet. Configure billing or recovery routes first.</p>
    <template v-else-if="info">
      <label class="row"><span class="name">Main route</span>
        <select v-model="main" class="input" aria-label="Main route for all stories" data-test="main">
          <option value="" disabled>Choose a route</option>
          <option v-for="r in routes" :key="key(r)" :value="key(r)">{{ label(r) }}</option>
        </select>
      </label>
      <fieldset class="backups"><legend>Backups, in order (up to 5)</legend>
        <p class="muted small">A story moves to the next backup when its route hits a quota or rate limit. Leave all unticked to keep each story's own backups. Free backups are never added to high-risk stories.</p>
        <label v-for="r in routes.filter(r => key(r) !== main)" :key="key(r)" class="choice">
          <input type="checkbox" :checked="backups.includes(key(r))" :disabled="!backups.includes(key(r)) && backups.length >= 5" @change="toggle(key(r))" />
          <span v-if="backups.includes(key(r))" class="order">{{ backups.indexOf(key(r)) + 1 }}</span>{{ label(r) }}
        </label>
      </fieldset>
      <div class="actions"><button type="button" class="btn primary" data-action="route-all" :disabled="busy || disabled || !main" @click="send">Use for all stories</button>
        <span class="muted small">Saves a new revision for you to review. Human stories are not changed.</span></div>
    </template>
  </details>
</template>
<style scoped>
.route-all { display: grid; gap: var(--gap-sm); }
.route-all summary { cursor: pointer; display: flex; flex-wrap: wrap; gap: var(--gap-sm); align-items: baseline; }
.row { display: grid; grid-template-columns: minmax(7rem, auto) minmax(0, 28rem); gap: var(--gap-sm); align-items: center; }
.backups { display: grid; gap: var(--gap-xs); border: 1px solid var(--surface-border); border-radius: var(--radius); padding: var(--gap-sm) var(--gap); margin: 0; }
.backups p { margin: 0; }
.choice { display: flex; align-items: center; gap: var(--gap-xs); overflow-wrap: anywhere; }
.choice input { accent-color: var(--accent); }
.order { display: inline-grid; place-items: center; min-width: 1.2rem; height: 1.2rem; border-radius: 50%; background: var(--accent); color: var(--bg); font-size: var(--font-size-xs); font-weight: var(--font-weight-strong); }
.actions { display: flex; flex-wrap: wrap; gap: var(--gap-sm); align-items: center; }
.small { font-size: var(--font-size-xs); margin: 0; }
@media (max-width: 600px) { .row { grid-template-columns: 1fr; } }
</style>
