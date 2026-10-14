<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { useThemeStore } from '@/stores/theme'
import { useAuthStore } from '@/stores/auth'
import { patchJson } from '@/lib/api'
defineProps<{ compact?: boolean }>()
const theme = useThemeStore()
const auth = useAuthStore()
async function toggle() {
  theme.toggle()
  if (auth.access && auth.user?.method === 'google') {
    try { await patchJson('/api/profile/appearance', { theme: theme.mode }) } catch { /* Local theme remains usable if profile is temporarily unavailable. */ }
  }
}
const label = computed(() => theme.mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode')
</script>

<template>
  <button type="button" class="btn theme-toggle" :class="{ compact }" :aria-label="label" :title="label" @click="toggle">
    <AppIcon :name="theme.mode === 'dark' ? 'sun' : 'moon'" />
    <span class="theme-label">{{ theme.mode === 'dark' ? 'Light mode' : 'Dark mode' }}</span>
  </button>
</template>

<style scoped>
.theme-toggle { flex: none; min-width: var(--touch-target); }
.compact { padding: 0; }
.compact .theme-label { display: none; }
@media (max-width: 600px) {
  .theme-toggle { padding: 0; }
  .theme-label { display: none; }
}
</style>
