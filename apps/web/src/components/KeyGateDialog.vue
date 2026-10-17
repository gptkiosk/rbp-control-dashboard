<script setup lang="ts">
import { ref } from 'vue'
import ModalShell from '@/components/ModalShell.vue'
import { putJson } from '@/lib/api'
export interface MissingKey { id: string; label: string; provider: string | null; providers?: string[]; blocking: boolean; why: string; obtain: string; scope: string }
const props = defineProps<{ missing: MissingKey[] }>()
const emit = defineEmits<{ close: []; saved: []; proceed: [] }>()
const values = ref<Record<string, string>>({})
const chosen = ref<Record<string, string>>({})
const busy = ref(false), error = ref('')
const providerOf = (m: MissingKey) => chosen.value[m.id] || m.providers?.[0] || m.provider || ''
async function save(m: MissingKey) {
  const provider = providerOf(m), value = (values.value[m.id] || '').trim()
  if (!provider || !value) return
  busy.value = true; error.value = ''
  try { await putJson(`/api/profile/credentials/${provider}`, { value }); values.value[m.id] = ''; emit('saved') } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
const blocked = () => props.missing.some(m => m.blocking)
const isLink = (s: string) => /^https:\/\//.test(s)
</script>
<template>
  <ModalShell labelledby="key-gate-title" @close="emit('close')">
    <div class="gate">
      <h2 id="key-gate-title">Add keys before this project starts</h2>
      <p class="muted small">This project's text suggests it needs the keys below. Adding one now avoids a failure later. Keys are saved encrypted and are never shown again or given to agents.</p>
      <div v-for="m in missing" :key="m.id" class="item" :data-gate="m.id">
        <strong>{{ m.label }}</strong> <span v-if="m.blocking" class="muted small">(required)</span>
        <p class="small">{{ m.why }}</p>
        <p class="muted small">Get it: <a v-if="isLink(m.obtain)" :href="m.obtain" target="_blank" rel="noopener noreferrer">{{ m.obtain }}</a><span v-else>{{ m.obtain }}</span> · {{ m.scope }}</p>
        <div v-if="m.provider" class="entry">
          <select v-if="(m.providers?.length || 0) > 1" v-model="chosen[m.id]" class="input" :aria-label="`${m.label} provider`"><option v-for="p in m.providers" :key="p" :value="p">{{ p }}</option></select>
          <input v-model="values[m.id]" class="input" type="password" autocomplete="new-password" :aria-label="`${m.label} value`" placeholder="Paste the key" />
          <button type="button" class="btn" :disabled="busy || !(values[m.id] || '').trim()" @click="save(m)">Save key</button>
        </div>
      </div>
      <p v-if="error" class="error-text" role="alert">{{ error }}</p>
      <footer>
        <button type="button" class="btn" @click="emit('close')">Cancel</button>
        <button type="button" class="btn primary" :disabled="blocked()" @click="emit('proceed')">Continue without these keys</button>
      </footer>
    </div>
  </ModalShell>
</template>
<style scoped>
.gate { padding: var(--gap-lg); display: flex; flex-direction: column; gap: var(--gap); }
.item { padding-bottom: var(--gap); border-bottom: 1px solid var(--glass-border); display: flex; flex-direction: column; gap: var(--gap-xs); }
.entry { display: flex; gap: var(--gap); flex-wrap: wrap; }
.entry .input { flex: 1; min-width: 12rem; }
footer { display: flex; justify-content: flex-end; gap: var(--gap); }
p { margin: 0; }
</style>
