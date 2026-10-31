<script setup lang="ts">
// Every key and sign-in RCD can use, in the same card as the setup checklist: whether it is in place, what it is for in a line, and where to add it.
import { computed, onMounted, ref } from 'vue'
import ManagedItem from '@/components/ManagedItem.vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import { getJson } from '@/lib/api'

interface KeyRow { id: string; label: string; level: 'required' | 'recommended' | 'optional'; purpose: string; obtain: string; scope: string; in_place: boolean | null; detail: string }
type Spending = Record<string, number | string | boolean | null>
const props = defineProps<{ credentials: { provider: string; hint: string }[]; secrets: Record<string, string>; busy: boolean; shareOn: boolean; spending: Spending | null }>()
const emit = defineEmits<{ secret: [provider: string, value: string]; save: [provider: string]; remove: [provider: string]; share: [on: boolean]; spend: [] }>()
const data = ref<{ keys: KeyRow[]; basic_use_ready: boolean } | null>(null)
const LEVEL = { required: 'Required', recommended: 'Recommended', optional: 'Optional' }
// The keys RCD stores. They show even when the guide cannot be read, so a key can always be saved.
const SAVED = [
  { id: 'openrouter', provider: 'openrouter', label: 'OpenRouter', level: 'recommended', purpose: 'Spending, shared agent routes and image generation.' },
  { id: 'fal', provider: 'fal', label: 'fal.ai (media)', level: 'optional', purpose: 'Video and image generation. Agents never receive it.' },
  { id: 'upubhub', provider: 'upubhub', label: 'upubhub.com', level: 'optional', purpose: 'Publish token from upubhub Dashboard → Connections, for upubhub templates. Agents never receive it.' },
  { id: 'discord', provider: 'discord', label: 'Discord bot', level: 'optional', purpose: 'Notifications from your own bot. Empty uses this installation’s Hermes bot.' },
] as const
const guide = (id: string) => data.value?.keys.find(k => k.id === id)
const saved = (provider: string) => props.credentials.find(c => c.provider === provider)
const first = (text: string) => text.split(/(?<=[.!?])\s/)[0] ?? text
const link = (id: string) => { const o = guide(id)?.obtain ?? ''; return /^https:\/\//.test(o) ? o : '' }
const agent = computed(() => guide('agent'))
const github = computed(() => guide('github'))
async function load() {
  try {
    const body = await getJson<{ keys: KeyRow[]; basic_use_ready: boolean }>('/api/keys')
    data.value = Array.isArray(body?.keys) ? body : null      // an unexpected answer falls back to the plain inputs
  } catch { data.value = null }
}
defineExpose({ load })
onMounted(load)
</script>
<template>
  <ul class="items" aria-label="Private credentials">
    <ManagedItem v-if="agent" name="Signed-in agent" data-key="agent" tag="Required" :mark="agent.in_place ? 'ok' : 'missing'" :word="agent.in_place ? 'ready' : 'none yet'" :detail="agent.in_place ? agent.detail : 'No agent is signed in on this machine yet.'" health-disabled>
      <a href="#agent-tools" class="btn">Open Agent tools</a>
    </ManagedItem>

    <ManagedItem v-for="k in SAVED" :key="k.id" :name="k.label" :data-key="k.id" :tag="LEVEL[guide(k.id)?.level ?? k.level]" :mark="saved(k.provider) ? 'ok' : 'info'"
      :word="saved(k.provider) ? `Saved ····${saved(k.provider)!.hint}` : 'not set'" :detail="first(guide(k.id)?.purpose ?? k.purpose)" health-disabled>
      <input class="input key-input" type="password" autocomplete="new-password" :aria-label="k.provider + ' credential'" :value="secrets[k.provider]" :placeholder="saved(k.provider) ? 'Paste a new key to replace it' : 'Paste key'"
        @input="emit('secret', k.provider, ($event.target as HTMLInputElement).value)" />
      <button type="button" class="btn primary" :disabled="busy || !secrets[k.provider]" @click="emit('save', k.provider)">Save credential</button>
      <button v-if="saved(k.provider)" type="button" class="btn" :disabled="busy" @click="emit('remove', k.provider)">Remove</button>
      <template #more>
        <a v-if="link(k.id)" :href="link(k.id)" target="_blank" rel="noopener noreferrer" class="small">Get a key ↗</a>
        <template v-if="k.provider === 'openrouter' && saved('openrouter')">
          <ToggleSwitch label="Share with Hermes and OpenClaw" data-testid="share-key" :model-value="shareOn" :disabled="busy"
            hint="Off by default. Claude, Codex and Grok never receive it; use a dedicated key with a credit limit set at OpenRouter." @change="emit('share', $event)" />
          <button type="button" class="btn small-btn" :disabled="busy" @click="emit('spend')">Check spending</button>
        </template>
        <span v-if="k.provider === 'openrouter' && saved('openrouter')" class="muted small">Claude, Codex and Grok never receive it; use a dedicated key with a credit limit.</span>
        <span v-if="k.provider === 'openrouter' && spending" class="spend small" role="status">This month: ${{ spending.month_usd ?? '—' }} API · ${{ spending.byok_month_usd ?? '—' }} BYOK · limit {{ spending.limit_usd != null ? '$' + spending.limit_usd : 'not set' }}{{ spending.limit_reset ? ` (${spending.limit_reset})` : '' }}</span>
      </template>
    </ManagedItem>

    <ManagedItem v-if="github" name="GitHub access" data-key="github" tag="Optional" mark="info" word="signed in with gh" :detail="first(github.purpose)" health-disabled>
      <RouterLink to="/profile#github-settings" class="btn">Open GitHub settings</RouterLink>
    </ManagedItem>
  </ul>
</template>
<style scoped>
.items { display: grid; gap: var(--gap-sm); padding: 0; margin: 0; list-style: none; }
.key-input { flex: 1 1 12rem; min-width: 0; }
.small { font-size: var(--font-size-xs); margin: 0; }
.small-btn { padding: 0 var(--gap-sm); }
.spend { flex-basis: 100%; }
</style>
