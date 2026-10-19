<script setup lang="ts">
// The same opening for every page: icon and title, one line saying what it is (with a How-to link into the documentation), and the page's actions on the right.
import AppIcon from '@/components/AppIcon.vue'
import type { IconName } from '@/icons/icons'
defineProps<{ id: string; title: string; icon: IconName; sub?: string; help?: string }>()
</script>
<template>
  <header class="page-head">
    <div class="titles">
      <h1 :id="id" class="page-title has-icon"><AppIcon :name="icon" size="lg" />{{ title }}</h1>
      <p v-if="sub || help || $slots.sub" class="sub muted small"><slot name="sub">{{ sub }}</slot><template v-if="help"> <RouterLink :to="`/help?topic=${help}`" class="howto">How-to</RouterLink></template></p>
    </div>
    <div v-if="$slots.default" class="head-actions"><slot /></div>
  </header>
</template>
<style scoped>
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--gap); flex-wrap: wrap; }
.titles { display: grid; gap: var(--gap-xs); min-width: 0; }
.sub { margin: 0; }
.head-actions { display: flex; align-items: center; gap: var(--gap-sm); flex-wrap: wrap; }
.howto { white-space: nowrap; margin-left: var(--gap-xs); }
</style>
