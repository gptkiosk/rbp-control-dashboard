<script setup lang="ts">
import { RouterLink } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
</script>

<template>
  <section class="not-found">
    <h1 class="has-icon"><AppIcon name="alert" size="lg" />Not found</h1>
    <p>There is nothing at this address.</p>
    <RouterLink to="/" class="back">Back to Overview</RouterLink>
  </section>
</template>

<style scoped>
.not-found {
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  padding: var(--gap-lg);
}

h1 {
  margin: 0 0 var(--gap-sm);
  font-size: var(--font-size-xl);
}

p {
  margin: 0 0 var(--gap);
  color: var(--text-muted);
}

.back {
  color: var(--accent);
}
</style>
