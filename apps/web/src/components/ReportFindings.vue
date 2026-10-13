<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import FindingTaskDialog from '@/components/FindingTaskDialog.vue'
import type { FindingTaskStatus, ReportFinding } from '@/lib/operations'

defineProps<{ reportId: string; reportModified: number; findings: ReportFinding[]; linked: Record<string, FindingTaskStatus | null> }>()
const emit = defineEmits<{ changed: [] }>()
const active = ref<ReportFinding | null>(null)
const SEVERITY = { warn: 'Warning', crit: 'Critical' } as const
</script>
<template>
  <section class="card findings" aria-labelledby="findings-title">
    <h2 id="findings-title">Findings</h2>
    <p class="muted small">Only warning and critical sections can become tasks. A task is created in Backlog and is not started.</p>
    <ul class="finding-list">
      <li v-for="f in findings" :key="f.id" class="finding" :data-severity="f.status">
        <div class="finding-head">
          <strong>{{ f.id }}</strong>
          <span class="severity" :data-severity="f.status">{{ SEVERITY[f.status] }}</span>
        </div>
        <p>{{ f.reason }}</p>
        <div class="finding-action">
          <template v-if="linked[f.id]">
            <span class="muted small">Task #{{ linked[f.id]!.task_id }} · {{ linked[f.id]!.task_status }}<template v-if="linked[f.id]!.run_status"> · run {{ linked[f.id]!.run_status }}</template></span>
            <RouterLink class="btn" :to="{ path: '/tasks', query: { card: String(linked[f.id]!.task_id) } }">Open existing</RouterLink>
          </template>
          <button v-else class="btn" @click="active = f">Create task</button>
        </div>
      </li>
    </ul>
    <FindingTaskDialog v-if="active" :report-id="reportId" :report-modified="reportModified" :finding="active" @close="active = null" @created="emit('changed')" />
  </section>
</template>
<style scoped>
.findings { margin: var(--gap-lg) 0; display: grid; gap: var(--gap); }
.findings h2 { font-size: var(--font-size-lg); margin: 0; }
.finding-list { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--gap-sm); }
.finding { padding: var(--gap); border: 1px solid var(--surface-border); border-left: 3px solid var(--surface-border); border-radius: var(--radius-sm); overflow-wrap: anywhere; }
.finding[data-severity='crit'] { border-left-color: var(--danger); }
.finding[data-severity='warn'] { border-left-color: var(--warn); }
.finding p { margin: var(--gap-sm) 0 0; }
.finding-head, .finding-action { display: flex; align-items: center; gap: var(--gap); flex-wrap: wrap; }
.finding-action { margin-top: var(--gap-sm); justify-content: space-between; }
.severity { display: inline-block; padding: 0 var(--gap-sm); border: 1px solid currentColor; border-radius: var(--radius-sm); font-size: var(--font-size-xs); font-weight: 600; white-space: nowrap; }
.severity[data-severity='crit'] { color: var(--danger); }
.severity[data-severity='warn'] { color: var(--warn); }
</style>
