<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import AppSelect from '@/components/AppSelect.vue'
import ModalShell from '@/components/ModalShell.vue'
import { postJson } from '@/lib/api'
import { dateLabel } from '@/lib/operations'
import { usePolledJson } from '@/composables/usePolledJson'
interface Grant { id: string; agent: string; scope: string; state: string; expires_at: number; created_at: number; last_used_at: number | null; token_file: string }
interface Access { grants: Grant[]; token_file: string; auth_enabled: boolean }
const { data, error, refresh } = usePolledJson<Access>('/api/agent-access', 30000)
const showReview = ref(false)
const scope = ref('read')
const days = ref('7')
const busy = ref(false)
const actionError = ref<string | null>(null)
const notice = ref<string | null>(null)
async function approve() {
  busy.value = true; actionError.value = null
  try {
    await postJson('/api/agent-access', { scope: scope.value, days: Number(days.value) })
    notice.value = 'Hermes access approved. The credential stays in its private local file. Register the RCD server through its separate pending MCP change.'
    showReview.value = false; refresh()
  } catch (e) { actionError.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
async function revoke(grant: Grant) {
  busy.value = true; actionError.value = null
  try { await postJson(`/api/agent-access/${grant.id}/revoke`); notice.value = 'Access revoked. Hermes requests using this grant are refused immediately.'; refresh() }
  catch (e) { actionError.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>
<template>
  <section class="card agent-access" aria-labelledby="agent-access-title">
    <header><div><h2 id="agent-access-title" class="section-title has-icon"><AppIcon name="approval" />Agent access</h2><p class="muted small">Give Hermes limited, expiring access to the RCD task board.</p></div><button class="btn" :disabled="!data?.auth_enabled || busy" @click="showReview = true; actionError = null">Review Hermes access</button></header>
    <p v-if="error || actionError" role="status" class="notice-warn">{{ error || actionError }}</p>
    <p v-if="notice" role="status" class="muted">{{ notice }}</p>
    <p class="muted small">Read access shows tasks and agent metadata. Draft access also creates Backlog tasks and edits only Hermes's own Backlog drafts. You review, queue and approve work.</p>
    <p v-if="data && !data.grants.length" class="muted">No access granted. The pending RCD server request cannot authenticate yet.</p>
    <ul v-if="data?.grants.length"><li v-for="grant in data.grants" :key="grant.id"><div><strong>Hermes · {{ grant.scope === 'draft' ? 'Read + planning drafts' : 'Read only' }}</strong><span class="badge">{{ grant.state }}</span><p class="muted small">Expires {{ dateLabel(grant.expires_at) }} · Last used {{ grant.last_used_at ? dateLabel(grant.last_used_at) : 'Never' }}</p></div><button v-if="grant.state === 'active'" class="btn" :disabled="busy" @click="revoke(grant)">Revoke access</button></li></ul>
    <details v-if="data"><summary>Local MCP setup</summary><p class="muted small">The RCD tool server reads this file automatically. Its contents are never shown here. MCP registration still requires its own approval.</p><code>{{ data.token_file }}</code></details>
    <ModalShell v-if="showReview" labelledby="review-access-title" @close="!busy && (showReview = false)">
      <div class="review-access"><header><h2 id="review-access-title">Review Hermes access</h2><button class="btn icon-only" aria-label="Close access review" :disabled="busy" @click="showReview = false"><AppIcon name="close" /></button></header>
        <p class="muted">Approve only the access Hermes needs. This replaces any previous Hermes grant.</p>
        <label>Permissions<AppSelect v-model="scope" :disabled="busy"><option value="read" data-description="Task descriptions, definitions of done, dependencies and agent metadata">Read only</option><option value="draft" data-description="Read tasks, create drafts and edit Hermes's own Backlog drafts">Read + planning drafts</option></AppSelect></label>
        <label>Expires after<AppSelect v-model="days" :disabled="busy"><option value="1">1 day</option><option value="7">7 days</option><option value="30">30 days</option></AppSelect></label>
        <p class="notice-warn">Hermes cannot start runs, approve work, mark tasks complete, delete tasks, or change integrations. Chat, logs, billing and credentials stay outside this access.</p>
        <p class="muted small">A private file on this Pi holds the credential. RCD stores its hash. Access works directly on loopback, expires automatically and can be revoked here.</p>
        <p v-if="actionError" role="status" class="notice-warn">{{ actionError }}</p>
        <footer><button class="btn" :disabled="busy" @click="showReview = false">Cancel</button><button class="btn primary" :disabled="busy" @click="approve">{{ busy ? 'Saving…' : 'Approve Hermes access' }}</button></footer>
      </div>
    </ModalShell>
  </section>
</template>
<style scoped>
header, li, footer { display: flex; justify-content: space-between; align-items: center; gap: var(--gap); flex-wrap: wrap; }
header p { margin-bottom: 0; }
.agent-access { margin: var(--gap-lg) 0; }
ul { padding: 0; list-style: none; }
li { border-top: 1px solid var(--surface-border); padding: var(--gap) 0; }
.badge { margin-left: var(--gap-sm); color: var(--text-muted); font-size: var(--font-size-xs); }
code { overflow-wrap: anywhere; font-size: var(--font-size-xs); }
summary { cursor: pointer; }
.review-access { display: grid; gap: var(--gap); padding: var(--gap-lg); }
label { display: grid; gap: var(--gap-sm); color: var(--text-muted); }
h2, .review-access p { margin: 0; }
footer { justify-content: flex-end; }
</style>
