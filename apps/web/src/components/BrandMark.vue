<script lang="ts">
// The MCD mark: an M-shaped pulse (monitoring + "M") in a rounded gradient tile with a status
// dot. Same geometry as public/favicon.svg; colours come from the --brand-* tokens.
// Each instance needs its own gradient id, or several marks on one page would share one.
let instances = 0
</script>

<script setup lang="ts">
instances += 1
const gradientId = `mcd-brand-${instances}`
</script>

<template>
  <svg class="brand-mark" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient :id="gradientId" x1="4" y1="2" x2="60" y2="62" gradientUnits="userSpaceOnUse">
        <stop offset="0" class="stop-from" />
        <stop offset="1" class="stop-to" />
      </linearGradient>
    </defs>
    <rect x="2" y="2" width="60" height="60" rx="14" :fill="`url(#${gradientId})`" />
    <polyline
      points="9,38 17,38 22.5,19 32,41 41.5,19 47,38 55,38"
      class="pulse"
      fill="none"
      stroke-width="5.2"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <circle cx="50" cy="50.5" r="3" class="dot" />
  </svg>
</template>

<style scoped>
.brand-mark {
  width: var(--brand-size);
  height: var(--brand-size);
  flex-shrink: 0;
  display: block;
}
.stop-from { stop-color: var(--brand-from); }
.stop-to { stop-color: var(--brand-to); }
.pulse { stroke: var(--brand-ink); }
.dot { fill: var(--brand-ink); opacity: 0.92; }
</style>
