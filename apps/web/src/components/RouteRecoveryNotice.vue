<script setup lang="ts">
import { computed } from 'vue'
import type { RecoveryInfo } from '@/lib/routeRecovery'
const props = defineProps<{ info?: RecoveryInfo|null; failed?: boolean; agent?: string|null; model?: string|null }>()
const recommendations = computed(() => (props.info?.recommendations ?? []).filter(r => !props.agent || (r.agent === props.agent && (!props.model || r.model === props.model))))
</script>
<template>
  <aside v-if="failed || recommendations.length" class="recovery-notice" aria-label="Model route advice">
    <template v-if="recommendations.length"><p v-for="r in recommendations" :key="r.agent + r.model"><strong>{{ r.agent }} · {{ r.model }}</strong> — {{ r.message }}</p></template>
    <p v-else>This attempt needs another try. You can choose another route while keeping this task and its history.</p>
    <p class="small muted">Membership routes use account quota. Paid API routes add provider charges. Free endpoints can be limited or unavailable.</p>
    <RouterLink class="btn small-btn" to="/profile#route-recovery">Configure recovery routes and enable fallback</RouterLink>
  </aside>
</template>
<style scoped>
.recovery-notice{display:grid;gap:var(--gap-sm);padding:var(--gap);border:1px solid var(--warn);border-radius:var(--radius);background:var(--panel)}
p{margin:0;overflow-wrap:anywhere}.recovery-notice .btn{justify-self:start;white-space:normal}.small{font-size:var(--font-size-xs)}
</style>
