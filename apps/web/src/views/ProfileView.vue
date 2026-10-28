<script setup lang="ts">
import RoutePolicyPanel from '@/components/RoutePolicyPanel.vue'
import RouteRecoveryPanel from '@/components/RouteRecoveryPanel.vue'
import RolesPanel from '@/components/RolesPanel.vue'
import CredentialsPanel from '@/components/CredentialsPanel.vue'
import ReportStoragePanel from '@/components/ReportStoragePanel.vue'
import GithubSettingsPanel from '@/components/GithubSettingsPanel.vue'
import AgentToolsPanel from '@/components/AgentToolsPanel.vue'
import SystemToolsPanel from '@/components/SystemToolsPanel.vue'
import UpdatePanel from '@/components/UpdatePanel.vue'
import HousekeepingPanel from '@/components/HousekeepingPanel.vue'
import BugIntakePanel from '@/components/BugIntakePanel.vue'
import GithubActionsPanel from '@/components/GithubActionsPanel.vue'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import AppSelect from '@/components/AppSelect.vue'
import PlanningBiasSlider from '@/components/PlanningBiasSlider.vue'
import CoordinatorSetupPanel from '@/components/CoordinatorSetupPanel.vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import { getJson, putJson, postJson, deleteJson } from '@/lib/api'
import type { Profile, Preferences, CoordinatorBootstrapPreferences } from '@/lib/profile'
import { directoryName, directoryDetail } from '@/lib/selectLabels'
import { useThemeStore } from '@/stores/theme'
const profile = ref<Profile | null>(null), preferences = ref<(Preferences & {coordinator_bootstrap: CoordinatorBootstrapPreferences}) | null>(null)
const workdirs = ref<{ path: string; branch: string | null }[]>([]), origins = ref<string[]>([])
const error = ref(''), notice = ref(''), busy = ref(false), pairing = ref('')
const guide = ref<InstanceType<typeof CredentialsPanel> | null>(null)
const secrets = ref<Record<string,string>>({ openrouter: '', discord: '', fal: '' })
const spending = ref<Record<string, number | string | boolean | null> | null>(null)
const theme = useThemeStore()
const router = useRouter()
const bootstrapReadiness = ref<{ ready: boolean; checks: {id:string;label:string;ready:boolean;link:string}[] } | null>(null)
// Keep coordinator bootstrap choices in their own profile section; old hash links still open the right group.
const TABS = [{ id: 'settings', label: 'Settings' }, { id: 'models', label: 'Models & providers' }, { id: 'coordinator', label: 'Coordinator setup' }, { id: 'updates', label: 'Updates & installs' }, { id: 'maintenance', label: 'Maintenance & access' }] as const
type Tab = typeof TABS[number]['id']
const HOME: Record<string, Tab> = { 'models-providers': 'models', 'coordinator-bootstrap': 'coordinator', 'route-recovery': 'coordinator', updates: 'updates', 'agent-tools': 'updates', 'system-tools': 'updates', 'agent-roles': 'maintenance', housekeeping: 'maintenance', 'github-settings': 'maintenance', 'github-actions': 'maintenance', 'bug-intake': 'maintenance', 'issue-tasks': 'maintenance', roles: 'maintenance', reports: 'maintenance' }
const THEMES = [{ id: 'system', label: 'Device' }, { id: 'light', label: 'Light' }, { id: 'dark', label: 'Dark' }] as const
const tab = ref<Tab>('settings')
function fromHash() {
  const id = (router ? router.currentRoute.value.hash : window.location.hash).replace('#', '')
  if (!id) return
  tab.value = HOME[id] ?? 'settings'
  void nextTick(() => document.getElementById(id)?.scrollIntoView?.({ block: 'start' }))
}
function pick(id: Tab) { tab.value = id; if (router) void router.replace({ path: router.currentRoute.value.path, query: router.currentRoute.value.query, hash: '' }); else history.replaceState(null, '', `${window.location.pathname}${window.location.search}`) }
onMounted(fromHash)
if (router) watch(() => router.currentRoute.value.hash, fromHash)
window.addEventListener('hashchange', fromHash)
onBeforeUnmount(() => window.removeEventListener('hashchange', fromHash))
const BOOTSTRAP_DEFAULTS = { mode: 'stable' as 'stable'|'custom', platforms: ['openclaw','claude','codex','grok'] as ('openclaw'|'claude'|'codex'|'grok')[], roles: ['developer','security'] as ('developer'|'security'|'reviewer')[], shared_project_memory: true, project_workspaces: true, model_policy: 'reuse_configured_default' as const, security_review: 'risk_based' as const }
function apply(p: Profile) { profile.value = p; preferences.value = {ai_agent:'hermes',ai_model:'openrouter/free',...structuredClone(p.preferences),coordinator_bootstrap:{...BOOTSTRAP_DEFAULTS,...p.preferences.coordinator_bootstrap}} }
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch(e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
onMounted(() => { void action(async () => {
  const p = await getJson<Profile>('/api/profile'); apply(p); origins.value = p.origins ?? []
  if (preferences.value && !preferences.value.discord_channel_id) preferences.value.discord_channel_id = p.suggested_discord_channel ?? ''
  workdirs.value = (await getJson<{ workdirs: typeof workdirs.value }>('/api/workdirs')).workdirs
  bootstrapReadiness.value = await getJson('/api/profile/coordinator-bootstrap/readiness')
}) })
async function save() { await action(async () => {
  apply(await putJson<Profile>('/api/profile', preferences.value)); theme.choose(profile.value!.preferences.theme)
  notice.value = tab.value === 'coordinator' ? 'Coordinator bootstrap preferences saved.' : 'Profile saved. New projects use these defaults.'
}) }
// Saves the current choices; the setup check reads them from the profile.
async function persistPreferences() { apply(await putJson<Profile>('/api/profile', preferences.value)) }
async function refreshCoordinatorReadiness() { await action(async () => {
  bootstrapReadiness.value = await getJson<{ ready:boolean; checks:{id:string;label:string;ready:boolean;link:string}[] }>('/api/profile/coordinator-bootstrap/readiness')
  notice.value = bootstrapReadiness.value.ready ? 'Hermes is ready.' : 'Readiness updated. Complete the linked Hermes items first.'
}) }
async function saveKey(provider: string) { await action(async () => {
  const key = secrets.value[provider]
  if (!key) return
  try { profile.value = await putJson<Profile>(`/api/profile/credentials/${provider}`, { value: key }) }
  finally { secrets.value[provider] = '' }
  notice.value = 'Credential saved privately. Its value cannot be read back.'
  void guide.value?.load()
}) }
async function removeKey(provider: string) { await action(async () => {
  profile.value = await deleteJson<Profile>(`/api/profile/credentials/${provider}`); spending.value = null; notice.value = 'Credential removed.'
  void guide.value?.load()
}) }
async function pair() { await action(async () => {
  // Save the displayed channel before generating a code for that channel.
  apply(await putJson<Profile>('/api/profile', preferences.value))
  const result = await postJson<{ instruction: string }>('/api/profile/discord/pair'); pairing.value = result.instruction
}) }
async function refresh() { await action(async () => { const p = await getJson<Profile>('/api/profile'); profile.value = p; if(p.discord_linked) pairing.value = ''; notice.value = p.discord_linked ? 'Discord identity linked.' : 'Waiting for Hermes to link your code.' }) }
async function unlink() { await action(async () => { profile.value = await postJson<Profile>('/api/profile/discord/unlink'); pairing.value = ''; notice.value = 'Discord access revoked.' }) }
async function shareKey(on: boolean) { await action(async () => {
  // Saves only this switch on top of what is already saved, so unsaved edits elsewhere on the page are not swept in.
  apply(await putJson<Profile>('/api/profile', { ...profile.value!.preferences, use_saved_openrouter_key: on }))
  notice.value = on ? 'Hermes and OpenClaw runs now use your saved OpenRouter key.' : 'Hermes and OpenClaw no longer receive your saved OpenRouter key.'
}) }
async function checkSpending() { await action(async () => { spending.value = (await postJson<{ spending: typeof spending.value }>('/api/profile/openrouter/check')).spending }) }
function exportPreferences() {
  const { setup: _setup, use_saved_openrouter_key: _share, ...portable } = preferences.value!
  const url = URL.createObjectURL(new Blob([JSON.stringify({ version: 1, preferences: portable },null,2)], { type: 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = 'mcd-preferences.json'; a.click(); URL.revokeObjectURL(url)
}
async function importPreferences(event: Event) { await action(async () => {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return
  if (file.size > 16000) throw new Error('Choose a small RCD preferences file.')
  const data = JSON.parse(await file.text())
  if (data.version !== 1 || !data.preferences || typeof data.preferences !== 'object' || Object.keys(data).some(k => !['version','preferences'].includes(k)) || Object.keys(data.preferences).some(k => !Object.keys(profile.value!.preferences).includes(k))) throw new Error('Invalid preferences file.')
  preferences.value = { ...data.preferences, coordinator_bootstrap: { ...BOOTSTRAP_DEFAULTS, ...data.preferences.coordinator_bootstrap }, setup: profile.value!.preferences.setup, use_saved_openrouter_key: profile.value!.preferences.use_saved_openrouter_key }; notice.value = 'Preferences loaded for review. Save to apply; Discord will need pairing on a new installation.'
}) }
</script>

<template>
  <section aria-labelledby="profile-title">
    <header class="page-head">
      <h1 id="profile-title" class="page-title has-icon"><AppIcon name="agents" size="lg" />Settings</h1>
      <RouterLink to="/setup" class="btn">Setup wizard</RouterLink>
    </header>
    <nav class="tabs" role="tablist" aria-label="Settings sections">
      <button v-for="t in TABS" :key="t.id" type="button" role="tab" class="tab" :class="{ on: tab === t.id }" :aria-selected="tab === t.id" :data-tab="t.id" @click="pick(t.id)">{{ t.label }}</button>
    </nav>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p><p v-if="notice" class="card" role="status">{{ notice }}</p>

    <div v-show="tab === 'updates'" class="group" role="tabpanel" aria-label="Updates and installs">
      <p class="muted small">Dashboard releases, agent tools and optional system tools. Each shows its version and status, runs with a progress bar and log, and ends with a health check. <RouterLink to="/help?topic=app-updates">How-to</RouterLink></p>
      <UpdatePanel />
      <AgentToolsPanel />
      <SystemToolsPanel />
    </div>

    <div v-show="tab === 'maintenance'" class="group" role="tabpanel" aria-label="Maintenance and access">
      <HousekeepingPanel />
      <ReportStoragePanel />
      <BugIntakePanel />
      <RolesPanel />
      <GithubSettingsPanel id="github-settings" />
      <GithubActionsPanel />
    </div>

    <div v-if="profile && preferences" v-show="tab === 'settings'" class="profile-grid" role="tabpanel" aria-label="Settings">
      <form class="card preferences" @submit.prevent="save">
        <header class="card-head"><h2>Preferences</h2><span class="muted small owner">{{ profile.owner }}</span></header>
        <div class="row"><span class="name" id="appearance-label">Appearance</span>
          <div class="seg" role="radiogroup" aria-labelledby="appearance-label"><button v-for="t in THEMES" :key="t.id" type="button" role="radio" class="seg-btn" :class="{ on: preferences.theme === t.id }" :aria-checked="preferences.theme === t.id" @click="preferences.theme = t.id">{{ t.label }}</button></div>
        </div>
        <label class="row"><span class="name">Workspace</span><AppSelect v-model="preferences.working_dir" aria-label="Default working directory"><option value="">First allowed workspace</option><option v-for="w in workdirs" :key="w.path" :value="w.path" :data-description="directoryDetail(w.path,w.branch)">{{ directoryName(w.path) }}</option></AppSelect></label>
        <section id="ai-settings" class="row stack" data-testid="default-models"><span class="name">Default models</span>
          <p class="muted small">New chat, New task and the project consultant start from the Chat and Tasks defaults in <RouterLink to="/profile#models-providers">Models &amp; providers</RouterLink>, with the Coordinator, planner and story defaults.</p>
        </section>
        <PlanningBiasSlider v-model="preferences.planning_bias" compact />
        <div class="actions"><button class="btn primary" :disabled="busy">Save preferences</button><button type="button" class="btn" @click="exportPreferences">Export</button><label class="btn import">Import<input type="file" accept="application/json" aria-label="Import preferences" @change="importPreferences" /></label></div>
      </form>
      <div class="profile-stack">
        <section id="discord-profile" class="card" aria-labelledby="discord-title">
          <header class="card-head"><h2 id="discord-title">Hermes on Discord</h2><span class="pill" :class="profile.discord_linked ? 'good' : ''">{{ profile.discord_linked ? '✓ Linked' : 'Not linked' }}</span><RouterLink to="/help?topic=profile-discord" class="small">How-to</RouterLink></header>
          <label class="row"><span class="name">Channel ID</span><input v-model="preferences.discord_channel_id" class="input" inputmode="numeric" autocomplete="off" maxlength="22" /></label>
          <label class="row"><span class="name">Link address</span><AppSelect v-model="preferences.dashboard_origin" aria-label="Dashboard address"><option value="">Installation default</option><option v-for="o in origins" :key="o" :value="o">{{ o }}</option></AppSelect></label>
          <div class="switches" role="group" aria-label="What Hermes may do in Discord">
            <ToggleSwitch v-model="preferences.notify_plans" label="Plan updates" hint="Tell me when a plan is ready or planning stops." />
            <ToggleSwitch v-model="preferences.allow_discord_planning" label="Start planning" hint="My Discord requests may start subscription planning with Hermes coordination." />
            <ToggleSwitch v-model="preferences.allow_discord_control" label="Control approved work" hint="Pause/resume projects, coordinate coding workspaces and switch limited subscriptions. New plan approvals, billing and credentials stay in RCD." />
            <ToggleSwitch v-model="preferences.allow_discord_diagnostics" label="Read failed runs" hint="Errors, short handoff excerpts and log tails, with credentials and addresses removed. Read only." />
            <ToggleSwitch v-model="preferences.allow_discord_standards" label="Project standards" hint="Read a project's standards and propose additions. You approve on the project page." />
            <ToggleSwitch v-model="preferences.allow_discord_repositories" label="New repositories" hint="Propose a new private GitHub repository. It waits for your approval here." />
            <ToggleSwitch v-model="preferences.allow_discord_issue_tasks" label="Issue tasks" hint="Turn one linked configured GitHub issue into a Hermes-assigned task. Code still waits for task approval." />
            <ToggleSwitch v-model="preferences.allow_discord_maintenance" label="Housekeeping" hint="Read Housekeeping findings and propose fixes. You approve here." />
          </div>
          <div class="actions"><button class="btn primary" :disabled="busy || !preferences.discord_channel_id" @click="pair">{{ profile.discord_linked ? 'Pair again' : 'Get pairing code' }}</button><button class="btn" :disabled="busy" @click="save">Save connection</button><button class="btn" :disabled="busy" @click="refresh">Check pairing</button><button v-if="profile.discord_linked" class="btn" :disabled="busy" @click="unlink">Unlink Discord</button></div>
          <div v-if="pairing" class="pairing" role="status"><strong>Send to Hermes in this channel within 10 minutes:</strong><p>{{ pairing }}</p><small>Treat the code as private. Then choose Check pairing.</small></div>
        </section>
        <section id="credentials-profile" class="card" aria-labelledby="credentials-title">
          <header class="card-head"><h2 id="credentials-title">Private credentials</h2><span class="muted small">write-only</span><RouterLink to="/help?topic=sign-in" class="small">How-to</RouterLink></header>
          <CredentialsPanel ref="guide" :credentials="profile.credentials" :secrets="secrets" :busy="busy" :share-on="!!profile.preferences.use_saved_openrouter_key" :spending="spending"
            @secret="(p, v) => secrets[p] = v" @save="saveKey" @remove="removeKey" @share="shareKey" @spend="checkSpending" />
        </section>
      </div>
    </div>

    <div v-show="tab === 'models'" class="group" role="tabpanel" aria-label="Models and providers"><RoutePolicyPanel /></div>
    <RouteRecoveryPanel v-show="tab === 'coordinator'" @saved="p => { if (preferences) preferences.route_recovery = p; if (profile) profile.preferences.route_recovery = p }" />
    <form v-if="profile && preferences" v-show="tab === 'coordinator'" id="coordinator-bootstrap" class="card bootstrap-card" role="tabpanel" aria-labelledby="bootstrap-title" @submit.prevent="save">
      <header class="card-head"><div><h2 id="bootstrap-title">Coordinator setup</h2><p class="muted small">The dashboard checks the platforms you pick and sets up what is missing. No model runs until you start the validation project.</p></div><RouterLink to="/help?topic=maintenance" class="small">How-to</RouterLink></header>
      <fieldset class="choice-group mode-group"><legend>Setup mode</legend>
        <label class="mode"><input v-model="preferences.coordinator_bootstrap.mode" type="radio" value="stable" /><span><strong>Stable start (recommended)</strong><span class="small muted">Creates the missing OpenClaw role agents and project folders from tested templates. Never changes what is already there.</span></span></label>
        <label class="mode"><input v-model="preferences.coordinator_bootstrap.mode" type="radio" value="custom" /><span><strong>I’ll configure the platforms myself</strong><span class="small muted">Changes nothing. Checks what you set up and lists any gaps with links.</span></span></label>
      </fieldset>
      <fieldset class="choice-group"><legend>Platforms</legend><p class="small muted">Each one is checked: installed, starts, and has a route the dashboard may use. Unready ones show the fix.</p>
        <label v-for="item in [{id:'openclaw',name:'OpenClaw'},{id:'claude',name:'Claude Code'},{id:'codex',name:'Codex'},{id:'grok',name:'Grok Build'}]" :key="item.id" class="choice"><input v-model="preferences.coordinator_bootstrap.platforms" type="checkbox" :value="item.id" /><span>{{ item.name }}</span></label>
      </fieldset>
      <template v-if="preferences.coordinator_bootstrap.mode === 'stable'">
        <fieldset class="choice-group"><legend>OpenClaw role agents</legend><p class="small muted">Missing ones are created on OpenClaw’s configured default model. Existing agents are kept.</p>
          <label v-for="item in [{id:'developer',name:'Developer'},{id:'security',name:'Security reviewer'},{id:'reviewer',name:'Acceptance reviewer'}]" :key="item.id" class="choice"><input v-model="preferences.coordinator_bootstrap.roles" type="checkbox" :value="item.id" /><span>{{ item.name }}</span></label>
        </fieldset>
        <div class="switches" role="group" aria-label="Workspace and memory setup">
          <ToggleSwitch v-model="preferences.coordinator_bootstrap.shared_project_memory" label="Shared project memory" hint="A notes folder every project may read." />
          <ToggleSwitch v-model="preferences.coordinator_bootstrap.project_workspaces" label="Project workspaces" hint="Projects get their own folders in the managed project area." />
        </div>
      </template>
      <label class="row bootstrap-model"><span class="name">Security review</span><AppSelect v-model="preferences.coordinator_bootstrap.security_review" aria-label="Security review policy"><option value="risk_based">Include for security-sensitive or high-risk work</option><option value="every_project">Include in every project</option><option value="by_request">Include when I request it</option></AppSelect></label>
      <h3 class="sub">Hermes, the Coordinator</h3>
      <ul v-if="bootstrapReadiness" class="readiness-list" aria-label="Hermes readiness">
        <li v-for="check in bootstrapReadiness.checks" :key="check.id" :class="check.ready ? 'ready' : 'missing'">
          <span aria-hidden="true">{{ check.ready ? '✓' : '!' }}</span><span>{{ check.label }}</span><RouterLink v-if="!check.ready" :to="check.link">{{ check.id === 'guidance' ? 'Open Agent roles' : 'Fix' }}</RouterLink>
        </li>
      </ul>
      <CoordinatorSetupPanel :hermes-ready="!!bootstrapReadiness?.ready" :persist="persistPreferences" />
      <div class="actions"><button class="btn" :disabled="busy">Save coordinator setup</button><button class="btn" type="button" :disabled="busy" @click="refreshCoordinatorReadiness">Recheck Hermes</button><RouterLink to="/agents" class="btn">Review installed agents</RouterLink></div>
    </form>
  </section>
</template>

<style scoped>
.page-head { display:flex; align-items:center; justify-content:space-between; gap:var(--gap); flex-wrap:wrap; }
.tabs { display:flex; gap:var(--gap-xs); flex-wrap:nowrap; overflow-x:auto; margin:var(--gap) 0; border-bottom:1px solid var(--surface-border); }
.tab { white-space:nowrap; padding:var(--gap-sm) var(--gap); border:0; border-bottom:2px solid transparent; background:none; color:var(--text-muted); font:inherit; cursor:pointer; }
.tab.on { color:var(--text); border-bottom-color:var(--accent); font-weight:var(--font-weight-strong); }
.group { display:grid; gap:var(--gap-lg); margin-top:var(--gap); } .group > :deep(.card), .group > :deep(section) { margin:0; }
.profile-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.2fr); gap:var(--gap-lg); align-items:start; margin-top:var(--gap-lg); }
.profile-stack { display:grid; gap:var(--gap-lg); min-width:0; } .card { background:var(--agent-glass); min-width:0; display:grid; gap:var(--gap); align-content:start; }
.bootstrap-card { max-width:70rem; margin:var(--gap-lg) auto 0; }
.bootstrap-card .card-head { justify-content:space-between; }
.bootstrap-card .card-head p { margin:var(--gap-xs) 0 0; }
.choice-group { display:flex; flex-wrap:wrap; gap:var(--gap-sm) var(--gap); border:1px solid var(--surface-border); border-radius:var(--radius); padding:var(--gap); margin:0; }
.choice-group legend { color:var(--text); font-weight:var(--font-weight-strong); padding:0 var(--gap-xs); }
.choice-group p { flex-basis:100%; margin:0; }
.choice { display:flex; align-items:center; gap:var(--gap-xs); color:var(--text); }
.choice input { accent-color:var(--accent); }
.bootstrap-model { max-width:42rem; }
.mode-group { display:grid; }
.mode { display:flex; align-items:flex-start; gap:var(--gap-sm); color:var(--text); }
.mode input { margin-top:0.3rem; accent-color:var(--accent); }
.mode > span { display:grid; gap:var(--gap-xs); }
.sub { margin:var(--gap-xs) 0 0; font-size:var(--font-size-base); }
.readiness-list { display:grid; gap:var(--gap-xs); list-style:none; padding:0; margin:0; }
.readiness-list li { display:flex; align-items:center; gap:var(--gap-sm); border:1px solid var(--surface-border); border-radius:var(--radius); padding:var(--gap-sm) var(--gap); }
.readiness-list li span:first-child { font-weight:var(--font-weight-strong); }
.readiness-list .ready span:first-child { color:var(--ok); }
.readiness-list .missing span:first-child { color:var(--warning, #d99a22); }
.readiness-list a { margin-left:auto; }
h2 { font-size:var(--font-size-lg); margin:0; }
.card-head { display:flex; align-items:center; flex-wrap:wrap; gap:var(--gap-sm); } .card-head h2 { flex:1 1 auto; }
.owner { overflow-wrap:anywhere; } .small { font-size:var(--font-size-xs); }
.row { display:grid; grid-template-columns:minmax(6rem,9rem) minmax(0,1fr); align-items:center; gap:var(--gap-sm); margin:0; color:var(--text-muted); font-size:var(--font-size-sm); }
.row.stack { grid-template-columns:minmax(0,1fr); } .name { color:var(--text-muted); }
.pair { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:var(--gap-sm); }
.seg { display:inline-flex; max-width:100%; border:1px solid var(--surface-border); border-radius:var(--radius-pill); overflow:hidden; justify-self:start; }
.seg-btn { padding:var(--gap-xs) var(--gap-sm); border:0; background:none; color:var(--text-muted); font:inherit; font-size:var(--font-size-sm); cursor:pointer; }
.seg-btn.on { background:var(--accent-soft); color:var(--accent); font-weight:var(--font-weight-strong); }
.pill { padding:0 var(--gap-sm); border:1px solid var(--surface-border); border-radius:var(--radius-pill); font-size:var(--font-size-xs); color:var(--text-muted); }
.pill.good { color:var(--ok); border-color:var(--ok); background:var(--ok-soft); }
.switches { display:grid; grid-template-columns:repeat(auto-fit,minmax(12rem,1fr)); gap:var(--gap-sm) var(--gap); padding:var(--gap-sm) 0; }
.actions { display:flex; align-items:center; flex-wrap:wrap; gap:var(--gap-sm); }
.perms summary { cursor:pointer; color:var(--text-muted); font-size:var(--font-size-sm); }
.pairing,.spending { padding:var(--gap); border:1px solid var(--surface-border); border-radius:var(--radius); overflow-wrap:anywhere; }
.credential { display:grid; gap:var(--gap-xs); border-top:1px solid var(--surface-border); padding-top:var(--gap-sm); }
.credential p, .share p { margin:0; }
.cred-head { display:flex; align-items:center; flex-wrap:wrap; gap:var(--gap-sm); } .cred-head .pill { margin-left:auto; }
.cred-row { display:flex; align-items:center; flex-wrap:wrap; gap:var(--gap-sm); } .cred-row .input { flex:1 1 12rem; min-width:0; }
.share { display:grid; gap:var(--gap-sm); border-top:1px solid var(--surface-border); padding-top:var(--gap-sm); justify-items:start; }
.import { position:relative; margin:0; cursor:pointer; } .import input { position:absolute; inset:0; opacity:0; width:100%; cursor:pointer; }
@media(max-width:900px) { .profile-grid { grid-template-columns:minmax(0,1fr); } .row { grid-template-columns:minmax(0,1fr); } .pair { grid-template-columns:minmax(0,1fr); } }
</style>
