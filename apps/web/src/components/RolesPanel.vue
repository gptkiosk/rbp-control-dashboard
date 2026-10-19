<script setup lang="ts">
import NoteFold from '@/components/NoteFold.vue'
import PanelHead from '@/components/PanelHead.vue'
import { onMounted, ref } from 'vue'
import { getJson, postJson } from '@/lib/api'
import ModalShell from '@/components/ModalShell.vue'
import ChipTag from '@/components/ChipTag.vue'
type Status = {roles: Record<string,string>; workspace:string; available:string[]; delegator:string|null; rollback_available:boolean; guidance_installed:boolean; recovery_required:boolean; revision:string}
type Preview = {roles:Record<string,string>; workspace:string; plan_sha256:string; changes:{path:string;diff:string}[]; notice:string}
const state = ref<Status|null>(null), roles = ref<Record<string,string>>({}), workspace = ref(''), preview = ref<Preview|null>(null)
const busy = ref(false), error = ref(''), rollback = ref(false)
async function load() { state.value = await getJson<Status>('/api/roles'); const next = Object.fromEntries([...new Set([...Object.keys(state.value.roles),...state.value.available])].map(agent=>[agent,state.value!.roles[agent] || 'worker'])); for (const agent of Object.keys(next)) if (agent !== 'hermes' && next[agent] === 'delegator') next[agent] = 'worker'; next.hermes = state.value.available.includes('hermes') ? 'delegator' : 'worker'; roles.value = next; workspace.value=state.value.workspace }
async function action(fn:()=>Promise<void>) {busy.value=true;error.value='';try {await fn()} catch(e) {error.value=e instanceof Error?e.message:'Role action failed'} finally {busy.value=false}}
async function review() {await action(async()=>{preview.value=await postJson<Preview>('/api/roles/preview',{roles:roles.value,workspace:workspace.value})})}
async function apply() {const plan=preview.value;if(!plan)return;await action(async()=>{await postJson('/api/roles/apply',{roles:plan.roles,workspace:plan.workspace,plan_sha256:plan.plan_sha256,confirm:true});preview.value=null;await load()})}
async function recover() {await action(async()=>{await postJson('/api/roles/recover',{confirm:true});await load()})}
async function restore() {await action(async()=>{await postJson('/api/roles/rollback',{confirm:true});rollback.value=false;await load()})}
onMounted(()=>action(load))
</script>
<template>
<section id="agent-roles" class="card">
  <PanelHead id="agent-roles-title" title="Agent roles" :status="state ? (state.available.includes('hermes') ? 'Coordinator: Hermes' : 'Coordinator not installed') : undefined" :tone="state?.available.includes('hermes') ? 'ok' : 'warn'" help="maintenance" />
  <p class="muted small">The Coordinator is fixed as Hermes. This card assigns worker, reviewer and security roles; role labels do not grant tool access or change billing.</p>
  <template v-if="state">
    <p>Coordinator: <strong>Hermes{{state.available.includes('hermes') ? '' : ' (not installed)'}}</strong>. {{state.guidance_installed && state.roles.hermes === 'delegator' ? 'Managed starter guidance installed.':'Starter guidance has not been installed.'}}</p>
    <div v-for="agent in Object.keys(roles)" :key="agent" class="role-row"><label :for="`role-${agent}`">{{agent}}{{ state.available.includes(agent) ? '' : ' (not installed)' }}</label><ChipTag v-if="agent === 'hermes'" tone="accent">Coordinator</ChipTag><select v-else :id="`role-${agent}`" v-model="roles[agent]" :disabled="busy"><option value="worker">Worker</option><option value="reviewer">Reviewer</option><option value="security">Security</option></select></div>
    <label class="workspace">Agent workspace for Grok or OpenClaw<input v-model="workspace" placeholder="An existing directory inside an allowed workspace root" :disabled="busy" /></label>
    <NoteFold label="What roles do"><p class="small muted">Coordinator is fixed as Hermes. Reviewers and Security roles describe assignments; they do not add automatic review jobs. In-progress pipelines retain their approved agent and model. Native instruction targets are shown in the preview.</p></NoteFold>
    <button v-if="state.recovery_required" class="btn" :disabled="busy" @click="recover">Recover interrupted assignment</button>
    <button class="btn" :disabled="busy || state.recovery_required" @click="review">Preview role changes</button>
    <button v-if="state.rollback_available" class="btn" :disabled="busy" @click="rollback=true">Roll back last assignment</button>
  </template>
  <p v-if="error" class="notice-warn" role="alert">{{error}}</p>
  <ModalShell v-if="preview" labelledby="role-review-title" @close="preview=null"><h2 id="role-review-title">Review role changes</h2><p>{{preview.notice}}</p><p>Only the marked managed block changes. Your surrounding instructions are retained. A private backup supports rollback; later operator edits cause rollback to refuse.</p><article v-for="change in preview.changes" :key="change.path"><strong>{{change.path}}</strong><pre>{{change.diff}}</pre></article><p v-if="!preview.changes.length">No native instruction text changes.</p><button class="btn" @click="preview=null">Cancel</button><button class="btn primary" :disabled="busy" @click="apply">Confirm assignment and instructions</button></ModalShell>
  <ModalShell v-if="rollback" labelledby="role-rollback-title" @close="rollback=false"><h2 id="role-rollback-title">Roll back last assignment</h2><p>Restore the previous role assignment and its exact instruction files. Rollback refuses if those files changed after assignment.</p><button class="btn" @click="rollback=false">Cancel</button><button class="btn primary" :disabled="busy" @click="restore">Confirm rollback</button></ModalShell>
</section>
</template>
<style scoped>
.role-row {display:flex;gap:1rem;align-items:center;margin:.5rem 0}.role-row label{min-width:7rem}.workspace{display:block;margin:1rem 0}.workspace input{display:block;width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:24rem;overflow:auto}
</style>
