<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import RouteRecoveryNotice from './RouteRecoveryNotice.vue'
import AppIcon from '@/components/AppIcon.vue'
import { getJson, postJson, type Card } from '@/lib/api'
import { agentLabel } from '@/lib/cards'
import type { Project, ProjectNode } from '@/lib/projects'

const props = defineProps<{ card: Card }>()
const emit = defineEmits<{ changed: [] }>()
const project = ref<Project | null>(null)
const busy = ref(false), error = ref(''), notice = ref('')
const story = computed(() => props.card.project?.role === 'story' && props.card.assignee_type !== 'human')
const visible = computed(() => story.value && ['failed', 'review', 'done'].includes(props.card.column))
const task = computed(() => project.value?.tasks.find(t => t.card_id === props.card.id && t.role === 'story'))
const succeededRerunnable = computed(() => story.value && task.value?.run_stage === 'succeeded' &&
  ((task.value.column === 'review' && project.value?.state === 'active') ||
   (task.value.column === 'done' && ['active', 'complete'].includes(project.value?.state ?? ''))))
// A run that finished and reported unfinished work can be accepted on the operator's say-so; a crash or timeout cannot (there is no report to accept).
const acceptable = computed(() => !!task.value?.incomplete_reason && !!task.value.run_id && task.value.run_id === props.card.last_run?.id && ['active', 'paused'].includes(project.value?.state ?? '') && !notice.value)
const timedOut = computed(() => props.card.last_run?.stage === 'timeout')
const timeoutAck = ref(false)
// After a timeout RCD cannot tell what the attempt changed or whether it is still running, so a new attempt needs the operator's word that the partial work was reviewed.
const ack = () => (timedOut.value ? { acknowledge_timeout: true } : {})
const ready = computed(() => visible.value && !notice.value && project.value?.state === 'active' && task.value?.column === 'failed' && task.value.run_id === props.card.last_run?.id && (!timedOut.value || timeoutAck.value))
const rerunReady = computed(() => ready.value || (!!succeededRerunnable.value && !busy.value && !notice.value && task.value?.run_id === props.card.last_run?.id))
const alternatives = computed(() => (task.value?.retry_routes ?? []).filter(r => r.agent !== props.card.agent || r.model !== (props.card.model ?? '')))
const limited = computed(() => /session limit|usage limit|quota|rate.?limit|limit reached/i.test(props.card.last_run?.error ?? ''))
const freeRoutes = computed(() => task.value?.free_retry_routes ?? [])
const showFree = ref(false), freeModel = ref(''), freeTarget = ref('')
const lowCost = computed(() => task.value?.low_cost_routes ?? [])
const paidRoutes = computed(() => task.value?.paid_retry_routes ?? [])
const showCheap = ref(false), cheapRoute = ref<{ agent: 'claude' | 'codex'; model: string } | null>(null), cheapEdit = ref(false), cheapAck = ref(false)
const showPaid = ref(false), paidModel = ref(''), paidTarget = ref(''), paidAck = ref(false)
const paidModels = computed(() => [...new Set(paidRoutes.value.map(r => r.model))])
const paidTargets = computed(() => [...new Set(paidRoutes.value.map(r => r.agent_target))])
const cheapLabel = (r: { agent: string; model: string }) => `${agentLabel(r.agent)} · ${r.model}`
function closePanels() { showFree.value = false; showCheap.value = false; showPaid.value = false }
const freeModels = computed(() => [...new Set(freeRoutes.value.map(r => r.model))])
const freeTargets = computed(() => [...new Set(freeRoutes.value.map(r => r.agent_target))])
async function acceptAnyway() {
  if (busy.value || !acceptable.value || !task.value) return
  const reason = window.prompt(`The agent reported "${props.card.title}" unfinished:\n\n${(task.value.incomplete_reason || '').slice(0, 300)}\n\nAccept it anyway? Its report and your reason are recorded as the handoff, the run stays failed in the history, and dependent stories are released. Why is this acceptable?`, '')
  if (!reason || reason.trim().length < 10) return
  busy.value = true; error.value = ''
  try {
    const base = `/api/projects/${props.card.project!.id}`
    const fresh = await getJson<Project>(base)
    const t = fresh.tasks.find(x => x.card_id === props.card.id && x.role === 'story')
    if (t?.column !== 'failed' || t.run_id !== props.card.last_run?.id) throw new Error('The task changed. Refresh before accepting it.')
    await postJson(`${base}/stories/${props.card.id}/accept-despite-report`, { revision: fresh.revision, run_id: t.run_id, reason: reason.trim() })
    notice.value = 'Accepted. Its report and your reason are recorded as the handoff, and the stories that wait on it are released.'
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
let generation = 0
watch(() => [props.card.id, props.card.project?.id, props.card.column, props.card.last_run?.id], async () => {
  const mine = ++generation
  project.value = null; error.value = ''; notice.value = ''; timeoutAck.value = false; closePanels()
  if (!visible.value) return
  try {
    const p = await getJson<Project>(`/api/projects/${props.card.project!.id}`)
    if (mine === generation) project.value = p
  } catch (e) { if (mine === generation) error.value = e instanceof Error ? e.message : String(e) }
}, { immediate: true })

function chooseFree() {
  closePanels()
  freeModel.value = freeModels.value[0] ?? ''
  const preferred = props.card.agent_target || (freeTargets.value.find(t => /developer$/.test(t)) || freeTargets.value[0] || '')
  freeTarget.value = freeTargets.value.includes(preferred) ? preferred : freeTargets.value[0] ?? ''
  showFree.value = true
}

function chooseCheap(route: { agent: 'claude' | 'codex'; model: string }) {
  closePanels(); cheapRoute.value = route; cheapEdit.value = false; cheapAck.value = false; showCheap.value = true
}
function choosePaid() {
  closePanels(); paidModel.value = paidModels.value[0] ?? ''
  const preferred = props.card.agent_target || (paidTargets.value.find(t => /developer$/.test(t)) || paidTargets.value[0] || '')
  paidTarget.value = paidTargets.value.includes(preferred) ? preferred : paidTargets.value[0] ?? ''
  paidAck.value = false; showPaid.value = true
}
async function current(base: string) {
  const p = await getJson<Project>(base)
  const t = p.tasks.find(x => x.card_id === props.card.id && x.role === 'story')
  if (!['active', 'complete'].includes(p.state) || !t || !['failed', 'review', 'done'].includes(t.column) || t.run_id !== props.card.last_run?.id ||
      (['review', 'done'].includes(t.column) && t.run_stage !== 'succeeded')) throw new Error('The task changed. Refresh before rerunning it.')
  return { p, t }
}
async function goCheap() {
  if (busy.value || !ready.value || !cheapRoute.value) return
  busy.value = true; error.value = ''
  try {
    const base = `/api/projects/${props.card.project!.id}`
    const { p, t } = await current(base)
    if (!t.low_cost_routes?.some(r => r.agent === cheapRoute.value!.agent && r.model === cheapRoute.value!.model)) throw new Error('This subscription route is no longer available. Refresh before choosing it.')
    await postJson(`${base}/stories/${props.card.id}/low-cost-retry`, { revision: p.revision, run_id: t.run_id, agent: cheapRoute.value.agent, edit_mode: cheapEdit.value, acknowledge: cheapEdit.value && cheapAck.value, ...ack() })
    closePanels(); notice.value = `Retry queued on ${cheapLabel(cheapRoute.value)} (your subscription). No paid API or Google BYOK route was added.`
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
async function goPaid() {
  if (busy.value || !ready.value || !paidModel.value || !paidTarget.value || !paidAck.value) return
  busy.value = true; error.value = ''
  try {
    const base = `/api/projects/${props.card.project!.id}`
    const { p, t } = await current(base)
    if (!t.paid_retry_routes?.some(r => r.model === paidModel.value && r.agent_target === paidTarget.value)) throw new Error('This paid route is no longer configured. Refresh before choosing it.')
    await postJson(`${base}/stories/${props.card.id}/pay-retry`, { revision: p.revision, run_id: t.run_id, model: paidModel.value, agent_target: paidTarget.value, acknowledge: true, ...ack() })
    closePanels(); notice.value = 'Paid retry queued for this task only. Price checks and budget caps still apply when it starts.'
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

async function goFree() {
  if (busy.value || !rerunReady.value) return
  busy.value = true; error.value = ''
  try {
    const base = `/api/projects/${props.card.project!.id}`
    const p = await getJson<Project>(base)
    const current = p.tasks.find(t => t.card_id === props.card.id && t.role === 'story')
    if (!['active', 'complete'].includes(p.state) || !current || !['failed', 'review', 'done'].includes(current.column) || current.run_id !== props.card.last_run?.id ||
        (['review', 'done'].includes(current.column) && current.run_stage !== 'succeeded'))
      throw new Error('The task changed. Refresh before rerunning it.')
    if (!current.free_retry_routes?.some(r => r.model === freeModel.value && r.agent_target === freeTarget.value))
      throw new Error('This free route is no longer configured. Refresh before selecting a model.')
    await postJson(`${base}/stories/${props.card.id}/go-free`, { revision: p.revision, run_id: current.run_id, model: freeModel.value, agent_target: freeTarget.value, ...ack() })
    showFree.value = false
    notice.value = 'Free-model retry queued for this task. Google BYOK and paid-model fallback are excluded.'
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

async function retry(route?: ProjectNode['routes'][number]) {
  if (busy.value || !ready.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const base = `/api/projects/${props.card.project!.id}`
    const p = await getJson<Project>(base)
    const current = p.tasks.find(t => t.card_id === props.card.id && t.role === 'story')
    if (p.state !== 'active' || current?.column !== 'failed' || current.run_id !== props.card.last_run?.id)
      throw new Error('The task changed. Refresh before rerunning it.')
    if (route && !current.retry_routes?.some(r => r.agent === route.agent && r.model === route.model))
      throw new Error('This route is no longer approved. Review the project.')
    await postJson(`${base}/stories/${props.card.id}/retry`, { revision: p.revision, ...(route ? { route } : {}), ...ack() })
    notice.value = 'Rerun queued. It will start when its dependencies and execution slot are ready.'
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>

<template>
  <section v-if="visible" class="task-retry" :aria-label="card.column === 'failed' ? 'Rerun failed task' : 'Rerun completed task'">
    <RouteRecoveryNotice v-if="card.column === 'failed'" :info="project?.route_reliability" :agent="card.agent" :model="card.model" failed />
    <div v-if="card.column === 'failed' && timedOut" class="timeout-ack notice-warn" role="group" aria-label="Timed-out attempt">
      <p>The last attempt timed out. RCD cannot tell what it changed or whether the provider is still working on it, so a new attempt needs your confirmation.</p>
      <label class="check"><input v-model="timeoutAck" type="checkbox" :disabled="busy" />I reviewed the partial work and want a new attempt.</label>
    </div>
    <div class="retry-actions">
      <button type="button" class="btn primary" :disabled="busy || !rerunReady" @click="retry()"><AppIcon name="run" size="sm" />{{ busy ? 'Queueing…' : card.column === 'failed' ? 'Rerun task' : 'Rerun same story' }}</button>
      <template v-if="card.column === 'failed'">
      <button v-for="route in alternatives" :key="`${route.agent}:${route.model}`" type="button" class="btn" :disabled="busy || !ready" @click="retry(route)">Rerun with {{ agentLabel(route.agent) }} · {{ route.model || 'Agent default' }}</button>
      <button v-if="card.agent === 'openclaw' && freeRoutes.length" type="button" class="btn" :disabled="busy || !ready" @click="chooseFree">Try another free model</button>
      <button v-for="r in lowCost" :key="`${r.agent}:${r.model}`" type="button" class="btn" :disabled="busy || !ready" @click="chooseCheap(r)">Use {{ cheapLabel(r) }} (subscription)</button>
      <button v-if="paidRoutes.length" type="button" class="btn" :disabled="busy || !ready" @click="choosePaid">Pay for this task…</button>
      <button v-if="limited && (card.agent === 'claude' || card.agent === 'codex')" type="button" class="btn" :disabled="busy || !ready || !freeRoutes.length" @click="chooseFree">Go Free!</button>
      <button v-if="acceptable" type="button" class="btn" :disabled="busy" data-testid="accept-anyway" @click="acceptAnyway">Accept anyway…</button>
      </template>
    </div>
    <div v-if="showFree" class="free-choice" aria-label="Choose free retry">
      <p><strong>Continue this task with OpenClaw</strong></p>
      <label>Free model<select v-model="freeModel" :disabled="busy"><option v-for="model in freeModels" :key="model" :value="model">{{ model }}</option></select></label>
      <label>OpenClaw agent<select v-model="freeTarget" :disabled="busy"><option v-for="target in freeTargets" :key="target" :value="target">{{ target }}</option></select></label>
      <p class="muted small">Approves this model for this task only. No paid-model or Google BYOK fallback. If the free model is unavailable, the task stops for review.</p>
      <div class="retry-actions"><button type="button" class="btn primary" :disabled="busy || !ready || !freeModel || !freeTarget" @click="goFree">{{ busy ? 'Queueing…' : 'Start free retry' }}</button><button type="button" class="btn" :disabled="busy" @click="showFree = false">Cancel</button></div>
    </div>
    <div v-if="showCheap && cheapRoute" class="free-choice" aria-label="Retry on a subscription model">
      <p><strong>Retry on {{ cheapLabel(cheapRoute) }}</strong></p>
      <p class="muted small">Uses your {{ agentLabel(cheapRoute.agent) }} membership and its shared quota; provider settings may enable overage charges. Same scope, workspace and dependencies; earlier work stays unverified.</p>
      <label v-if="card.mode === 'read'" class="check"><input v-model="cheapEdit" type="checkbox" :disabled="busy" />Let it edit files and commit on this project’s branch. This switches the task from read-only to edit mode.</label>
      <label v-if="cheapEdit" class="check"><input v-model="cheapAck" type="checkbox" :disabled="busy" />I approve the switch from read-only review to workspace execution.</label>
      <div class="retry-actions"><button type="button" class="btn primary" :disabled="busy || !ready || (cheapEdit && !cheapAck)" @click="goCheap">{{ busy ? 'Queueing…' : 'Start retry' }}</button><button type="button" class="btn" :disabled="busy" @click="showCheap = false">Cancel</button></div>
    </div>
    <div v-if="showPaid" class="free-choice" aria-label="Pay for this task">
      <p><strong>Retry this task on a paid model</strong></p>
      <label>Model<select v-model="paidModel" :disabled="busy"><option v-for="model in paidModels" :key="model" :value="model">{{ model }}</option></select></label>
      <label>OpenClaw agent<select v-model="paidTarget" :disabled="busy"><option v-for="target in paidTargets" :key="target" :value="target">{{ target }}</option></select></label>
      <p class="muted small">Uses API billing for this task only. The price check, budget caps and free-only setting still apply when it starts, and it can stop there with the reason. No Google BYOK route is added.</p>
      <label class="check"><input v-model="paidAck" type="checkbox" :disabled="busy" />I approve API billing for this task only.</label>
      <div class="retry-actions"><button type="button" class="btn primary" :disabled="busy || !ready || !paidModel || !paidTarget || !paidAck" @click="goPaid">{{ busy ? 'Queueing…' : 'Start paid retry' }}</button><button type="button" class="btn" :disabled="busy" @click="showPaid = false">Cancel</button></div>
    </div>
    <p class="muted small">Keeps this task’s scope, workspace and dependency order. Earlier runs remain in history. If a free model is throttled, <strong>Rerun task</strong> again later also works.</p>
    <p v-if="limited" class="muted small">The same agent may remain limited until its quota resets. Use an approved alternative above when available.</p>
    <p v-if="limited && (card.agent === 'claude' || card.agent === 'codex') && project && !freeRoutes.length" class="muted small">Go Free needs an installed OpenClaw agent with a configured OpenRouter :free model.</p>
    <p v-if="acceptable" class="muted small"><strong>Accept anyway</strong> is for a run that finished and reported unfinished work you are content to live with. You give a reason; the report stays on record.</p>
    <p v-if="project?.state === 'paused'" class="muted small">Resume project dispatch before rerunning this task.</p>
    <p v-if="error" class="error-text" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.task-retry { display:grid; gap:var(--gap-sm); padding:var(--gap); border:1px solid var(--panel-border); border-radius:var(--radius); background:var(--panel-raised); }
.task-retry p { margin:0; overflow-wrap:anywhere; }
.timeout-ack { display:grid; gap:var(--gap-sm); }
.retry-actions { display:flex; flex-wrap:wrap; gap:var(--gap-sm); }
.retry-actions .btn { display:inline-flex; gap:var(--gap-xs); align-items:center; white-space:normal; overflow-wrap:anywhere; max-width:100%; }
.free-choice { display:grid; gap:var(--gap-sm); border-top:1px solid var(--panel-border); padding-top:var(--gap); }
.free-choice label { display:grid; gap:var(--gap-xs); min-width:0; }
.free-choice select { width:100%; min-width:0; }
</style>
