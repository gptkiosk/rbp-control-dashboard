<script setup lang="ts">
import RolesPanel from '@/components/RolesPanel.vue'
import ReportStoragePanel from '@/components/ReportStoragePanel.vue'
import GithubSettingsPanel from '@/components/GithubSettingsPanel.vue'
import UpdatePanel from '@/components/UpdatePanel.vue'
import HousekeepingPanel from '@/components/HousekeepingPanel.vue'
import AgentToolsPanel from '@/components/AgentToolsPanel.vue'
import BugIntakePanel from '@/components/BugIntakePanel.vue'
import { onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import AppSelect from '@/components/AppSelect.vue'
import PlanningBiasSlider from '@/components/PlanningBiasSlider.vue'
import { getJson, putJson, postJson, deleteJson } from '@/lib/api'
import type { Profile, Preferences } from '@/lib/profile'
import { directoryName, directoryDetail } from '@/lib/selectLabels'
import { useThemeStore } from '@/stores/theme'
const profile = ref<Profile | null>(null), preferences = ref<Preferences | null>(null)
const workdirs = ref<{ path: string; branch: string | null }[]>([]), origins = ref<string[]>([])
const error = ref(''), notice = ref(''), busy = ref(false), pairing = ref('')
const secrets = ref<Record<string,string>>({ openrouter: '', discord: '' })
const spending = ref<Record<string, number | string | boolean | null> | null>(null)
const theme = useThemeStore()
function apply(p: Profile) { profile.value = p; preferences.value = {ai_agent:'hermes',ai_model:'openrouter/free',...structuredClone(p.preferences)} }
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch(e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
onMounted(() => { void action(async () => {
  const p = await getJson<Profile>('/api/profile'); apply(p); origins.value = p.origins ?? []
  if (preferences.value && !preferences.value.discord_channel_id) preferences.value.discord_channel_id = p.suggested_discord_channel ?? ''
  workdirs.value = (await getJson<{ workdirs: typeof workdirs.value }>('/api/workdirs')).workdirs
}) })
async function save() { await action(async () => {
  apply(await putJson<Profile>('/api/profile', preferences.value)); theme.choose(profile.value!.preferences.theme)
  notice.value = 'Profile saved. New projects use these defaults.'
}) }
async function saveKey(provider: string) { await action(async () => {
  const key = secrets.value[provider]
  if (!key) return
  try { profile.value = await putJson<Profile>(`/api/profile/credentials/${provider}`, { value: key }) }
  finally { secrets.value[provider] = '' }
  notice.value = 'Credential saved privately. Its value cannot be read back.'
}) }
async function removeKey(provider: string) { await action(async () => {
  profile.value = await deleteJson<Profile>(`/api/profile/credentials/${provider}`); spending.value = null; notice.value = 'Credential removed.'
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
  preferences.value = { ...data.preferences, setup: profile.value!.preferences.setup, use_saved_openrouter_key: profile.value!.preferences.use_saved_openrouter_key }; notice.value = 'Preferences loaded for review. Save to apply; Discord will need pairing on a new installation.'
}) }
</script>

<template>
  <section aria-labelledby="profile-title">
    <h1 id="profile-title" class="page-title has-icon"><AppIcon name="agents" size="lg" />Your profile</h1>
    <p class="muted">Planning defaults, your Discord connection and private provider credentials.</p>
    <RouterLink to="/setup" class="btn">Open setup wizard</RouterLink>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p><p v-if="notice" class="card" role="status">{{ notice }}</p>
    <ReportStoragePanel />
    <UpdatePanel />
    <HousekeepingPanel />
    <BugIntakePanel />
    <AgentToolsPanel />
    <RolesPanel />
    <GithubSettingsPanel id="github-settings" />
    <div v-if="profile && preferences" class="profile-grid">
      <form class="card preferences" @submit.prevent="save">
        <h2>Preferences</h2><p class="muted owner">{{ profile.owner }}</p>
        <label>Appearance<AppSelect v-model="preferences.theme" aria-label="Profile appearance"><option value="system">Follow device</option><option value="light">Light</option><option value="dark">Dark</option></AppSelect></label>
        <label>Default working directory<AppSelect v-model="preferences.working_dir" aria-label="Default working directory"><option value="">Use first allowed workspace</option><option v-for="w in workdirs" :key="w.path" :value="w.path" :data-description="directoryDetail(w.path,w.branch)">{{ directoryName(w.path) }}</option></AppSelect></label>
        <section id="ai-settings"><h3>AI defaults</h3><p>New consultant chats, agent chats, task forms and project planning start with Hermes on OpenRouter’s free router. Change these defaults to use your installed membership CLI or a reviewed API model. Existing conversations and approved projects keep their selected routes.</p><label>Default AI agent<AppSelect v-model="preferences.ai_agent" aria-label="Default AI agent"><option value="hermes">Hermes · OpenRouter</option><option value="openclaw">OpenClaw · OpenRouter</option><option value="claude">Claude Code · native membership</option><option value="codex">Codex · native membership</option><option value="grok">Grok Build · native membership</option></AppSelect></label><label>Default AI model<input v-model="preferences.ai_model" class="input" maxlength="200" required placeholder="openrouter/free" /></label><p class="muted">Choose a model supported by the selected CLI. Memberships require native sign-in; OpenRouter/API keys do not use membership allowances. Free routes can throttle or fail; this preference never authorizes paid fallback. Model-policy checks and existing approvals still apply.</p><RouterLink to="/help?topic=project-consultant">AI defaults and consultant help</RouterLink></section><PlanningBiasSlider v-model="preferences.planning_bias" />
        <div class="actions"><button class="btn primary" :disabled="busy">Save preferences</button><button type="button" class="btn" @click="exportPreferences">Export preferences</button><label class="btn import">Import preferences<input type="file" accept="application/json" @change="importPreferences" /></label></div>
        <p class="muted small">Exports contain settings only. Credentials, encryption keys, Discord pairing and setup confirmations are excluded. Workspace paths and the dashboard address must match the destination installation.</p>
      </form>
      <div class="profile-stack">
        <section id="discord-profile" class="card" aria-labelledby="discord-title"><h2 id="discord-title">Hermes on Discord</h2>
          <p>{{ profile.discord_linked ? 'Linked to your Discord identity' : 'Pair once to create and edit your projects through Hermes.' }}</p>
          <label>Discord channel ID<input v-model="preferences.discord_channel_id" class="input" inputmode="numeric" autocomplete="off" maxlength="22" /></label>
          <label>Dashboard address for project links<AppSelect v-model="preferences.dashboard_origin" aria-label="Dashboard address"><option value="">Installation default</option><option v-for="o in origins" :key="o" :value="o">{{ o }}</option></AppSelect></label>
          <label class="check"><input v-model="preferences.notify_plans" type="checkbox" />Notify me when a plan is ready or planning stops.</label>
          <label class="check"><input v-model="preferences.allow_discord_planning" type="checkbox" />Allow my Discord requests to start subscription planning with Hermes coordination.</label>
          <label class="check"><input v-model="preferences.allow_discord_control" type="checkbox" />Allow my Discord requests to change how work is routed, such as sending waiting stories to the other subscription while a limit lasts. Approvals, dispatch, billing and credentials stay in RCD.</label>
          <label class="check"><input v-model="preferences.allow_discord_diagnostics" type="checkbox" />Allow Hermes to read failed runs for me in Discord: errors, short handoff excerpts and log tails, with credentials and addresses removed. Read only.</label>
          <label class="check"><input v-model="preferences.allow_discord_standards" type="checkbox" />Allow Hermes to read a project's standards in Discord and propose additions to the repository's standards file. It cannot change or remove anything: you approve on the project page, and approval only creates a new branch to review.</label>
          <label class="check"><input v-model="preferences.allow_discord_maintenance" type="checkbox" />Allow Hermes to read Housekeeping findings in Discord and propose fixes. It cannot change anything: you approve in Profile.</label>
          <p class="muted small">Hermes uses its configured OpenRouter route, including capped Google BYOK fallback. This permission covers planning when you ask. Paid API planners and story execution require separate review in RCD.</p>
          <div class="actions"><button class="btn" :disabled="busy" @click="save">Save connection</button><button class="btn primary" :disabled="busy || !preferences.discord_channel_id" @click="pair">{{ profile.discord_linked ? 'Pair again' : 'Get pairing code' }}</button><button class="btn" :disabled="busy" @click="refresh">Check pairing</button><button v-if="profile.discord_linked" class="btn" :disabled="busy" @click="unlink">Unlink Discord</button></div>
          <div v-if="pairing" class="pairing" role="status"><strong>Send to Hermes in this channel within 10 minutes:</strong><p>{{ pairing }}</p><small>Treat the code as private. Then choose Check pairing.</small></div>
          <p class="muted small">Ask Hermes to plan a project. It collects missing information, uses your preference and posts an editable map. It asks whether you need a diagram before sending an image.</p>
        </section>
        <section id="credentials-profile" class="card" aria-labelledby="credentials-title"><h2 id="credentials-title">Private credentials</h2>
          <p class="muted small">Write-only values are encrypted in your local profile. They stay out of browser storage, source code, exports and agent prompts.</p>
          <div v-for="provider in ['openrouter','discord']" :key="provider" class="credential">
            <label>{{ provider === 'openrouter' ? 'OpenRouter key' : 'Discord bot token (optional)' }}<input v-model="secrets[provider]" class="input" type="password" autocomplete="new-password" :aria-label="provider + ' credential'" placeholder="Enter a new credential" /></label>
            <p class="muted small">{{ provider === 'openrouter' ? 'Read actual spending for this key. Agents keep their own configured routing and caps unless you share this key with Hermes and OpenClaw below.' : 'Use your own bot for project notifications, or leave empty to use this installation’s Hermes bot.' }}</p>
            <div class="actions"><span v-if="profile.credentials.find(c => c.provider === provider)">Saved ····{{ profile.credentials.find(c => c.provider === provider)?.hint }}</span><button class="btn" :disabled="busy || !secrets[provider]" @click="saveKey(provider)">Save credential</button><button v-if="profile.credentials.find(c => c.provider === provider)" class="btn" :disabled="busy" @click="removeKey(provider)">Remove</button></div>
          </div>
          <div v-if="profile.credentials.some(c => c.provider === 'openrouter')" class="share">
            <label class="check"><input type="checkbox" data-testid="share-key" :checked="!!profile.preferences.use_saved_openrouter_key" :disabled="busy" @change="shareKey(($event.target as HTMLInputElement).checked)" />Let Hermes and OpenClaw use this saved key</label>
            <p class="muted small">Off by default. When on, Hermes and OpenClaw runs receive this key as OPENROUTER_API_KEY, even if they have their own, and it is removed from anything they print. Claude, Codex and Grok never receive it, and paid models still follow your dispatch policy. An agent can read its own environment, so use a dedicated key with a credit limit set at OpenRouter. Turning this off, or removing the key, stops it at once.</p>
          </div>
          <button v-if="profile.credentials.some(c => c.provider === 'openrouter')" class="btn" :disabled="busy" @click="checkSpending">Check key spending</button>
          <div v-if="spending" class="spending" role="status"><p>API usage this month: ${{ spending.month_usd ?? 'not reported' }}</p><p>BYOK usage this month: ${{ spending.byok_month_usd ?? 'not reported' }}</p><p>Key limit: ${{ spending.limit_usd ?? 'not set' }} · {{ spending.limit_reset ?? 'no reset' }}</p></div>
          <p class="muted small">Claude/Codex remain signed into their host subscriptions. Google OAuth and gateway credentials belong in private installation configuration, never a distribution package. Back up the private vault key alongside the database to recover encrypted profile credentials.</p>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.profile-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.2fr); gap:var(--gap-lg); align-items:start; margin-top:var(--gap-lg); }
.profile-stack { display:grid; gap:var(--gap-lg); min-width:0; } .card { background:var(--agent-glass); min-width:0; }
h2 { font-size:var(--font-size-lg); margin:0 0 var(--gap); } label { display:grid; gap:var(--gap-sm); margin-top:var(--gap); color:var(--text-muted); font-size:var(--font-size-sm); }
.check { display:flex; align-items:flex-start; } .check input { accent-color:var(--accent); margin-top:var(--gap-xs); flex-shrink:0; }
.actions { display:flex; align-items:center; flex-wrap:wrap; gap:var(--gap-sm); margin-top:var(--gap); } .small { font-size:var(--font-size-xs); line-height:var(--line-height); }
.pairing,.spending { padding:var(--gap); border:1px solid var(--surface-border); border-radius:var(--radius); margin-top:var(--gap); overflow-wrap:anywhere; }
.credential { border-top:1px solid var(--surface-border); margin:var(--gap) 0; padding-top:var(--gap-sm); } .owner { overflow-wrap:anywhere; }
.import { position:relative; margin:0; cursor:pointer; } .import input { position:absolute; inset:0; opacity:0; width:100%; cursor:pointer; }
@media(max-width:900px) { .profile-grid { grid-template-columns:minmax(0,1fr); } }
</style>
