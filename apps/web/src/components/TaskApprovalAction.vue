<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ModalShell from '@/components/ModalShell.vue'
import { getJson, postJson, type Card } from '@/lib/api'
import MediaCallout from '@/components/MediaCallout.vue'
import { useProjectMedia } from '@/composables/useProjectMedia'
import { awaitsApproval } from '@/lib/cards'
import type { Project } from '@/lib/projects'

const props = defineProps<{ card: Card; hideMediaLink?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const busy = ref(false), error = ref(''), decisionOpen = ref(false), decision = ref('')
const option = ref(''), decisionId = ref('')
// A human story about media goes straight to the media studio, with where the slots stand and what is left to spend.
const { media, link: mediaLink } = useProjectMedia(() => props.card)
const gate = computed(() => props.card.last_run?.approval)
const kind = computed(() => {
  const c = props.card
  if (c.last_run?.stage === 'awaiting_approval' && gate.value) return 'gate'
  if (c.project?.role === 'story') {
    if (c.blocked_by.length) return null
    if (c.assignee_type === 'human' && ['backlog','review'].includes(c.column)) return 'decision'
    if (c.column !== 'review') return null
    if (c.last_run?.stage === 'awaiting_approval') return 'output'
    if (c.last_run?.stage === 'succeeded') return 'handoff'
    return null
  }
  return !c.project && awaitsApproval(c) && ['review','backlog'].includes(c.column) ? 'run' : null
})
const label = computed(() => ({ gate:'Answer run decision', decision:'Record decision', output:'Approve & continue', handoff:'Approve handoff', run:'Approve run' }[kind.value || 'run']))
const explanation = computed(() => {
  if (kind.value === 'handoff') return 'Accept the latest completed result and release ready dependent stories. Open the task to inspect its evidence before approving.'
  if (kind.value === 'output') return 'Continue the same read-only story and allow RCD to save its proposed Markdown document.'
  return props.card.approval_reasons.join('; ') || 'Record your decision before dependent work can start.'
})
async function approve(reject = false) {
  if (busy.value || !kind.value) return
  if (['decision','gate'].includes(kind.value) && !decisionOpen.value) { decision.value=''; option.value=''; decisionId.value=crypto.randomUUID(); decisionOpen.value=true; return }
  const c = props.card, action = kind.value, runId = c.last_run?.id
  busy.value=true; error.value=''
  try {
    if (action === 'gate') {
      if (!gate.value || c.last_run?.decision_pending) throw new Error('This decision is already being applied. Refresh the task.')
      await postJson(`/api/runs/${runId}/decision`, {
        approval_id: gate.value.approval_id, approval_nonce: gate.value.nonce, decision_id: decisionId.value,
        verdict: reject ? 'reject' : decision.value.trim() || option.value ? 'answer' : 'approve',
        answer_text: decision.value.trim() || null, option_id: option.value || null,
        approved_output_sha256: gate.value.proposed_output?.sha256 || null,
      })
    } else if (action === 'run') await postJson(`/api/cards/${c.id}/approve`, { challenge: c.approval_challenge, pin: c.approval_pin })
    else {
      const base = `/api/projects/${c.project!.id}`
      const p = await getJson<Project>(base)
      const task = p.tasks.find(t => t.card_id === c.id && t.role === 'story')
      if (!task || !['active','paused'].includes(p.state)) throw new Error('This story is no longer available for approval. Refresh the task.')
      if (action === 'decision') {
        if (!decision.value.trim()) throw new Error('Write the operator decision before approving it.')
        await postJson(`${base}/stories/${c.id}/accept`, { revision:p.revision, run_id:null, summary:decision.value.trim(), snapshot:false, files:[] })
      } else {
        if (task.column !== 'review' || task.run_id !== runId) throw new Error('The latest run changed. Review the current result before approving.')
        if (action === 'output') {
          if (!task.output_approval || task.output_approval.run_id !== runId) throw new Error('This run is no longer waiting for output approval.')
          await postJson(`${base}/stories/${c.id}/continue-output`, { revision:p.revision, run_id:runId, approve_output:true })
        } else {
          if (task.run_stage !== 'succeeded') throw new Error('Only a completed successful result can be approved.')
          const artifact = await getJson<{files:string[]; output?:{sha256:string} | null}>(`${base}/stories/${c.id}/artifact`)
          if (artifact.files.length) throw new Error('This handoff has workspace changes. Review and select those files in Projects before approval.')
          const summary = p.memory.find(m => m.kind === 'proposal' && m.run_id === runId)?.text?.trim() || c.last_run?.result_text?.trim()
          if (!summary || summary.length > 12000) throw new Error('Open the project review to write a verified handoff summary.')
          await postJson(`${base}/stories/${c.id}/accept`, { revision:p.revision, run_id:runId, summary, snapshot:false, files:[], ...(artifact.output ? {output_sha256:artifact.output.sha256} : {}) })
        }
      }
    }
    decisionOpen.value=false; emit('changed')
  } catch (e) { error.value=e instanceof Error ? e.message : String(e) }
  finally { busy.value=false }
}
</script>

<template>
  <div v-if="kind" class="task-approval" @click.stop @dragstart.stop.prevent>
    <button type="button" class="btn primary approval-button" :disabled="busy || !!card.last_run?.decision_pending" :title="explanation" @click="approve()">
      <AppIcon name="approval" size="sm" />{{ busy ? 'Approving…' : label }}
    </button>
    <MediaCallout v-if="kind === 'decision' && !hideMediaLink" :media="media" :link="mediaLink" compact />
    <p v-if="kind === 'run' && card.approval_reasons.length" class="approval-reason">{{ card.approval_reasons.join('; ') }}</p>
    <p v-if="error && !decisionOpen" class="error-text" role="alert">{{ error }} <RouterLink v-if="card.project" :to="`/projects?project=${card.project.id}&view=work&story=${card.id}&action=review`">Open project review</RouterLink></p>
    <ModalShell class="decision-dialog" v-if="decisionOpen" :labelledby="`decision-title-${card.id}`" @close="decisionOpen=false">
      <form class="decision-form" @submit.prevent="approve()">
        <h2 :id="`decision-title-${card.id}`">{{ kind === 'gate' ? 'Run needs your decision' : 'Record operator decision' }}</h2>
        <p><strong>{{ card.title }}</strong></p>
        <p class="instructions">{{ kind === 'gate' ? gate?.question : card.body }}</p>
        <pre v-if="kind === 'gate' && gate?.proposed_output?.preview" class="log-window">{{ gate.proposed_output.preview }}</pre>
        <label v-if="kind === 'gate' && gate?.options?.length">Choose an option<select v-model="option" class="input"><option value="">Select…</option><option v-for="o in gate.options" :key="o.id" :value="o.id">{{ o.label }}</option></select></label>
        <p v-if="card.acceptance" class="instructions muted">Definition of done: {{ card.acceptance }}</p>
        <p v-if="media?.available" class="media-box" data-testid="media-box">
          <RouterLink :to="mediaLink" @click="decisionOpen = false">Open the media studio →</RouterLink>
          <template v-if="media.summary"><br />{{ media.summary.text }}<br /><button type="button" class="btn" @click="decision = media.summary!.text">Use this as my decision</button></template>
        </p>
        <label :for="`decision-${card.id}`">Your decision</label>
        <textarea :id="`decision-${card.id}`" v-model="decision" class="input" rows="7" :required="kind !== 'gate'" maxlength="12000" data-autofocus placeholder="Record each required choice and any conditions." />
        <p v-if="error" class="error-text" role="alert">{{ error }}</p>
        <div class="decision-actions"><button type="button" class="btn" @click="decisionOpen=false">Keep waiting</button><button v-if="kind === 'gate'" type="button" class="btn" :disabled="busy" @click="approve(true)">Reject decision</button><button class="btn primary" :disabled="busy || (kind !== 'gate' && !decision.trim())">{{ busy ? 'Approving…' : kind === 'gate' ? 'Resume run' : 'Approve decision' }}</button></div>
      </form>
    </ModalShell>
  </div>
</template>

<style scoped>
.task-approval { width:100%; }
.decision-dialog :deep(.modal-panel) { padding:var(--gap-lg); }
.approval-button { display:inline-flex; align-items:center; justify-content:center; gap:var(--gap-xs); max-width:100%; font-size:var(--font-size-sm); white-space:normal; text-align:center; }
.media-box { font-size:var(--font-size-sm); }
.approval-reason,.error-text { font-size:var(--font-size-xs); margin:var(--gap-xs) 0 0; overflow-wrap:anywhere; }
.decision-form { display:grid; gap:var(--gap); }
.decision-form h2,.decision-form p { margin:0; }
.decision-form h2 { font-size:var(--font-size-xl); font-weight:var(--font-weight-strong); }
.decision-actions { display:flex; justify-content:flex-end; gap:var(--gap-sm); flex-wrap:wrap; margin-top:var(--gap); }
@media (max-width:600px) { .decision-dialog :deep(.modal-panel) { padding:var(--gap); } }
</style>
