<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJson } from '@/lib/api'
interface KeyRow { id: string; label: string; level: 'required' | 'recommended' | 'optional'; purpose: string; obtain: string; scope: string; in_place: boolean | null; detail: string }
const data = ref<{ keys: KeyRow[]; basic_use_ready: boolean } | null>(null)
const failed = ref(false)
const levelText = { required: 'Required for basic use', recommended: 'Recommended', optional: 'Optional' }
async function load() {
  try { data.value = await getJson('/api/keys') } catch { failed.value = true }
}
defineExpose({ load })
onMounted(load)
const isLink = (s: string) => /^https:\/\//.test(s)
</script>
<template>
  <section class="keys-guide" aria-labelledby="keys-guide-title">
    <h3 id="keys-guide-title">Which keys you need</h3>
    <p v-if="failed" class="muted small">The key guide could not be loaded.</p>
    <template v-if="data">
      <p class="small" role="status">
        <strong>Basic use needs one thing:</strong> an agent signed in on this Mac.
        {{ data.basic_use_ready ? 'You have that.' : 'None is available yet; open Agents, then Agent tools.' }}
        Everything else below adds a feature, and you can add it later or when a project asks for it.
      </p>
      <ul class="keys">
        <li v-for="k in data.keys" :key="k.id" :data-key="k.id">
          <div class="row">
            <strong>{{ k.label }}</strong>
            <span class="badge" :class="k.level">{{ levelText[k.level] }}</span>
            <span class="muted small">{{ k.in_place === null ? k.detail : k.in_place ? '✓ ' + k.detail : 'Not in place' }}</span>
          </div>
          <p class="muted small">{{ k.purpose }}</p>
          <p class="muted small">
            Get it: <a v-if="isLink(k.obtain)" :href="k.obtain" target="_blank" rel="noopener noreferrer">{{ k.obtain }}</a><span v-else>{{ k.obtain }}</span>
            · {{ k.scope }}
          </p>
        </li>
      </ul>
    </template>
  </section>
</template>
<style scoped>
.keys-guide { display: flex; flex-direction: column; gap: var(--gap); }
.keys { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--gap); }
.keys li { padding-bottom: var(--gap); border-bottom: 1px solid var(--glass-border); }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-sm, 0.5rem); }
.badge { font-size: var(--font-size-sm); padding: 0 0.5rem; border: 1px solid var(--glass-border); border-radius: 999px; }
.badge.required { border-color: var(--accent, currentColor); }
p { margin: 0; }
</style>
