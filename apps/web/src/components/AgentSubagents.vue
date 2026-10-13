<script setup lang="ts">
import ChipTag from '@/components/ChipTag.vue'
import ReportedValue from '@/components/ReportedValue.vue'
import type { Subagents } from '@/lib/api'
import { formatCount, formatDuration, formatAge } from '@/lib/format'
defineProps<{ data?: Subagents }>()
</script>
<template>
  <details class="subagents">
    <summary>
      Sub-agents &amp; sessions
      <span class="muted small"
        >{{ (data?.agents?.length ?? 0) + (data?.processes?.length ?? 0) }} agents / processes</span
      >
    </summary>
    <p v-if="!data" class="muted small">Sub-agent data not reported.</p>
    <template v-else>
      <h4>Live processes</h4>
      <p v-if="!data.processes.length" class="muted small">No live processes reported.</p>
      <ul class="items">
        <li v-for="p in data.processes" :key="p.pid">
          <strong>{{ p.kind }} · PID {{ p.pid }}</strong>
          <dl>
            <div>
              <dt>Running</dt>
              <dd>{{ formatDuration(p.running_s) }}</dd>
            </div>
            <div>
              <dt>Started with model</dt>
              <dd><ReportedValue :value="p.model" /></dd>
            </div>
            <div>
              <dt>Session</dt>
              <dd><ReportedValue :value="p.session" /></dd>
            </div>
            <div>
              <dt>Working directory</dt>
              <dd><ReportedValue :value="p.cwd" /></dd>
            </div>
          </dl>
        </li>
      </ul>
      <template v-if="data.agents">
        <h4>Configured agents</h4>
        <p v-if="!data.agents.length" class="muted small">No configured agents reported.</p>
        <ul class="items">
          <li v-for="a in data.agents" :key="a.id">
            <strong>{{ a.name || a.id }}</strong>
            <ChipTag v-if="a.default" tone="accent">Default</ChipTag>
            <dl>
              <div>
                <dt>ID</dt>
                <dd>{{ a.id }}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd><ReportedValue :value="a.model" /></dd>
              </div>
              <div>
                <dt>Sessions (24h)</dt>
                <dd>
                  <ReportedValue :value="a.sessions_24h" :format="formatCount" />
                </dd>
              </div>
              <div>
                <dt>Session tokens (24h)</dt>
                <dd>
                  <ReportedValue :value="a.tokens_24h" :format="formatCount" />
                </dd>
              </div>
              <div>
                <dt>Last active</dt>
                <dd>
                  <ReportedValue :value="a.last_active_s" :format="formatAge" />
                </dd>
              </div>
              <div>
                <dt>Bindings</dt>
                <dd>{{ a.bindings }}</dd>
              </div>
              <div>
                <dt>Workspace</dt>
                <dd><ReportedValue :value="a.workspace" /></dd>
              </div>
            </dl>
          </li>
        </ul>
      </template>
      <template v-if="data.sessions">
        <h4>Recent sessions</h4>
        <p v-if="!data.sessions.length" class="muted small">No recent sessions reported.</p>
        <ul class="items">
          <li v-for="s in data.sessions" :key="s.id">
            <strong>{{ s.title || 'Untitled session' }}</strong>
            <dl>
              <div>
                <dt>ID</dt>
                <dd>{{ s.id }}</dd>
              </div>
              <div>
                <dt>Workspace</dt>
                <dd>{{ s.workspace || 'not reported' }}</dd>
              </div>
              <div>
                <dt>Last active</dt>
                <dd>{{ s.last_active || 'not reported' }}</dd>
              </div>
            </dl>
          </li>
        </ul>
      </template>
    </template>
  </details>
</template>
<style scoped>
.subagents {
  border-top: 1px solid var(--panel-border);
  padding-top: var(--gap-sm);
  min-width: 0;
}
summary {
  cursor: pointer;
  min-height: var(--touch-target);
  font-weight: var(--font-weight-strong);
}
summary span {
  font-weight: var(--font-weight);
}
h4 {
  margin: var(--gap) 0 var(--gap-sm);
  font-size: var(--font-size-sm);
}
.items {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}
.items li {
  padding: var(--gap-sm);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  font-size: var(--font-size-sm);
  overflow-wrap: anywhere;
}
dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap-sm);
  margin: var(--gap-sm) 0 0;
}
dt {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
}
dd {
  margin: 0;
}
</style>
