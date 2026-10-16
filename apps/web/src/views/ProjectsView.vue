<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ProjectConsultant from '@/components/ProjectConsultant.vue'
import AppIcon from '@/components/AppIcon.vue'
import AppSelect from '@/components/AppSelect.vue'
import ModalShell from '@/components/ModalShell.vue'
import PlanningBiasSlider from '@/components/PlanningBiasSlider.vue'
import StandardsLine from '@/components/StandardsLine.vue'
import ProjectGitAccess from '@/components/ProjectGitAccess.vue'
import ProjectSchedule from '@/components/ProjectSchedule.vue'
import RouteAdvice from '@/components/RouteAdvice.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import { useGuideAction } from '@/composables/useGuideAction'
import { getJson, postJson, patchJson } from '@/lib/api'
import type { ReportContent, Reports } from '@/lib/operations'
import { actionableFindings } from '@/lib/findings'
import { firstInstalled } from '@/lib/agentMix'
import { type Project, type ProjectDocument, type ProjectSummary, type ProjectNode, type ProjectTask, emptyProject, newNode, arrange, label, planningBiasLabel } from '@/lib/projects'
import { directoryName, directoryDetail } from '@/lib/selectLabels'
import type { Profile } from '@/lib/profile'
import { agentLabel } from '@/lib/cards'
const route = useRoute(), router = useRouter()
const { data: listing, error: listError, refresh: refreshList } = usePolledJson<{ projects: ProjectSummary[] }>('/api/projects', 5000, { match: e => e.type !== 'run_event' })
const { data: workdirs } = usePolledJson<{ workdirs: { path: string; branch: string | null }[] }>('/api/workdirs', 60000)
const { data: agents } = usePolledJson<{ agents: { id: string; name: string; available?: boolean; default_model: string | null; subagents?: { agents?: { id: string; name: string }[] } }[] }>('/api/agents', 60000)
const { data: profile } = usePolledJson<Profile>('/api/profile', 10000)
const { data: roleStatus } = usePolledJson<{delegator:string|null; revision:string}>('/api/roles', 10000)
const newApiPlanning = ref(false)
const newCoordination = ref(false), submitting = ref(false)
const readyDelivery = computed(() => project.value?.deliveries?.find(d => d.kind === 'ready' && d.revision === project.value?.revision))
const planningSteps = ['coordinate', 'plan', 'return']
const currentStep = computed(() => planningSteps.indexOf(project.value?.pipeline?.step || ''))
const selectedId = computed(() => Number(route.query.project) || null)
const detailPath = computed(() => selectedId.value ? `/api/projects/${selectedId.value}` : '/api/projects')
const { data: remote, error: detailError, refresh: refreshDetail } = usePolledJson<Project | { projects: ProjectSummary[] }>(detailPath, 3000, { match: () => true })
const project = ref<Project | null>(null), draft = ref<ProjectDocument>(emptyProject()), baseline = ref(''), selectedNode = ref('')
const error = ref(''), busy = ref(false), tab = ref<'map' | 'memory' | 'work'>(route.query.view === 'work' ? 'work' : 'map'), zoom = ref(1)
// Parallel build is a switch chosen when the project is built. Off (the default) builds one story at a time in dependency order.
const parallelDraft = computed({ get: () => draft.value.dispatch_mode === 'parallel', set: (on: boolean) => { draft.value.dispatch_mode = on ? 'parallel' : 'sequential' } })
const parallelNew = computed({ get: () => newDraft.value.dispatch_mode === 'parallel', set: (on: boolean) => { newDraft.value.dispatch_mode = on ? 'parallel' : 'sequential' } })
const touchesText = (n: { touches?: string[] }) => (n.touches ?? []).join('\n')
const setTouches = (n: { touches?: string[] }, text: string) => { n.touches = text.split('\n').map(x => x.trim()).filter(Boolean).slice(0, 20) }
const nodeTitles = computed(() => Object.fromEntries(draft.value.nodes.map(n => [n.key, n.title])))
const newDialog = ref(false), newDraft = ref(emptyProject()), confirmation = ref<'plan' | 'submit' | null>(null)
const coordination = ref(false), paidPlanner = ref(false), paidWork = ref(false), note = ref('')
const accepting = ref<ProjectTask | null>(null), handoff = ref('')
const artifact = ref<{ files: string[]; diff: string; head: string | null; output?: { path: string; markdown: string; sha256: string } | null } | null>(null), selectedFiles = ref<string[]>([])
const outputReviewed = ref(false), continuing = ref<ProjectTask | null>(null), outputApproved = ref(false)
const integrationReview = ref(false)
const approvalDialog = ref(false), automaticHandoffs = ref(true), handoffsAcknowledged = ref(false)
const retierDialog = ref(false), retierAcknowledged = ref(false)
const repairing = ref<ProjectTask | null>(null), repairAcknowledged = ref(false)
const conflict = ref(false), mapScroll = ref<HTMLElement | null>(null)
function fitMap() { if (mapScroll.value) zoom.value = Math.max(.25, Math.min(1,(mapScroll.value.clientWidth-20)/width.value)) }
const dirty = computed(() => !!project.value && JSON.stringify(draft.value) !== baseline.value)
const locked = computed(() => ['planning', 'dispatching', 'active', 'paused', 'complete', 'closed'].includes(project.value?.state || ''))
const node = computed(() => draft.value.nodes.find(n => n.key === selectedNode.value))
const stories = computed(() => draft.value.nodes.filter(n => n.kind === 'story'))
const nodeTasks = computed(() => project.value?.tasks.filter(t => t.role === 'story') ?? [])
const width = computed(() => Math.max(960, ...draft.value.nodes.map(n => n.x + 310)))
const height = computed(() => Math.max(520, ...draft.value.nodes.map(n => n.y + 170)))
const needsPaidWork = computed(() => stories.value.some(n => ['hermes', 'openclaw'].includes(n.assignee) || n.routes.some(r => ['hermes','openclaw'].includes(r.agent))))
const phases = computed(() => draft.value.nodes.filter(n => n.kind === 'phase'))
const targets = computed(() => agents.value?.agents.find(a => a.id === 'openclaw')?.subagents?.agents ?? [])
const retierableTasks = computed(() => nodeTasks.value.filter(t => ['queued','backlog'].includes(t.column) && (
  (t.agent === 'claude' && t.model !== 'claude-haiku-5-5') || (t.agent === 'codex' && t.model !== 'gpt-6-luna')
)))
const repairableTasks = computed(() => nodeTasks.value.filter(t => ['review', 'failed'].includes(t.column) && t.mode === 'read' && !!t.incomplete_reason))
// Consume a review deep link once. Polling must never reopen a dismissed dialog.
let openedReview = ''
watch(() => [route.fullPath, project.value] as const, () => {
  if (route.query.action !== 'review') { openedReview = ''; return }
  if (!project.value || project.value.id !== selectedId.value) return
  const task = project.value.tasks.find(t => t.card_id === Number(route.query.story) && t.role === 'story')
  if (!task || openedReview === route.fullPath) return
  openedReview = route.fullPath
  tab.value = 'work'
  if (task.output_approval) showContinue(task)
  else if (task.column === 'review' && task.run_stage === 'succeeded') void showAccept(task)
}, { flush: 'post' })
watch(remote, value => {
  if (!value || !('document' in value)) return
  if (project.value?.id === value.id && dirty.value) {
    conflict.value = project.value.revision !== value.revision
    project.value = { ...value, revision: project.value.revision }; return
  }
  apply(value)
})
watch(selectedId, () => { project.value = null; draft.value = emptyProject(); baseline.value = ''; conflict.value = false; error.value = '' })
function apply(value: Project) {
  project.value = value; draft.value = { ...emptyProject(), ...structuredClone(value.document) }
  // Newly generated maps have default positions; arrange before the operator saves/reviews.
  if (draft.value.nodes.length > 1 && draft.value.nodes.every(n => n.x === 0 && n.y === 0)) draft.value.nodes = arrange(draft.value.nodes)
  baseline.value = JSON.stringify(draft.value); conflict.value = false
  if (!draft.value.nodes.some(n => n.key === selectedNode.value)) selectedNode.value = draft.value.nodes[0]?.key ?? ''
}
function discardEdits() { if (window.confirm("Discard your local edits and reload the newer revision?") && remote.value && "document" in remote.value) apply(remote.value) }
function select(id: number) {
  if (id === selectedId.value && project.value) { refreshDetail(); return }
  if (dirty.value && !window.confirm('Discard unsaved project edits?')) return
  void router.push({ path: '/projects', query: { project: String(id) } })
}
function startNew() {
  delegator.value = roleStatus.value ? {...roleStatus.value} : null
  newDraft.value = { ...emptyProject(profile.value?.preferences.working_dir || workdirs.value?.workdirs[0]?.path || ''), planning_bias: profile.value?.preferences.planning_bias ?? 50, planner_agent: profile.value?.preferences.ai_agent || 'hermes', planner_model: profile.value?.preferences.ai_model || 'openrouter/free' }
  newCoordination.value = false; newApiPlanning.value = false; newDialog.value = true
}
function reviewConsultant(value: {title:string;brief:string;working_dir:string}) {
  if (roleStatus.value?.delegator !== 'hermes') { error.value='Assign Hermes as Delegator in Settings → Agent roles before submitting the consultant brief.'; return }
  startNew()
  newDraft.value = {...newDraft.value,...value}
}
function consultantStarted(id:number) { const {consultant:_old,...rest}=route.query; void router.replace({query:id?{...rest,consultant:String(id)}:rest}) }
useGuideAction('new', startNew)
// A report's "Plan project" link opens the New-project dialog prefilled from its actionable findings. Nothing is submitted here.
watch(() => route.query.from_report, async id => {
  if (typeof id !== 'string' || !/^[a-f0-9]{64}$/.test(id)) return
  try {
    const report = await getJson<ReportContent | Reports>(`/api/reports/${id}`)
    if (!('content' in report)) return
    const title = report.title || report.name
    const ids = actionableFindings(report.content).map(f => f.id)
    newDraft.value = { ...emptyProject(profile.value?.preferences.working_dir || workdirs.value?.workdirs[0]?.path || ''), title: `Plan Ops findings: ${title}`.slice(0, 200), brief: `Source report ${id} (${title}). Plan the work to resolve these actionable findings: ${ids.join(', ') || 'none'}. Review the report evidence before approving coordination.`, planning_bias: profile.value?.preferences.planning_bias ?? 50, planner_agent: profile.value?.preferences.ai_agent || 'hermes', planner_model: profile.value?.preferences.ai_model || 'openrouter/free' }
    newCoordination.value = false; newApiPlanning.value = false; newDialog.value = true
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    const { from_report: _consumed, ...rest } = route.query
    void router.replace({ path: '/projects', query: rest })
  }
}, { immediate: true })
async function perform(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await fn(); refreshList() } catch (e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
async function create(send = true) { await perform(async () => {
  if (!newDraft.value.title.trim() || !newDraft.value.brief.trim()) throw new Error('Add a project name and brief.')
  if (send && !newCoordination.value) throw new Error('Review and approve Delegator coordination before submitting.')
  submitting.value = send
  try {
    const p = await postJson<Project>('/api/projects', newDraft.value); newDialog.value = false
    await router.push({ path: '/projects', query: { project: String(p.id) } }); apply(p)
    if (send) apply(await postJson<Project>(`/api/projects/${p.id}/plan`, { revision: p.revision, approve_coordination: true, delegator_revision: delegator.value?.revision, ...(newApiPlanning.value ? {approve_api_planning:true} : {}) }))
    refreshDetail()
  } finally { submitting.value = false }
}) }
async function save() { await perform(async () => { if (!project.value) return
  apply(await patchJson<Project>(`/api/projects/${project.value.id}`, { revision: project.value.revision, document: draft.value })); refreshDetail()
}) }
async function resumePlan() { await perform(async () => { if (!project.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/resume-plan`, { revision: project.value.revision })); refreshDetail()
}) }
function add(kind: 'phase' | 'story') {
  const n = newNode(kind, draft.value.nodes.length, node.value?.kind === 'phase' ? node.value.key : null, draft.value.planning_bias, targets.value.find(t => t.id === 'mm-developer')?.id || '')
  if (kind === 'story') {
    // A new story starts on an agent that is installed, whichever mix this machine has.
    const order = draft.value.planning_bias < 50 ? ['openclaw', 'codex', 'claude', 'grok', 'hermes'] : ['codex', 'claude', 'grok', 'openclaw', 'hermes']
    const chosen = firstInstalled(id => agents.value?.agents.find(a => a.id === id)?.available, order)
    if (chosen && chosen !== n.assignee) { n.assignee = chosen as ProjectNode['assignee']; n.model = ''; n.agent_target = chosen === 'openclaw' ? n.agent_target || (targets.value.find(t => t.id === 'mm-developer')?.id || '') : '' }
  }
  draft.value.nodes.push(n); selectedNode.value = n.key
}
function removeNode() {
  if (!node.value) return
  const key = node.value.key
  draft.value.nodes = draft.value.nodes.filter(n => n.key !== key).map(n => ({ ...n, parent: n.parent === key ? null : n.parent, depends_on: n.depends_on.filter(d => d !== key) }))
  selectedNode.value = draft.value.nodes[0]?.key || ''
}
function depends(key: string, checked: boolean) {
  if (!node.value) return
  node.value.depends_on = checked ? [...node.value.depends_on, key] : node.value.depends_on.filter(d => d !== key)
}
function addRoute() { if (node.value) node.value.routes.push({ agent: node.value.assignee === 'claude' ? 'codex' : 'claude', model: node.value.assignee === 'claude' ? 'gpt-6.1-sol' : 'claude-sonnet-5-5' }) }
function modelChoices(agent: string) {
  if (agent === 'claude') return ['claude-haiku-5-5','claude-sonnet-5-5','claude-opus-5-5']
  if (agent === 'codex') return ['gpt-6-luna','gpt-5.6-terra','gpt-6.1-sol','gpt-5.6-sol','gpt-6-astra']
  if (agent === 'grok') return ['grok-4.6','grok-4.5','grok-build-0.1']
  return ['thinkingmachines/inkling:free','google/gemma-4-31b-it:free','google/gemini-2.5-flash'].map(m => agent === 'openclaw' ? 'openrouter/'+m : m)
}
const closable = computed(() => ['active', 'paused', 'review', 'draft', 'planning_failed', 'dispatch_failed'].includes(project.value?.state || ''))
async function closeProject() {
  if (!project.value) return
  const reason = window.prompt('Close this project without finishing it? No new story will start, its failed tasks can be removed, and the whole ledger is kept. Why are you closing it?', '')
  if (!reason || reason.trim().length < 3) return
  await perform(async () => { apply(await postJson<Project>(`/api/projects/${project.value!.id}/close`, { revision: project.value!.revision, reason: reason.trim() })); refreshDetail() })
}
async function toggleModelLock() { await perform(async () => { if (!project.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/model-lock`, { revision: project.value.revision, enabled: !project.value.model_lock })); refreshDetail()
}) }
async function dispatchControl(action: 'pause' | 'resume') { await perform(async () => { if (!project.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/${action}`, { revision: project.value.revision })); refreshDetail()
}) }
function openRetier() { retierAcknowledged.value = false; retierDialog.value = true }
async function retierProject() { await perform(async () => { if (!project.value || !retierAcknowledged.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/retier`, {
    revision: project.value.revision, claude_model: 'claude-haiku-5-5', codex_model: 'gpt-6-luna', acknowledge: true,
  })); retierDialog.value = false; refreshDetail()
}) }
function showRepair(task: ProjectTask) { repairAcknowledged.value = false; repairing.value = task }
async function repairExecution() { await perform(async () => { if (!project.value || !repairing.value || !repairAcknowledged.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/stories/${repairing.value.card_id}/repair-execution`, {
    revision: project.value.revision, acknowledge: true,
  })); repairing.value = null; refreshDetail()
}) }
const delegator = ref<{delegator:string|null; revision:string}|null>(null)
async function openConfirm(action: 'plan' | 'submit') { await perform(async()=>{ delegator.value = await getJson('/api/roles'); confirmation.value = action; coordination.value = paidPlanner.value = paidWork.value = false }) }
async function confirmAction() { await perform(async () => {
  if (!project.value || !confirmation.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/${confirmation.value}`, {
    revision: project.value.revision, approve_coordination: coordination.value, delegator_revision: delegator.value?.revision, approve_api_planning: paidPlanner.value, approve_api_work: paidWork.value,
  })); confirmation.value = null; refreshDetail()
}) }
async function addNote() { await perform(async () => { if (!project.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/memory`, { text: note.value })); note.value = ''; refreshDetail()
}) }
async function showAccept(task: ProjectTask, integration = false) {
  integrationReview.value = integration
  accepting.value = task; artifact.value = null; selectedFiles.value = []; outputReviewed.value = false
  handoff.value = project.value?.memory.find(m => m.kind === 'proposal' && m.run_id === task.run_id)?.text || ''
  await perform(async () => { artifact.value = await getJson(`/api/projects/${project.value!.id}/stories/${task.card_id}/artifact`) })
}
async function accept() { await perform(async () => { if (!project.value || !accepting.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/stories/${accepting.value.card_id}/${integrationReview.value ? 'integration' : 'accept'}`, { revision: project.value.revision, run_id: accepting.value.run_id, summary: handoff.value, snapshot: selectedFiles.value.length > 0, files: selectedFiles.value, ...(artifact.value?.output && outputReviewed.value ? {output_sha256:artifact.value.output.sha256} : {}) }))
  accepting.value = null; refreshDetail()
}) }
function showContinue(task: ProjectTask) { continuing.value = task; outputApproved.value = false; error.value = '' }
async function continueOutput() { await perform(async () => {
  if (!project.value || !continuing.value?.output_approval || !outputApproved.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/stories/${continuing.value.card_id}/continue-output`, {
    revision:project.value.revision, run_id:continuing.value.output_approval.run_id, approve_output:true,
  })); continuing.value = null; refreshDetail()
}) }
async function retry(task: ProjectTask, selectedRoute?: ProjectNode['routes'][number]) { await perform(async () => { if (!project.value) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/stories/${task.card_id}/retry`, { revision: project.value.revision, ...(selectedRoute ? {route:selectedRoute} : {}) })); refreshDetail()
}) }
async function exportContext() { await perform(async () => {
  if (!project.value) return
  const response = await fetch(`/api/projects/${project.value.id}/context`, { cache: 'no-store' })
  if (!response.ok) throw new Error('Shared context could not be exported.')
  const url = URL.createObjectURL(new Blob([await response.text()], { type: 'text/markdown' }))
  const a = document.createElement('a'); a.href = url; a.download = `mcd-project-${project.value.id}-context.md`; a.click(); URL.revokeObjectURL(url)
}) }
function point(key: string) { return draft.value.nodes.find(n => n.key === key) }
function edge(from: ProjectNode, to: ProjectNode) {
  const x1 = from.x + 250, x2 = to.x, y1 = from.y + 55, y2 = to.y + 55
  return `M${x1},${y1} C${x1 + 70},${y1} ${x2 - 70},${y2} ${x2},${y2}`
}
let drag: { key: string; x: number; y: number; px: number; py: number } | null = null
function dragStart(event: PointerEvent, n: ProjectNode) {
  selectedNode.value = n.key
  if (locked.value || event.button !== 0) return
  drag = { key: n.key, x: n.x, y: n.y, px: event.clientX, py: event.clientY }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function dragMove(event: PointerEvent) {
  if (!drag) return
  const n = point(drag.key); if (!n) return
  n.x = Math.max(0, Math.min(10000, drag.x + (event.clientX - drag.px) / zoom.value))
  n.y = Math.max(0, Math.min(10000, drag.y + (event.clientY - drag.py) / zoom.value))
}
onBeforeUnmount(() => { drag = null })
const doneCount = computed(() => nodeTasks.value.filter(t => t.column === 'done').length)
function taskStatus(task: ProjectTask): string {
  if (task.output_approval || task.run_stage === 'awaiting_approval') return 'approval'
  if (task.column === 'backlog' && human(task)) return 'human'
  if (task.column === 'queued' && task.blocked_by?.length) return 'blocked'
  return task.column
}
function aggregateStatus(states: string[]): string {
  if (!states.length) return 'draft'
  if (states.every(s => s === 'done')) return 'done'
  return ['failed','running','approval','review','human','queued','blocked','backlog'].find(s => states.includes(s)) || 'draft'
}
function status(key: string): string {
  const n = point(key)
  if (n?.kind !== 'phase') return nodeTasks.value.find(t => t.node_key === key) ? taskStatus(nodeTasks.value.find(t => t.node_key === key)!) : 'draft'
  const keys = new Set([key])
  for (let i = 0; i < draft.value.nodes.length; i++) for (const child of draft.value.nodes) if (child.parent && keys.has(child.parent)) keys.add(child.key)
  return aggregateStatus(nodeTasks.value.filter(t => keys.has(t.node_key)).map(taskStatus))
}
function statusLabel(value: string): string { return ({running:'Running',review:'Review',approval:'Needs approval',human:'Your decision',blocked:'Blocked',done:'Done',queued:'Queued',draft:'Not started'} as Record<string,string>)[value] || label(value) }
const projectStatus = computed(() => project.value?.state === 'paused' ? 'paused' : aggregateStatus(nodeTasks.value.map(taskStatus)))
function openHandoffApproval() { approvalDialog.value = true; automaticHandoffs.value = true; handoffsAcknowledged.value = false }
async function updateHandoffPolicy(mode: 'manual' | 'batch' | 'automatic') { await perform(async () => {
  if (!project.value?.handoff_approval?.manifest_hash || (mode !== 'manual' && !handoffsAcknowledged.value)) return
  apply(await postJson<Project>(`/api/projects/${project.value.id}/handoff-policy`, {
    revision:project.value.revision,manifest_hash:project.value.handoff_approval.manifest_hash,mode,approve:mode !== 'manual',
  })); approvalDialog.value = false; refreshDetail()
}) }
const selectedTask = computed(() => node.value ? nodeTasks.value.find(t => t.node_key === node.value!.key) : undefined)
function human(task: ProjectTask) { return draft.value.nodes.find(n => n.key === task.node_key)?.assignee === 'human' }
</script>

<template>
  <section aria-labelledby="projects-title">
    <div class="page-header"><div><h1 id="projects-title" class="page-title has-icon"><AppIcon name="tasks" size="lg" />Projects</h1><p class="muted">Plan together. Review the map. Share context through every handoff.</p></div><button class="btn primary" @click="startNew">+ New project</button></div>
    <p v-if="error || listError || detailError" class="notice-warn" role="alert">{{ error || listError || detailError }}</p>
    <div class="project-layout">
      <aside class="project-index card"><h2>Project library</h2><p v-if="!listing?.projects.length" class="muted">Start with a brief. Your assigned Delegator will coordinate a plan before any story is submitted.</p><button v-for="p in listing?.projects" :key="p.id" class="project-link" :class="[{ selected: p.id === selectedId },`status-${p.id === project?.id ? projectStatus : p.state}`]" @click="select(p.id)"><strong>{{ p.title }}</strong><small>{{ label(p.state) }} · revision {{ p.revision }}</small></button><p class="small muted">Set your story assignment preference when creating a project. API routes require approval.</p></aside>
      <div v-if="!project" class="card welcome"><span class="eyebrow">SHARED PROJECT WORKSPACE</span><h2>From a big idea to clear, connected stories</h2><p>Create a project brief, ask Hermes to coordinate your selected planner, then edit the mind map and review each assignment.</p><ol><li>Define the goal and working directory.</li><li>Review phases, scope, definitions of done and dependencies.</li><li>Submit the exact revision. Hermes orders the stories.</li><li>Accept each handoff into shared memory before dependent stories start.</li></ol><button class="btn primary" @click="startNew">Create project brief</button><ProjectConsultant :preferences="profile?.preferences" :workdirs="workdirs?.workdirs || []" :available="!!agents?.agents.find(a=>a.id === (profile?.preferences.ai_agent || 'hermes'))?.available" :resume-id="Number(route.query.consultant) || undefined" @review="reviewConsultant" @started="consultantStarted" /></div>
      <div v-else class="project-main">
        <header class="card project-heading"><div><span class="eyebrow">PROJECT {{ project.id }} · REVISION {{ project.revision }}</span><h2>{{ draft.title }}</h2><span class="status-label">{{ label(project.state) }}</span><span v-if="dirty" class="dirty">Unsaved edits</span></div><div class="actions"><button v-if="closable" class="btn" :disabled="busy" @click="closeProject">Close project…</button><button v-if="!locked" class="btn" :disabled="busy || !dirty || conflict" @click="save">Save revision</button><button v-if="project.can_resume_plan" class="btn primary" :disabled="busy || dirty || conflict" @click="resumePlan">Resume saved plan</button><button v-if="!locked" class="btn" :disabled="busy || dirty || conflict" @click="openConfirm('plan')">{{ project.state === 'planning_failed' ? 'Retry planning' : 'Plan with Hermes' }}</button><button v-if="!locked && stories.length" class="btn primary" :disabled="busy || dirty || conflict" @click="openConfirm('submit')">Review & submit</button><button v-if="project.state === 'active' || project.state === 'paused'" class="btn" :disabled="busy" @click="dispatchControl(project.state === 'paused' ? 'resume' : 'pause')">{{ project.state === 'paused' ? 'Resume dispatch' : 'Pause dispatch' }}</button><button v-if="project.state === 'paused' && retierableTasks.length" class="btn" :disabled="busy" @click="openRetier">Use lower-cost models…</button><button class="btn" :disabled="busy || dirty" @click="exportContext">Export context</button></div></header>
        <section v-if="locked" class="card live-project" aria-label="Live project status">
          <div class="live-summary"><div class="project-bubble" :class="`status-${projectStatus}`"><span class="status-dot" aria-hidden="true" /><strong>{{ statusLabel(projectStatus) }}</strong><span>{{ doneCount }} / {{ nodeTasks.length }} stories done</span></div><span class="small muted">View only · refreshes every 3 seconds</span></div>
          <progress v-if="nodeTasks.length" :value="doneCount" :max="nodeTasks.length" aria-label="Completed project stories" />
          <p class="small muted">Viewing this map does not save edits or change the approved plan. Select a story to inspect its status.</p>
          <div v-if="project.state === 'active' || project.state === 'paused'" class="actions">
            <button v-if="project.handoff_approval?.mode !== 'automatic'" class="btn primary" :disabled="busy || !project.handoff_approval?.manifest_hash" @click="openHandoffApproval">Approve all except human-required tasks…</button>
            <template v-else><span class="small">Automatic agent handoffs enabled · human-required tasks excluded</span><button class="btn" :disabled="busy" @click="updateHandoffPolicy('manual')">Require individual reviews</button></template>
          </div>
          <p v-if="project.state === 'active' || project.state === 'paused'" class="small muted">Tasks needing human interaction, decisions or required answers still stop for your input and approval.</p>
        </section>
        <p v-if="conflict" class="notice-warn" role="alert">A newer revision arrived. Your local edits are preserved. <button class="btn" @click="discardEdits">Discard edits & reload</button></p>
        <p v-if="project.error" class="notice-warn" role="status">{{ project.error }}</p>
        <section v-if="project.state === 'paused' && repairableTasks.length" class="notice-warn" role="status"><strong>{{ repairableTasks.length }} read-only {{ repairableTasks.length === 1 ? 'story reports' : 'stories report' }} unfinished execution.</strong> Its result is retained as evidence and has not been accepted. <button class="btn" :disabled="busy" @click="showRepair(repairableTasks[0]!)">Repair first assignment…</button></section>
        <section v-if="project.state === 'planning' || project.state === 'review' || project.state === 'planning_failed'" class="pipeline card" aria-labelledby="planning-progress-title" role="status">
          <h2 id="planning-progress-title">{{ project.state === 'review' ? 'Your plan is ready to review' : project.state === 'planning_failed' ? 'Planning needs attention' : 'Submitted to ' + agentLabel(project.pipeline?.delegator?.agent || roleStatus?.delegator || 'hermes') }}</h2>
          <progress v-if="project.state === 'planning'" aria-label="Project planning in progress" />
          <ol class="planning-stages"><li v-for="(step,i) in planningSteps" :key="step" :class="{ current: currentStep === i, finished: project.state === 'review' || currentStep > i }">{{ ['Delegator coordinates', 'Subscription planner creates the map', 'Delegator reviews and returns the plan'][i] }}</li></ol>
          <RouterLink v-if="project.pipeline" :to="`/tasks?card=${project.pipeline.card_id}`">Open current planning task #{{ project.pipeline.card_id }}</RouterLink>
          <p v-if="profile?.discord_linked && profile.preferences.notify_plans">{{ readyDelivery?.status === 'sent' ? 'Discord notification delivered. Edit this map here or discuss revisions with Hermes.' : readyDelivery?.status === 'uncertain' ? 'Discord delivery could not be confirmed. Check your channel; RCD will not send a duplicate automatically.' : project.state === 'review' ? 'Your Discord notification is being prepared. You can edit the map now.' : 'You will receive a Discord message when the plan is ready. Then edit it in Projects or through Hermes.' }}</p>
          <p v-else>Review the plan here when ready. <RouterLink to="/profile#discord-profile">Link Discord in your profile</RouterLink> to receive plan notifications and edit through Hermes.</p>
          <p v-if="readyDelivery?.error" class="muted">{{ readyDelivery.error }}</p><p class="muted">Hermes asks whether you need a diagram before sending an image. Story execution requires a separate review.</p>
        </section>
        <nav class="tabs" aria-label="Project sections"><button v-for="t in (['map','memory','work'] as const)" :key="t" class="btn" :class="{ active: tab === t }" :aria-pressed="tab === t" @click="tab = t">{{ t === 'map' ? (locked ? 'Live map' : 'Planning map') : t === 'memory' ? 'Shared memory' : 'Stories & runs' }}</button></nav>
        <template v-if="tab === 'map'">
          <ProjectGitAccess v-if="project" :project-id="project.id" />
          <ProjectSchedule v-if="project?.schedule" :schedule="project.schedule" :titles="nodeTitles" :timing="project.timing" />
          <details class="card brief-panel" :open="!draft.nodes.length"><summary>Project brief & planner</summary><div class="form-grid"><label>Project name<input v-model="draft.title" class="input" :disabled="locked" maxlength="200" /></label><label>Working directory<AppSelect v-model="draft.working_dir" :disabled="locked" aria-label="Project working directory"><option v-for="w in workdirs?.workdirs" :key="w.path" :value="w.path" :data-description="directoryDetail(w.path,w.branch)">{{ directoryName(w.path) }}</option></AppSelect></label><StandardsLine v-if="project" class="full" :project-id="project.id" :revision="project.revision" /><label class="full">Goal and requirements<textarea v-model="draft.brief" class="input" rows="4" :disabled="locked" maxlength="20000" /></label><label class="full">Constraints and non-goals<textarea v-model="draft.constraints" class="input" rows="2" :disabled="locked" maxlength="10000" /></label><PlanningBiasSlider class="full" v-model="draft.planning_bias" :disabled="locked" mapped /><label>Planning route<AppSelect v-model="draft.planner_agent" :disabled="locked" aria-label="Planning route"><option value="auto" data-description="Prefer an installed subscription planner; use a reviewed free Delegator route when none is available">Automatic planner</option><option value="claude">Claude subscription</option><option value="codex">Codex subscription</option><option value="grok">Grok Build membership</option><option value="openclaw">OpenClaw / reviewed provider route</option><option value="hermes" data-description="Separate API planning approval required">Hermes / OpenRouter</option></AppSelect></label><label>Planner model<AppSelect v-model="draft.planner_model" editable :disabled="locked || draft.planner_agent === 'auto'" placeholder="Configured default" aria-label="Planner model"><option value="">Agent default</option><option v-for="m in modelChoices(draft.planner_agent)" :key="m" :value="m">{{ m }}</option></AppSelect></label><label class="check parallel-toggle"><input v-model="parallelDraft" type="checkbox" :disabled="locked" data-testid="parallel-draft" /><span><strong>Build in parallel</strong>: separate branches run at the same time and integration stories bring them together. Off builds one story at a time in dependency order.</span></label></div></details>
          <div class="status-legend small" aria-label="Map status colors"><span v-for="state in ['running','review','approval','queued','blocked','done','failed']" :key="state" :class="`status-${state}`"><i class="status-dot" aria-hidden="true" />{{ statusLabel(state) }}</span></div><div class="map-layout"><div class="card map-panel"><div class="map-toolbar"><div class="actions"><button class="btn" :disabled="locked" @click="add('phase')">+ Phase</button><button class="btn" :disabled="locked" @click="add('story')">+ Story</button><button class="btn" :disabled="locked" @click="draft.nodes = arrange(draft.nodes)">Arrange</button></div><div class="actions"><button class="btn" @click="fitMap">Fit map</button><button class="btn" aria-label="Zoom out" @click="zoom = Math.max(.5, zoom - .1)">−</button><span>{{ Math.round(zoom * 100) }}%</span><button class="btn" aria-label="Zoom in" @click="zoom = Math.min(1.5, zoom + .1)">+</button></div></div><p class="map-legend muted small">Solid lines connect phases. Dashed arrows show prerequisites. {{ locked ? 'Select a node to inspect its live status.' : 'Select a node to edit; drag to arrange.' }}</p><div class="map-scroll" ref="mapScroll" :aria-label="locked ? 'Live project mind map' : 'Editable project mind map'"><div :style="{ width: `${width * zoom}px`, height: `${height * zoom}px` }"><div class="map-canvas" :style="{ width: `${width}px`, height: `${height}px`, transform: `scale(${zoom})` }"><svg class="connections" :width="width" :height="height" aria-hidden="true"><defs><marker id="project-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10Z" /></marker></defs><template v-for="n in draft.nodes" :key="n.key"><path v-if="n.parent && point(n.parent)" :d="edge(point(n.parent)!,n)" class="parent-edge" /><path v-for="dep in n.depends_on.filter(d => point(d))" :key="dep" :d="edge(point(dep)!,n)" class="dependency-edge" marker-end="url(#project-arrow)" /></template></svg><button v-for="n in draft.nodes" :key="n.key" type="button" class="map-node" :class="[n.kind,`status-${status(n.key)}`,{ selected: selectedNode === n.key }]" :style="{ left: `${n.x}px`, top: `${n.y}px` }" :aria-label="`${n.kind}: ${n.title}`" :aria-pressed="selectedNode === n.key" @click="selectedNode = n.key" @pointerdown="dragStart($event,n)" @pointermove="dragMove" @pointerup="drag = null" @pointercancel="drag = null"><span class="node-top"><span>{{ n.kind === 'phase' ? 'PHASE' : 'STORY' }}</span><span v-if="status(n.key)">{{ statusLabel(status(n.key)) }}</span></span><strong>{{ n.title }}</strong><small v-if="n.kind === 'story'">{{ n.assignee === 'human' ? 'You' : agentLabel(n.assignee) }} · {{ n.model || 'Agent default' }}</small><small v-else>{{ draft.nodes.filter(c => c.parent === n.key).length }} connected nodes · {{ statusLabel(status(n.key)) }}</small></button><div v-if="!draft.nodes.length" class="map-empty"><AppIcon name="tasks" size="lg" /><h3>Your project map starts here</h3><p>Ask Hermes for a plan, or add phases and stories yourself.</p></div></div></div></div></div>
          <aside v-if="node" class="card node-editor"><p v-if="locked" class="node-live-status" :class="`status-${status(node.key)}`"><span class="status-dot" aria-hidden="true" />{{ statusLabel(status(node.key)) }} <RouterLink v-if="selectedTask" :to="`/tasks?card=${selectedTask.card_id}`">Open task</RouterLink></p><div class="editor-title"><h3>{{ node.kind === 'phase' ? 'Phase details' : 'Story details' }}</h3><button class="btn" :disabled="locked" @click="removeNode">Remove</button></div><fieldset :disabled="locked"><label>Title<input v-model="node.title" class="input" maxlength="200" /></label><label>Parent phase<AppSelect v-model="node.parent" aria-label="Parent phase"><option :value="''">Project root</option><option v-for="p in phases.filter(p => p.key !== node?.key)" :key="p.key" :value="p.key">{{ p.title }}</option></AppSelect></label><label>Instructions<textarea v-model="node.description" class="input" rows="4" maxlength="12000" /></label><template v-if="node.kind === 'story'"><label>Definition of done<textarea v-model="node.acceptance" class="input" rows="3" maxlength="6000" placeholder="What proves this story is complete?" /></label><label>Scope and boundaries<textarea v-model="node.scope" class="input" rows="2" maxlength="3000" placeholder="Files, interfaces, ownership and exclusions" /></label><template v-if="parallelDraft && node.kind === 'story'"><label>Files or folders it changes (one per line)<textarea class="input" rows="2" :disabled="locked" :value="touchesText(node)" placeholder="site/about/&#10;docs/**" data-testid="node-touches" @input="setTouches(node, ($event.target as HTMLTextAreaElement).value)" /></label><label class="check"><input v-model="node.integration" type="checkbox" :disabled="locked" data-testid="node-integration" />Integration story: brings together the branches of the stories it depends on</label></template><div class="form-grid"><label>Agent<AppSelect v-model="node.assignee" :disabled="locked" aria-label="Story agent"><option value="human">You · human task</option><option v-for="a in agents?.agents" :key="a.id" :value="a.id">{{ a.name }}{{ a.available ? '' : ' (not installed)' }}</option></AppSelect></label><label>Mode<AppSelect v-model="node.mode" :disabled="locked || node.assignee === 'human'" aria-label="Story mode"><option value="read">Read / plan</option><option value="edit">Edit workspace</option></AppSelect></label></div><label v-if="node.assignee !== 'human'">Model<AppSelect v-model="node.model" editable :disabled="locked" placeholder="Agent default" aria-label="Story model"><option value="">Agent default</option><option v-for="m in modelChoices(node.assignee)" :key="m" :value="m">{{ m }}</option></AppSelect></label><label v-if="node.assignee === 'openclaw'">OpenClaw target<AppSelect v-model="node.agent_target" :disabled="locked" aria-label="OpenClaw story target"><option value="">Default agent</option><option v-for="t in targets" :key="t.id" :value="t.id">{{ t.name || t.id }}</option></AppSelect></label><div v-if="node.assignee !== 'human'" class="choices"><span>Approved model routes on a reported limit</span><p class="small muted">Tried in order, once per story. Availability and quota windows differ by provider.</p><div v-for="(r,i) in node.routes" :key="i" class="route-choice"><AppSelect v-model="r.agent" :disabled="locked" :aria-label="`Handoff agent ${i+1}`"><option v-for="a in agents?.agents" :key="a.id" :value="a.id">{{ a.name }}</option></AppSelect><AppSelect v-model="r.model" editable :disabled="locked" :aria-label="`Handoff model ${i+1}`"><option v-for="m in modelChoices(r.agent)" :key="m" :value="m">{{ m }}</option></AppSelect><button type="button" class="btn" :disabled="locked" @click="node.routes.splice(i,1)">Remove route</button></div><button type="button" class="btn" :disabled="locked || node.routes.length >= 6" @click="addRoute">+ Model route</button></div><label>Assignment rationale<textarea v-model="node.rationale" class="input" rows="2" maxlength="2000" /></label><div class="choices"><span>Prerequisites</span><p v-if="stories.length < 2" class="muted small">Add another story to connect a prerequisite.</p><label v-for="s in stories.filter(s => s.key !== node?.key)" :key="s.key" class="check"><input type="checkbox" :checked="node.depends_on.includes(s.key)" @change="depends(s.key,($event.target as HTMLInputElement).checked)" />{{ s.title }}</label></div></template></fieldset><p v-if="locked" class="muted small">Approved scope is frozen. Story outcomes and handoffs are in Stories & runs.</p></aside><aside v-else class="card node-editor"><h3>Make every slice clear</h3><p class="muted">Select a phase or story to edit its scope, agent, model and connections. Approval applies to a saved revision.</p></aside></div>
        </template>
        <div v-if="tab === 'memory'" class="card memory-panel"><h2>Shared project memory</h2><p class="muted">The approved brief, scope and accepted handoffs are injected into every RCD project run across Claude, Codex, Hermes and OpenClaw. Agent results remain proposals until you accept them. Independent sessions can use Export context.</p><form @submit.prevent="addNote"><label>Record a decision or project note<textarea v-model="note" class="input" rows="3" maxlength="12000" placeholder="Decision, evidence, artifact location or constraint" /></label><button class="btn" :disabled="busy || !note.trim() || dirty">Append to shared memory</button></form><article v-for="m in project.memory" :key="m.id" class="memory-entry"><header><strong>{{ label(m.kind) }}</strong><small class="muted">{{ m.actor }} · {{ new Date(m.created_at * 1000).toLocaleString() }}<RouterLink v-if="m.card_id" :to="`/tasks?card=${m.card_id}`"> · task #{{ m.card_id }}</RouterLink></small></header><details v-if="m.kind === 'context'"><summary>Captured context for run #{{ m.run_id }}</summary><pre>{{ m.text }}</pre></details><pre v-else>{{ m.text }}</pre></article></div>
        <div v-if="tab === 'work'" class="card work-panel"><h2>Stories & runs</h2><label v-if="['active','paused'].includes(project.state)" class="check"><input type="checkbox" :checked="!!project.model_lock" :disabled="busy" @change="toggleModelLock" />Model lock</label><p class="muted">{{ project.model_lock ? 'Failures stop on the assigned model. Retry explicitly when ready.' : 'Approved equivalent models can take over when a model reaches its limit.' }}</p><p class="muted">Stories run in dependency order. Parallel mode gives independent stories separate Git worktrees; sequential mode uses one workspace. {{ project.handoff_approval?.mode === 'automatic' ? 'Successful eligible agent handoffs advance automatically under your project policy. Listed exceptions still need individual review.' : 'A successful agent run waits for your definition-of-done review before releasing dependent stories.' }} Pausing or canceling a run does not complete it.</p><p v-if="!nodeTasks.length" class="muted">Submit the reviewed map to have Hermes create the board stories.</p><article v-for="t in project.tasks" :key="t.card_id" class="work-row"><div><small class="muted">{{ t.role === 'story' ? 'STORY' : 'PLANNING' }} · {{ label(t.column) }}</small><h3><RouterLink :to="`/tasks?card=${t.card_id}`">#{{ t.card_id }} {{ t.title }}</RouterLink></h3><small v-if="t.working_dir" class="muted workspace-path">{{ t.agent ? agentLabel(t.agent)+' · '+(t.model || 'Agent default') : 'Human' }}<br />{{ t.working_dir }}</small><small v-if="t.run_stage" class="muted">Run #{{ t.run_id }} · {{ label(t.run_stage) }}</small></div><div class="actions"><button v-if="t.output_approval" class="btn primary" :disabled="busy" @click="showContinue(t)">Approve output &amp; continue</button><button v-if="t.role === 'story' && ['active','paused'].includes(project.state) && ((t.column === 'review' && t.run_stage !== 'awaiting_approval' && !(project.handoff_approval?.mode === 'automatic' && project.handoff_approval?.eligible.some(e => e.card_id === t.card_id))) || (human(t) && t.column !== 'done'))" class="btn primary" :disabled="busy" @click="showAccept(t,false)">Review handoff</button><button v-if="t.role === 'story' && t.column === 'failed' && project.workspaces[t.node_key]?.integration_error" class="btn" :disabled="busy" @click="showAccept(t,true)">Review integration</button><button v-if="t.role === 'story' && t.column === 'failed'" class="btn" :disabled="busy" @click="retry(t)">Retry same story</button><button v-if="t.role === 'story' && t.run_stage === 'succeeded' && !human(t) && ((t.column === 'review' && project.state === 'active') || (t.column === 'done' && ['active','complete'].includes(project.state) && !draft.nodes.some(n => n.depends_on.includes(t.node_key))))" class="btn" :disabled="busy" @click="retry(t)">Rerun same story</button><template v-if="t.role === 'story' && t.column === 'failed' && project.state === 'active'"><button v-for="r in t.retry_routes || []" :key="r.agent + '/' + r.model" class="btn" :disabled="busy" @click="retry(t,r)">Retry with {{ agentLabel(r.agent) }} · {{ r.model }}</button></template></div></article></div>
      </div>
    </div>
    <ModalShell class="project-dialog" v-if="approvalDialog" labelledby="handoff-policy-title" @close="approvalDialog = false">
      <form @submit.prevent="updateHandoffPolicy(automaticHandoffs ? 'automatic' : 'batch')">
        <h2 id="handoff-policy-title">Approve all except human-required tasks</h2>
        <p>Approve successful routine agent handoffs, except tasks that require human interaction, decisions or answers to complete the project. Keep the approved assignments and dependency order; accepted handoffs enter shared memory so the next story can start.</p>
        <label class="check"><input v-model="automaticHandoffs" type="checkbox" />Also pass future successful handoffs in this project revision automatically</label>
        <p class="small muted">Failed runs, unfinished plans, human-assigned decisions, required execution approvals and isolated Git snapshots still need individual review. Agent completion is not independent verification.</p>
        <p v-if="!project?.handoff_approval?.eligible.length" class="notice-warn">No routine agent handoffs remain. The tasks below need individual review.</p>
        <div class="review-stories"><h3 v-if="project?.handoff_approval?.eligible.length">Included</h3><article v-for="t in project?.handoff_approval?.eligible" :key="t.card_id"><strong>#{{ t.card_id }} {{ t.title }}</strong><p>{{ statusLabel(t.column) }}</p></article><h3 v-if="project?.handoff_approval?.excluded.length">Requires human input or approval</h3><article v-for="t in project?.handoff_approval?.excluded" :key="t.card_id"><strong>#{{ t.card_id }} {{ t.title }}</strong><p>{{ t.reason }}</p></article></div>
        <label class="check"><input v-model="handoffsAcknowledged" type="checkbox" />I approve the listed routine agent handoffs in this revision. Human-required tasks remain excluded.</label>
        <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
        <div class="dialog-actions actions"><button type="button" class="btn" @click="approvalDialog = false">Cancel</button><button class="btn primary" :disabled="busy || !handoffsAcknowledged || !project?.handoff_approval?.eligible.length">{{ automaticHandoffs ? 'Enable automatic handoffs' : 'Approve waiting handoffs' }}</button></div>
      </form>
    </ModalShell>
    <ModalShell class="project-dialog" v-if="continuing?.output_approval" labelledby="continue-output-title" @close="continuing = null"><form @submit.prevent="continueOutput"><h2 id="continue-output-title">Approve output &amp; continue</h2><p>{{ continuing.title }}</p><p class="muted">This run returned an unfinished plan. Continue with {{ agentLabel(continuing.agent || 'claude') }} · {{ continuing.model || 'Agent default' }} using the same story and workspace. The agent remains read-only and resumes its prior Claude session when available.</p><p>RCD will save one proposed Markdown document here:</p><p class="workspace-path">{{ continuing.output_approval.path }}</p><p class="muted">No repository edits, shell commands, delegation, publishing or handoff acceptance. Review the saved document afterward before dependent stories can start.</p><details><summary>Read the previous result and proposed plan</summary><pre class="output-preview">{{ continuing.output_approval.plan }}</pre></details><label class="check"><input v-model="outputApproved" type="checkbox" />I approve this read-only continuation and RCD saving this one Markdown file.</label><p v-if="error" class="notice-warn" role="alert">{{ error }}</p><div class="dialog-actions"><button type="button" class="btn" @click="continuing = null">Keep waiting</button><button class="btn primary" :disabled="busy || !outputApproved">{{ busy ? 'Starting continuation…' : 'Approve & continue' }}</button></div></form></ModalShell>
    <ModalShell class="project-dialog" v-if="newDialog" labelledby="new-project-title" @close="newDialog = false"><form @submit.prevent="create(true)"><h2 id="new-project-title">New project</h2><p>Delegator: {{ delegator?.delegator ? agentLabel(delegator.delegator) : 'None — choose one in Settings' }}.</p><p class="muted">Write the outcome you want. Planning and execution each have a separate review.</p><p>Planner: {{newDraft.planner_agent}} · {{newDraft.planner_model}}. <RouterLink to="/profile#ai-settings">Configure AI defaults</RouterLink> · <RouterLink to="/help?topic=project-consultant">Planning model help</RouterLink></p><label>Project name<input v-model="newDraft.title" class="input" required maxlength="200" data-autofocus /></label><label>Project brief<textarea v-model="newDraft.brief" class="input" required rows="5" maxlength="20000" /></label><PlanningBiasSlider v-model="newDraft.planning_bias" /><label class="check parallel-toggle"><input v-model="parallelNew" type="checkbox" data-testid="parallel-new" /><span><strong>Build in parallel</strong> (faster). The planner splits the work into branches that can run at the same time and adds integration stories to bring them together. Off, the default, builds one story at a time in dependency order. Parallel needs a clean git repository as the working directory.</span></label><label>Working directory<AppSelect v-model="newDraft.working_dir" required aria-label="New project working directory"><option v-for="w in workdirs?.workdirs" :key="w.path" :value="w.path" :data-description="directoryDetail(w.path,w.branch)">{{ directoryName(w.path) }}</option></AppSelect></label><p class="muted submission-note">Submit this brief to Hermes to coordinate the selected planner and return an editable map. You can also save a draft first.</p><p class="muted small">{{ profile?.discord_linked && profile.preferences.notify_plans ? 'A Discord message will let you know when the plan is ready. Edit it here or discuss it with Hermes.' : 'Link Discord in Profile for plan notifications and conversation with Hermes.' }}</p><label class="check"><input v-model="newCoordination" type="checkbox" />I approve coordination by the selected Delegator using its configured free-first route and capped Google BYOK fallback. This starts planning only.</label><label v-if="['hermes','openclaw'].includes(newDraft.planner_agent)" class="check"><input v-model="newApiPlanning" type="checkbox" />If this planner uses a paid API route, I separately approve its model-planning charges. Leave unchecked for reviewed free models.</label><p v-if="error" class="notice-warn" role="alert">{{ error }}</p><div class="dialog-actions"><button type="button" class="btn" @click="newDialog = false">Cancel</button><button type="button" class="btn" :disabled="busy" @click="create(false)">Save draft</button><button class="btn primary" :disabled="busy || !newCoordination">{{ submitting ? 'Submitting to Hermes…' : 'Submit to Hermes' }}</button></div></form></ModalShell>
    <ModalShell class="project-dialog" v-if="confirmation && project" labelledby="project-review-title" @close="confirmation = null"><h2 id="project-review-title">{{ confirmation === 'plan' ? 'Review planning request' : 'Review project submission' }}</h2><p><strong>{{ draft.title }}</strong> · revision {{ project.revision }}</p><p class="muted">{{ draft.working_dir }}</p><p>Story preference: <strong>{{ planningBiasLabel(draft.planning_bias) }}</strong></p><template v-if="confirmation === 'plan'"><p>{{ delegator?.delegator || 'The assigned Delegator' }} selects the approved planner, passes the brief to that agent, reviews the returned plan and posts an editable map. No implementation story starts from this request.</p><p>Planner: <strong>{{ draft.planner_agent === 'auto' ? 'Installed subscription planner, or reviewed free Delegator route' : agentLabel(draft.planner_agent) + ' · ' + (draft.planner_model || 'Agent default') }}</strong></p></template><template v-else><p>{{ delegator?.delegator || 'The assigned Delegator' }} will order these exact stories. RCD creates them once, adds prerequisite links and uses {{ draft.dispatch_mode }} execution. Each handoff needs your acceptance. Model routes and scope are frozen at submission. Parallel mode creates local story branches from the reviewed clean commit; accepted prerequisite commits are applied to dependent worktrees. Integration conflicts stop dispatch. The source branch is never merged automatically.</p><div class="review-stories"><article v-for="s in stories" :key="s.key"><strong>{{ s.title }}</strong><p>{{ agentLabel(s.assignee) }} · {{ s.model || 'Agent default' }} · {{ s.mode }}</p><p>Scope: {{ s.scope || 'Missing — add before submission' }}</p><p>Done when: {{ s.acceptance || 'Missing — add before submission' }}</p><p v-if="s.depends_on.length">Depends on: {{ s.depends_on.map(k => point(k)?.title).join(', ') }}</p><p v-if="s.routes.length">Approved handoffs: {{ s.routes.map(r => agentLabel(r.agent)+' · '+r.model).join(' → ') }}</p></article></div><RouteAdvice v-if="confirmation === 'submit'" :project-id="project.id" :revision="project.revision" /></template><p class="notice-warn">The selected Delegator uses its reviewed native route. Membership access and provider API billing remain separate. Free models can hit limits; a configured Google BYOK fallback can incur Google charges. The approved Hermes/OpenClaw routing uses a shared $20/month OpenRouter key cap including tracked BYOK usage; check Agents for its current setting. This is not a guarantee about your entire Google invoice or calls outside this key.</p><label class="check"><input v-model="coordination" type="checkbox" />I approve this Delegator coordination request and its configured routing.</label><label v-if="confirmation === 'plan' && ['hermes','openclaw'].includes(draft.planner_agent)" class="check"><input v-model="paidPlanner" type="checkbox" />I separately approve API model planning.</label><label v-if="confirmation === 'submit' && needsPaidWork" class="check"><input v-model="paidWork" type="checkbox" />I approve the API / BYOK routes assigned to these stories.</label><p v-if="error" class="notice-warn" role="alert">{{ error }}</p><div class="dialog-actions"><button class="btn" @click="confirmation = null">Back to map</button><button class="btn primary" :disabled="busy || !coordination" @click="confirmAction">{{ confirmation === 'plan' ? 'Start planning' : 'Submit approved revision' }}</button></div></ModalShell>
    <ModalShell class="project-dialog" v-if="accepting" labelledby="accept-handoff-title" @close="accepting = null"><form @submit.prevent="accept"><h2 id="accept-handoff-title">{{ integrationReview ? 'Confirm prerequisite integration' : 'Accept story handoff' }}</h2><p><strong>{{ accepting.title }}</strong></p><p class="muted">Verify its definition of done in the task and review artifacts/checks. Edit the summary below into the context the next agent should receive.</p><p v-if="integrationReview" class="notice-warn">Resolve the prerequisite changes in this story workspace, then verify the integrated files. Confirming this records your decision; the story remains Failed until you explicitly retry it and review its result.</p><RouterLink :to="`/tasks?card=${accepting.card_id}`">Open task and run evidence</RouterLink><p v-if="project?.workspaces[accepting.node_key]" class="notice-warn">Review the story branch {{ project.workspaces[accepting.node_key]?.branch }}. Review and select each changed file below, or commit your reviewed changes locally before acceptance. Dependent stories receive the accepted commits. Nothing is merged into the source repository.</p><div v-if="artifact?.files.length" class="choices"><h3>Files for this local snapshot</h3><p class="small muted">Select only after reviewing these changes. Untracked file contents must be checked in the workspace; the diff below covers tracked files. Every changed file must be selected or committed/reverted outside RCD.</p><label v-for="file in artifact.files" :key="file" class="check"><input v-model="selectedFiles" type="checkbox" :value="file" />{{ file }}</label><details><summary>Review tracked changes</summary><pre>{{ artifact.diff || 'No tracked diff. Inspect the new files in the workspace.' }}</pre></details></div><section v-if="artifact?.output"><h3>Proposed Markdown document</h3><p class="workspace-path">{{ artifact.output.path }}</p><pre class="output-preview">{{ artifact.output.markdown }}</pre><label class="check"><input v-model="outputReviewed" type="checkbox" />I reviewed this document against the story’s definition of done.</label></section><label>Verified handoff<textarea v-model="handoff" class="input" rows="8" required maxlength="12000" placeholder="Changes and paths, checks/results, decisions, remaining risks and next steps" /></label><p v-if="error" class="notice-warn" role="alert">{{ error }}</p><div class="dialog-actions"><button type="button" class="btn" @click="accepting = null">Keep in review</button><button class="btn primary" :disabled="busy || !handoff.trim() || !artifact || (!!artifact.output && !outputReviewed)">{{ integrationReview ? 'Confirm integration' : 'Accept handoff' }}</button></div></form></ModalShell>
    <ModalShell class="project-dialog" v-if="retierDialog" labelledby="retier-title" @close="retierDialog = false">
      <form @submit.prevent="retierProject">
        <h2 id="retier-title">Use lower-cost models</h2>
        <p><strong>{{ retierableTasks.length }} unstarted Claude or Codex stories</strong> in this paused revision will be amended.</p>
        <div class="review-stories">
          <article><strong>Claude Haiku 5.5</strong><p>Replaces the current Claude model on eligible queued stories.</p></article>
          <article><strong>Codex GPT-6 Luna</strong><p>Replaces the current Codex model on eligible queued stories.</p></article>
        </div>
        <p class="notice-warn">Running, completed, review, failed and human stories are unchanged. Scope, dependencies, workspaces, security gates, publication gates and required human decisions remain unchanged. Resume dispatch separately after reviewing this amendment.</p>
        <label class="check"><input v-model="retierAcknowledged" type="checkbox" />I approve these lower-cost routes for the listed unstarted stories in this revision.</label>
        <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
        <div class="dialog-actions"><button type="button" class="btn" @click="retierDialog = false">Keep paused</button><button class="btn primary" :disabled="busy || !retierAcknowledged">Apply model change</button></div>
      </form>
    </ModalShell>
    <ModalShell class="project-dialog" v-if="repairing" labelledby="repair-execution-title" @close="repairing = null">
      <form @submit.prevent="repairExecution">
        <h2 id="repair-execution-title">Repair unfinished execution story</h2>
        <p><strong>#{{ repairing.card_id }} {{ repairing.title }}</strong></p>
        <p>{{ repairing.incomplete_reason }}</p>
        <p>The read-only result remains in run history but will not be accepted. RCD will retry the same scope and definition of done in <strong>Edit workspace</strong> mode on the approved lower-cost primary route shown in the project map.</p>
        <p class="notice-warn">This expands this story from inspection to local workspace execution. Dependencies, workspace, human decisions, security gates and publication gates remain unchanged. The project stays paused until you resume it separately.</p>
        <label class="check"><input v-model="repairAcknowledged" type="checkbox" />I approve repairing this inconsistent assignment and retrying its existing scope as an execution task.</label>
        <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
        <div class="dialog-actions"><button type="button" class="btn" @click="repairing = null">Keep in review</button><button class="btn primary" :disabled="busy || !repairAcknowledged">Repair &amp; queue retry</button></div>
      </form>
    </ModalShell>
  </section>
</template>
<style scoped>
.output-preview { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 24rem; overflow: auto; padding: var(--gap); border: 1px solid var(--surface-border); border-radius: var(--radius); }

.project-dialog :deep(.modal-panel) { padding: var(--gap-lg); }
.project-dialog h2 { font-size: var(--font-size-xl); }
.project-dialog p { line-height: var(--line-height); }
.project-dialog .dialog-actions { padding-top: var(--gap-lg); border-top: 1px solid var(--glass-border); }
@media (max-width: 600px) {
  .project-dialog :deep(.modal-panel) { padding: var(--gap); }
}

.page-header,.project-heading,.actions,.map-toolbar,.editor-title,.work-row,.dialog-actions{display:flex;align-items:center;justify-content:space-between;gap:var(--gap);flex-wrap:wrap}.page-header p{margin-bottom:0}.project-layout{display:grid;grid-template-columns:var(--project-library-width) minmax(0,1fr);gap:var(--gap-lg);margin-top:var(--gap-lg);align-items:start}.project-index{position:sticky;top:var(--gap)}h2{font-size:var(--font-size-lg);margin:0 0 var(--gap)}h3{font-size:var(--font-size);margin:0 0 var(--gap-sm)}.project-link{display:grid;gap:var(--gap-xs);width:100%;text-align:left;padding:var(--gap);margin-bottom:var(--gap-sm);background:transparent;color:var(--text);border:1px solid var(--surface-border);border-radius:var(--radius);cursor:pointer;font:inherit;overflow-wrap:anywhere}.project-link.selected{background:var(--nav-active);border-color:var(--accent)}.project-link small,.node-top,.map-node small{color:var(--text-muted);font-size:var(--font-size-xs)}.project-main{min-width:0}.project-heading{flex-direction:row;background:var(--agent-glass)}.eyebrow{color:var(--accent);font-size:var(--font-size-xs);letter-spacing:var(--eyebrow-spacing)}.project-heading h2{margin-top:var(--gap-sm)}.status-label,.dirty{font-size:var(--font-size-xs);color:var(--accent)}.dirty{margin-left:var(--gap);color:var(--warn)}.tabs{display:flex;gap:var(--gap-sm);margin:var(--gap) 0;flex-wrap:wrap}.tabs .active{border-color:var(--accent);background:var(--accent-soft)}.brief-panel{margin-bottom:var(--gap)}summary{cursor:pointer;color:var(--text);padding:var(--gap-sm) 0}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--gap)}.full{grid-column:1/-1}label{display:grid;gap:var(--gap-sm);color:var(--text-muted);font-size:var(--font-size-sm);margin-top:var(--gap)}textarea{resize:vertical}.map-layout{display:grid;grid-template-columns:minmax(0,1fr) var(--project-editor-width);gap:var(--gap)}.map-panel{min-width:0;padding:var(--gap)}.map-legend{margin:var(--gap-sm) 0}.map-scroll{overflow:auto;max-height:var(--project-map-height);min-height:var(--project-map-min-height);border:1px solid var(--surface-border);border-radius:var(--radius);background:var(--glass-bg);overscroll-behavior:contain}.map-canvas{position:relative;transform-origin:top left;background-image:radial-gradient(var(--surface-border) 1px,transparent 1px);background-size:var(--project-grid-size) var(--project-grid-size)}.connections{position:absolute;inset:0;pointer-events:none;overflow:visible}.connections path{fill:none;stroke:var(--accent);stroke-width:2;opacity:.6}.connections marker path{fill:var(--accent);stroke:none}.connections .dependency-edge{stroke:var(--brand-to);stroke-dasharray:6 5;opacity:.8}.map-node{position:absolute;display:grid;gap:var(--gap-xs);width:var(--project-node-width);height:var(--project-node-height);text-align:left;padding:var(--gap);color:var(--text);border:1px solid var(--surface-border);border-radius:var(--surface-radius);background:var(--agent-glass);box-shadow:var(--surface-shadow);font:inherit;cursor:grab;touch-action:none}.map-node.phase{background:var(--card-glass);border-left:var(--nav-indicator-width) solid var(--brand-to)}.map-node.selected{border-color:var(--accent);background:var(--agent-glass-selected)}.map-node strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:var(--font-size-sm);line-height:var(--line-height)}.map-node small{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.node-top{display:flex;justify-content:space-between;gap:var(--gap-xs)}.map-empty{position:absolute;top:var(--project-empty-top);left:var(--gap-lg);max-width:var(--project-editor-width);color:var(--text-muted)}.node-editor{min-width:0;max-height:var(--project-editor-height);overflow:auto;position:sticky;top:var(--gap)}fieldset{border:0;padding:0;margin:0;min-width:0}.check{display:flex;align-items:flex-start;gap:var(--gap-sm)}.check input{margin-top:var(--gap-xs);flex-shrink:0;accent-color:var(--accent)}.choices{margin-top:var(--gap)}.choices>span{color:var(--text-muted);font-size:var(--font-size-sm)}.welcome{line-height:var(--line-height)}.welcome h2{margin-top:var(--gap)}.welcome ol{list-style:decimal;padding-left:var(--gap-lg)}.welcome li{margin:var(--gap-sm) 0}.memory-entry,.work-row{border-top:1px solid var(--surface-border);padding:var(--gap) 0;margin-top:var(--gap)}.memory-entry header{display:grid;gap:var(--gap-xs)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:var(--font-size-sm);line-height:var(--line-height)}.review-stories{max-height:var(--project-review-height);overflow:auto}.review-stories article{border-top:1px solid var(--surface-border);padding:var(--gap-sm) 0}.review-stories p{font-size:var(--font-size-sm);margin:var(--gap-xs) 0}.dialog-actions{justify-content:flex-end;margin-top:var(--gap-lg)}.work-row h3{margin:var(--gap-xs) 0}.route-choice{display:grid;gap:var(--gap-sm);margin:var(--gap-sm) 0;padding:var(--gap-sm);border:1px solid var(--surface-border);border-radius:var(--radius)}.workspace-path{display:block;overflow-wrap:anywhere}.pipeline{font-size:var(--font-size-sm)}.pipeline progress{width:100%;height:var(--gap-sm);accent-color:var(--accent);margin:var(--gap-sm) 0}.planning-stages{display:flex;gap:var(--gap);list-style:none;padding:0;flex-wrap:wrap}.planning-stages li{flex:1;min-width:160px;color:var(--text-muted);padding:var(--gap-sm);border-bottom:2px solid var(--surface-border)}.planning-stages .current{color:var(--accent);border-color:var(--accent)}.planning-stages .finished{color:var(--ok);border-color:var(--ok)}.submission-note{margin-top:var(--gap-lg);font-size:var(--font-size-sm)}.small{font-size:var(--font-size-xs)}
@media(max-width:1200px){.map-layout{grid-template-columns:1fr}.node-editor{position:static;max-height:none}.project-layout{grid-template-columns:var(--project-library-small) minmax(0,1fr)}}
@media(max-width:760px){.project-layout{grid-template-columns:1fr}.project-index{position:static}.project-index .project-link{display:inline-grid;width:var(--project-library-small);margin-right:var(--gap-sm)}.project-index{max-height:var(--project-phone-library-height);overflow:auto}.form-grid{grid-template-columns:1fr}.project-heading .actions{width:100%}.map-scroll{max-height:var(--project-phone-map-height)}.map-toolbar .btn{font-size:var(--font-size-xs)}}
</style>

<style scoped>
.live-project{margin-top:var(--gap);background:var(--card-glass)}.live-summary{display:flex;align-items:center;justify-content:space-between;gap:var(--gap);flex-wrap:wrap}.project-bubble{display:flex;align-items:center;gap:var(--gap-sm);flex-wrap:wrap;padding:var(--gap-sm) var(--gap);border:1px solid var(--status-color,var(--surface-border));border-radius:var(--surface-radius);background:color-mix(in srgb,var(--status-color,var(--accent)) 12%,transparent)}.live-project progress{width:100%;height:8px;margin-top:var(--gap);accent-color:var(--ok)}.status-running,.status-active,.status-planning,.status-dispatching{--status-color:var(--accent)}.status-review,.status-approval,.status-human,.status-paused{--status-color:var(--warn)}.status-done,.status-complete{--status-color:var(--ok)}.status-failed,.status-planning_failed{--status-color:var(--danger)}.status-queued{--status-color:var(--brand-to)}.status-blocked,.status-backlog,.status-draft{--status-color:var(--text-muted)}.status-dot{display:inline-block;width:9px;height:9px;flex-shrink:0;border-radius:50%;background:var(--status-color,var(--text-muted))}.status-legend{display:flex;flex-wrap:wrap;gap:var(--gap);margin:var(--gap) 0;color:var(--text-muted)}.status-legend span,.node-live-status{display:flex;align-items:center;gap:var(--gap-sm)}.map-node{border-left:4px solid var(--status-color,var(--surface-border));background:linear-gradient(color-mix(in srgb,var(--status-color,var(--accent)) 11%,transparent),color-mix(in srgb,var(--status-color,var(--accent)) 4%,transparent)),var(--agent-glass)}.map-node.phase{border-left-color:var(--status-color,var(--brand-to))}.map-node .node-top>span:last-child{color:var(--status-color,var(--text-muted))}.project-link{border-left:3px solid var(--status-color,var(--surface-border))}.node-live-status{font-size:var(--font-size-sm);flex-wrap:wrap}.node-live-status a{margin-left:auto}
</style>
