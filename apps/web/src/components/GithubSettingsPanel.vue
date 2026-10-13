<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, getJson, postJson, putJson } from '@/lib/api'
import type { Profile } from '@/lib/profile'
interface GithubStatus {
  state: 'migration_required' | 'configuration_error' | 'disabled' | 'unconfigured' | 'ready'
  configured: boolean; enabled?: boolean; account?: string; repos?: string[]; public_only?: boolean; poll_seconds?: number
  message?: string; error?: string
}
interface Login { available: boolean; account: string }
const props = defineProps<{ wizard?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const SLUG = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/, LOGIN = /^[A-Za-z0-9-]{1,39}$/
const cadences = [[300, 'Every 5 minutes'], [900, 'Every 15 minutes (recommended)'], [1800, 'Every 30 minutes'], [3600, 'Every hour'], [21600, 'Every 6 hours'], [86400, 'Once a day']] as const
const status = ref<GithubStatus | null>(null), login = ref<Login | null>(null)
const enabled = ref(true), account = ref(''), selected = ref<string[]>([]), publicOnly = ref(false), poll = ref(900)
const mine = ref<string[]>([]), minePublic = ref(false), personal = ref<Profile | null>(null)
const busy = ref(false), error = ref(''), notice = ref(''), forbidden = ref(false)
interface RepoChoice { name: string; private: boolean; archived: boolean; description: string | null; updated_at: string | null }
const choices = ref<RepoChoice[]>([]), listState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle'), listError = ref(''), listLimited = ref(false)
const filter = ref(''), extra = ref(''), extraError = ref('')
let timer: number | undefined, listSeq = 0
const repos = computed(() => selected.value)
const known = computed(() => new Set(choices.value.map(c => c.name)))
// Saved or added by hand but not in this account's list (another owner, or a name GitHub no longer shows).
const unlisted = computed(() => selected.value.filter(r => !known.value.has(r)))
const shown = computed(() => {
  const q = filter.value.trim().toLowerCase()
  return choices.value.filter(c => !q || c.name.toLowerCase().includes(q) || (c.description ?? '').toLowerCase().includes(q))
})
const hostRepos = computed(() => status.value?.repos ?? [])
const problem = computed(() => {
  if (!enabled.value) return ''
  if (!LOGIN.test(account.value.trim())) return 'Enter the GitHub account name of your existing gh login.'
  if (!repos.value.length) return 'Choose at least one repository.'
  if (repos.value.length > 100) return 'Choose at most 100 repositories.'
  const bad = repos.value.find(r => !SLUG.test(r))
  return bad ? `“${bad.slice(0, 60)}” is not in owner/name form.` : ''
})
const summary = computed(() => {
  const s = status.value
  if (!s) return ''
  if (s.state === 'ready') return `Enabled for ${s.account} · ${s.repos?.length ?? 0} repositories · ${s.public_only ? 'public only · ' : ''}checked every ${Math.round((s.poll_seconds ?? 900) / 60)} minutes.`
  if (s.state === 'disabled') return 'GitHub is turned off. Nothing is checked in the background.'
  if (s.state === 'unconfigured') return 'GitHub is on but needs an account and repository list.'
  if (s.state === 'configuration_error') return s.error ?? 'Saved GitHub settings need operator review.'
  return 'GitHub is optional and not set up yet. Nothing is checked in the background.'
})
function fill(s: GithubStatus) {
  status.value = s
  if (s.state === 'ready' || s.state === 'disabled' || s.state === 'unconfigured') {
    enabled.value = s.state !== 'disabled'; account.value = s.account ?? ''; selected.value = [...(s.repos ?? [])]
    publicOnly.value = !!s.public_only; poll.value = s.poll_seconds ?? 900
  }
}
function denied(e: unknown, fallback: string) {
  forbidden.value = e instanceof ApiError && (e.status === 401 || e.status === 403)
  return forbidden.value ? 'Operator sign-in is required to change host GitHub settings.' : e instanceof Error ? e.message : fallback
}
async function loadChoices() {
  const owner = account.value.trim()
  if (!enabled.value || !LOGIN.test(owner)) { listState.value = 'idle'; return }
  const mine = ++listSeq
  listState.value = 'loading'; listError.value = ''
  try {
    const r = await getJson<{ repos: RepoChoice[]; limited: boolean }>(`/api/github/account-repos?owner=${encodeURIComponent(owner)}`)
    if (mine !== listSeq) return
    choices.value = r.repos; listLimited.value = r.limited; listState.value = 'ready'
  } catch (e) {
    if (mine !== listSeq) return
    choices.value = []; listState.value = 'error'; listError.value = denied(e, 'The repository list could not be loaded.')
  }
}
// Typing waits for a pause; leaving the field or pressing Enter loads at once.
function accountTyped() { window.clearTimeout(timer); choices.value = []; listState.value = 'idle'; if (LOGIN.test(account.value.trim())) timer = window.setTimeout(loadChoices, 600) }
function accountDone() { window.clearTimeout(timer); void loadChoices() }
function addExtra() {
  const name = extra.value.trim()
  extraError.value = ''
  if (!SLUG.test(name)) { extraError.value = 'Use the owner/name form, for example owner/repository.'; return }
  if (!selected.value.includes(name)) selected.value = [...selected.value, name]
  extra.value = ''
}
function chooseShown() { selected.value = [...new Set([...selected.value, ...shown.value.map(c => c.name)])] }
function clearAll() { selected.value = [] }
onBeforeUnmount(() => window.clearTimeout(timer))
watch(enabled, on => { if (on) void loadChoices() })
async function load() {
  try { fill(await getJson<GithubStatus>('/api/github/status')); void loadChoices() } catch { error.value = 'GitHub settings are unavailable right now.' }
  if (!props.wizard) {
    try { personal.value = await getJson<Profile>('/api/profile'); const g = (personal.value.preferences as unknown as { github?: { repos: string[]; public_only: boolean } }).github; mine.value = g?.repos ?? []; minePublic.value = !!g?.public_only } catch { personal.value = null }
  }
}
async function save(turnOff = false) {
  if (!turnOff && problem.value) { error.value = problem.value; return }
  busy.value = true; error.value = ''; notice.value = ''
  const migrating = status.value?.state === 'migration_required'
  const body = { version: 1, enabled: !turnOff && enabled.value, account: account.value.trim(), repos: repos.value, public_only: publicOnly.value, poll_seconds: poll.value }
  try {
    const result = migrating
      ? await postJson<GithubStatus & { login?: Login }>('/api/github/migrate', body)
      : await putJson<GithubStatus & { login?: Login }>('/api/github/config', body)
    login.value = result.login ?? null; fill(result)
    notice.value = body.enabled ? 'GitHub settings saved. The first check runs shortly.' : 'GitHub is turned off. No background checks will run.'
    emit('changed')
  } catch (e) { error.value = denied(e, 'GitHub settings could not be saved.') }
  finally { busy.value = false }
}
async function refresh() {
  busy.value = true; error.value = ''; notice.value = ''
  try { await postJson('/api/github/refresh'); notice.value = 'Refresh requested. Checks are rate limited to one every 30 seconds.'; emit('changed') }
  catch (e) { error.value = denied(e, 'GitHub could not be refreshed.') }
  finally { busy.value = false }
}
async function savePersonal() {
  if (!personal.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const next = await putJson<Profile>('/api/profile', { ...personal.value.preferences, github: { repos: mine.value, public_only: minePublic.value } })
    personal.value = next; notice.value = 'Your GitHub view was saved. It can only narrow what the host allows.'; emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : 'Your GitHub view could not be saved.' }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <component :is="wizard ? 'div' : 'details'" class="card github-panel" :open="wizard ? undefined : status?.state !== 'ready' ? true : undefined">
    <component :is="wizard ? 'h3' : 'summary'">GitHub (optional) · repositories, pull requests and issues</component>
    <p class="status" role="status">{{ summary }}</p>
    <p class="muted">Turn this on only if you want this dashboard to show open pull requests and issues. While it is off or unfinished, no background GitHub calls are made. Settings here apply to everyone using this installation; changes need operator sign-in.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="login" class="muted" role="status">{{ login.available ? `Active gh login: ${login.account}.` : 'No active gh login was detected on the host. Sign in there with “gh auth login”, then refresh.' }}</p>
    <form v-if="status && status.state !== 'configuration_error'" @submit.prevent="save()">
      <label class="check"><input v-model="enabled" type="checkbox" />Enable GitHub</label>
      <template v-if="enabled">
        <label>GitHub account<input v-model="account" class="input" autocomplete="off" spellcheck="false" placeholder="your-github-login" @input="accountTyped" @blur="accountDone" @keydown.enter.prevent="accountDone" /></label>
        <p class="muted small">The account must be the one already signed in with <code>gh</code> on the host. The dashboard uses that existing login and never asks for, reads or stores a token.</p>
        <fieldset class="repo-list" :aria-busy="listState === 'loading'">
          <legend>Repositories to show</legend>
          <p v-if="listState === 'idle' && !selected.length" class="muted small">Enter the account above and its repositories appear here to tick.</p>
          <p v-else-if="listState === 'loading'" class="muted small" role="status">Loading repositories for {{ account.trim() }}…</p>
          <p v-else-if="listState === 'error'" class="notice-warn small" role="alert">{{ listError }} You can still add a repository by name below.</p>
          <template v-if="choices.length || unlisted.length">
            <div class="list-tools">
              <input v-if="choices.length > 8" v-model="filter" class="input" type="search" placeholder="Find a repository" aria-label="Find a repository" />
              <button v-if="choices.length" type="button" class="btn" @click="chooseShown">{{ filter.trim() ? 'Select shown' : 'Select all' }}</button>
              <button type="button" class="btn" :disabled="!selected.length" @click="clearAll">Clear</button>
            </div>
            <label v-for="c in shown" :key="c.name" class="check"><input v-model="selected" type="checkbox" :value="c.name" />
              <span>{{ c.name }}<small v-if="c.private" class="tag">private</small><small v-if="c.archived" class="tag">archived</small><span v-if="c.description" class="muted small desc"> {{ c.description }}</span></span></label>
            <p v-if="choices.length && !shown.length" class="muted small">No repository matches this search.</p>
            <label v-for="r in unlisted" :key="r" class="check unlisted"><input v-model="selected" type="checkbox" :value="r" />
              <span>{{ r }}<small class="tag">not in {{ account.trim() || 'this' }}’s list</small></span></label>
          </template>
          <p v-if="listLimited" class="muted small">Showing the newest 100 repositories. Add any other by name below.</p>
          <p class="muted small">{{ selected.length }} selected. Only these repositories are read.</p>
        </fieldset>
        <details class="by-name">
          <summary class="small">Add a repository by name (another owner)</summary>
          <div class="add-row"><input v-model="extra" class="input" spellcheck="false" placeholder="owner/repository" aria-label="Repository name" @keydown.enter.prevent="addExtra" /><button type="button" class="btn" @click="addExtra">Add</button></div>
          <p v-if="extraError" class="notice-warn small" role="alert">{{ extraError }}</p>
        </details>
        <label class="check"><input v-model="publicOnly" type="checkbox" />Public repositories only</label>
        <label>How often to check<select v-model.number="poll" class="input"><option v-for="[v, l] in cadences" :key="v" :value="v">{{ l }}</option></select></label>
      </template>
      <p v-if="enabled && problem" class="muted small">{{ problem }}</p>
      <div class="actions">
        <button class="btn primary" :disabled="busy || forbidden">{{ status.state === 'migration_required' ? 'Save and migrate' : 'Save GitHub settings' }}</button>
        <button v-if="status.state === 'ready'" type="button" class="btn" :disabled="busy || forbidden" @click="save(true)">Turn off</button>
        <button v-if="status.state === 'ready'" type="button" class="btn" :disabled="busy || forbidden" @click="refresh">Refresh now</button>
      </div>
    </form>
    <section v-if="!wizard && status?.state === 'ready' && personal" class="personal" aria-label="Your GitHub view">
      <h3>Your view</h3>
      <p class="muted small">Optional and private to your profile. You can narrow the repositories you see; you cannot add any the host has not allowed.</p>
      <fieldset><legend class="small">Show only these (none selected = all allowed)</legend>
        <label v-for="r in hostRepos" :key="r" class="check"><input v-model="mine" type="checkbox" :value="r" />{{ r }}</label>
      </fieldset>
      <label class="check"><input v-model="minePublic" type="checkbox" />Hide private repositories from my view</label>
      <button type="button" class="btn" :disabled="busy" @click="savePersonal">Save my view</button>
    </section>
    <details class="help">
      <summary>What about my GitHub profile’s contribution graph?</summary>
      <p>Whether your contributions appear on your public GitHub profile is a separate GitHub account setting and is not controlled here. To include or hide private-repository activity, open GitHub: Profile &gt; Contribution settings &gt; Private contributions.</p>
      <p>Viewing repositories here is read-only. Posting issues, comments or pull requests, or merging, is never done without a separate, specifically reviewed authorization.</p>
    </details>
  </component>
</template>
<style scoped>
.github-panel { margin: var(--gap-lg) 0; display: grid; gap: var(--gap); }
summary { cursor: pointer; font-weight: 600; }
h3 { margin: 0; }
form { display: grid; gap: var(--gap-sm); }
label { display: grid; gap: var(--gap-sm); }
.check { display: flex; align-items: flex-start; gap: var(--gap-sm); }
.check input { flex: none; margin-top: var(--gap-xs); accent-color: var(--accent); }
.status { font-weight: 600; margin: 0; }
.small { font-size: var(--font-size-xs); margin: 0; }
.actions { display: flex; gap: var(--gap); flex-wrap: wrap; }
fieldset { display: grid; gap: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); padding: var(--gap); }
.repo-list { max-height: 22rem; overflow: auto; }
.list-tools { display: flex; gap: var(--gap-sm); flex-wrap: wrap; align-items: center; }
.list-tools .input { flex: 1 1 12rem; }
.tag { margin-left: var(--gap-xs); padding: 0 var(--gap-xs); border: 1px solid var(--surface-border); border-radius: var(--radius); color: var(--text-muted); font-size: var(--font-size-xs); }
.unlisted { opacity: 0.85; }
.desc { overflow-wrap: anywhere; }
.add-row { display: flex; gap: var(--gap-sm); margin-top: var(--gap-sm); }
.add-row .input { flex: 1; }
.personal { display: grid; gap: var(--gap-sm); }
code { overflow-wrap: anywhere; }
</style>
