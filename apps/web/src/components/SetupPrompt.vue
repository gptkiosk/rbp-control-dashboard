<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getJson, patchJson } from '@/lib/api'
import type { Profile } from '@/lib/profile'
const auth = useAuthStore(), route = useRoute()
const profile = ref<Profile | null>(null), busy = ref(false), error = ref('')
watch([() => auth.access, () => auth.user?.email, () => route.path], async (_, _old, cleanup) => {
  let current = true; cleanup(() => { current = false })
  profile.value = null
  if (!auth.access || route.path === '/setup' || (auth.enabled && auth.user?.method !== 'google')) return
  try { const p = await getJson<Profile>('/api/profile'); if (current) profile.value = p } catch { /* Setup remains available from Settings. */ }
}, { immediate: true })
async function later() {
  if (!profile.value || busy.value) return
  busy.value = true; error.value = ''
  try { profile.value = await patchJson<Profile>('/api/profile/setup', { ...profile.value.preferences.setup, step: profile.value.preferences.setup?.step ?? 0, confirmed: profile.value.preferences.setup?.confirmed ?? [], status: 'deferred' }) }
  catch { error.value = 'Could not save your choice. Try again.' }
  finally { busy.value = false }
}
</script>
<template>
  <aside v-if="profile && (!profile.preferences.setup || ['new','in_progress'].includes(profile.preferences.setup.status))" class="setup-prompt card" aria-label="Get started with RCD">
    <div><strong>{{ profile.preferences.setup?.status === 'in_progress' ? 'Continue your RCD setup' : 'Welcome to RCD' }}</strong><p>Check your Pi and agents, connect sign-in and provider credentials, then learn your way around.</p><p v-if="error" role="alert">{{ error }}</p></div>
    <div class="prompt-actions"><RouterLink to="/setup" class="btn primary">{{ profile.preferences.setup?.status === 'in_progress' ? 'Continue setup' : 'Start setup wizard' }}</RouterLink><button class="btn" :disabled="busy" @click="later">Later</button></div>
  </aside>
</template>
<style scoped>
.setup-prompt { display:flex; justify-content:space-between; gap:var(--gap); align-items:center; flex-wrap:wrap; margin-bottom:var(--gap-lg); background:var(--agent-glass); }
.setup-prompt p { margin:var(--gap-xs) 0 0; color:var(--text-muted); font-size:var(--font-size-sm); }
.prompt-actions { display:flex; gap:var(--gap-sm); flex-wrap:wrap; }
</style>
