<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getJson, type ReleaseEnvelope } from '@/lib/api'
import { releaseLabel } from '@/lib/releaseLabel'

const release = ref<ReleaseEnvelope | null>(null)
const year = new Date().getFullYear()
const webSha = import.meta.env.VITE_APP_VERSION ?? ''
const label = computed(() => releaseLabel(release.value, webSha))
const owner = 'Bamcio LLC'
const product = computed(() => release.value?.product || 'Raspberry Pi Control Dashboard')

onMounted(async () => {
  try {
    release.value = await getJson<ReleaseEnvelope>('/api/release')
  } catch {
    /* footer degrades to the copyright line only */
  }
})
</script>

<template>
  <footer class="footer">
    <p class="copyright">© {{ year }} {{ product }} · {{ owner }}</p>
    <p v-if="label" class="release" data-testid="release-label">{{ label }}</p>
  </footer>
</template>

<style scoped>
.footer {
  margin-top: var(--gap-xl);
  padding: var(--gap) 0;
  border-top: 1px solid var(--panel-border);
  text-align: center;
}

.footer p {
  margin: 0;
}

.copyright {
  font-size: var(--font-size-sm);
}

.release {
  margin-top: var(--gap-xs);
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  overflow-wrap: anywhere;
}
</style>
