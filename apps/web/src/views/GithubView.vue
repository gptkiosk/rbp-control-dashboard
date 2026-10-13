<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import AppSelect from '@/components/AppSelect.vue'
import GithubWorkList from '@/components/GithubWorkList.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import { dateLabel, type Repositories, type RepositoryDetails } from '@/lib/operations'

const { data, error, loaded, refresh } = usePolledJson<Repositories>('/api/github/repos', 60000)
const search = ref('')
const selected = ref('')
const repos = computed(() => data.value?.repos ?? [])
// Optional setup states come from local configuration; they are guidance, not failures.
const setup = computed(() => data.value?.setup && data.value.setup.state !== 'ready' ? data.value.setup : null)
const setupText = computed(() => ({ migration_required: 'GitHub is optional and has not been set up on this installation. Nothing is checked in the background until you turn it on.', disabled: 'GitHub is turned off. Nothing is checked in the background.', unconfigured: 'GitHub is on but still needs an account and at least one repository.', configuration_error: 'The saved GitHub settings could not be read. An operator needs to review them in Settings.', ready: '' })[setup.value?.state ?? 'ready'])
const filtered = computed(() => repos.value.filter(r => `${r.name} ${r.description ?? ''}`.toLowerCase().includes(search.value.toLowerCase())))
watch(repos, list => { if (!list.some(r => r.name === selected.value)) selected.value = list[0]?.name ?? '' })
const current = computed(() => repos.value.find(r => r.name === selected.value))
// The empty catalog path avoids making a details request before a repository is selected.
const detailsPath = computed(() => selected.value ? `/api/github/repos/${selected.value}` : '/api/github/repos')
const { data: rawDetails, error: detailError, loaded: detailsLoaded, refresh: refreshDetails } = usePolledJson<RepositoryDetails | Repositories>(detailsPath, 60000)
const details = computed(() => rawDetails.value && 'pulls' in rawDetails.value ? rawDetails.value : null)
function refreshAll() { refresh(); if (selected.value) refreshDetails() }
</script>
<template>
  <section aria-labelledby="github-title">
    <div class="page-header"><h1 id="github-title" class="page-title has-icon"><AppIcon name="github" size="lg" />GitHub</h1><button class="btn" @click="refreshAll">Refresh</button></div>
    <p class="muted">Repositories and open work from your existing GitHub login, for the repositories you choose.</p>
    <p v-if="error || (data?.error && !setup)" role="status" class="notice-warn">{{ error || data?.error }}<span v-if="repos.length"> Showing the last successful catalog.</span></p>
    <p v-if="!loaded" class="muted" role="status">Loading repositories…</p>
    <div v-else-if="setup" class="card setup-card" role="status"><h2>Set up GitHub (optional)</h2><p>{{ setupText }}</p><p class="muted">Choose an account that is already signed in with <code>gh</code> on the host and the repositories to show. A token is never requested or stored here.</p><RouterLink class="btn primary" to="/profile#github-settings">Open GitHub settings</RouterLink><p class="muted small-note">Your public profile’s contribution graph is a separate GitHub setting: Profile &gt; Contribution settings &gt; Private contributions.</p></div>
    <div v-else-if="!repos.length" class="card"><h2>No repositories available</h2><p class="muted">{{ data?.error ? 'Restore the existing gh login or repository access, then refresh.' : 'No repositories are accessible to the current GitHub account.' }}</p></div>
    <template v-else>
      <div class="repository-controls card">
        <label>Find a repository<input v-model="search" class="input" type="search" placeholder="Search name or description" /></label>
        <label>Repository<AppSelect v-model="selected" aria-label="Repository"><option v-for="r in repos" :key="r.name" :value="r.name" :data-description="r.archived ? 'Archived' : r.private ? 'Private repository' : 'Public repository'">{{ r.name }}</option></AppSelect></label>
        <p class="muted">{{ repos.length }} repositories · {{ dateLabel(data?.checked_at ?? null) }}<span v-if="data?.limited"> · First 100 repositories</span></p>
      </div>
      <div class="repo-catalog" aria-label="Repositories">
        <button v-for="r in filtered" :key="r.name" class="card repo-card" :class="{ selected: r.name === selected }" :aria-pressed="r.name === selected" @click="selected = r.name">
          <strong>{{ r.name }}</strong><span class="muted">{{ r.description || 'No description' }}</span><small class="muted">{{ r.private ? 'Private' : 'Public' }} · {{ r.archived ? 'Archived' : r.branch }}</small>
        </button>
      </div>
      <p v-if="!filtered.length" class="muted">No repositories match this search.</p>
      <section v-if="current" class="repository-detail" :aria-label="current.name">
        <div class="detail-heading"><h2>{{ current.name }}</h2><a :href="current.url" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Open on GitHub ↗</a></div>
        <p v-if="detailError" role="status" class="notice-warn">{{ detailError }}</p>
        <p v-if="!detailsLoaded || !details" class="muted" role="status">{{ detailError ? 'Repository work is unavailable.' : 'Loading open work…' }}</p>
        <div v-if="details" class="work-grid"><GithubWorkList title="Pull requests" :stream="details.pulls" /><GithubWorkList title="Issues" :stream="details.issues" /></div>
      </section>
    </template>
  </section>
</template>
<style scoped>
.page-header, .detail-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--gap); }
.repository-controls { display: grid; grid-template-columns: 1fr 1fr; gap: var(--gap); margin: var(--gap-lg) 0; }
label { display: grid; gap: var(--gap-sm); min-width: 0; color: var(--text-muted); }
.repository-controls p { grid-column: 1 / -1; margin: 0; font-size: var(--font-size-xs); }
.repo-catalog { max-height: 340px; overflow-y: auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr)); gap: var(--gap); }
.repo-card { text-align: left; display: flex; flex-direction: column; gap: var(--gap-sm); cursor: pointer; color: var(--text); font: inherit; overflow-wrap: anywhere; }
.repo-card.selected { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.repo-card:hover { border-color: var(--accent); }
.repo-card span { font-size: var(--font-size-sm); }
.setup-card { display: grid; gap: var(--gap); justify-items: start; }
.small-note { font-size: var(--font-size-xs); margin: 0; }
.repository-detail { margin-top: var(--gap-lg); }
.detail-heading h2 { font-size: var(--font-size-lg); overflow-wrap: anywhere; min-width: 0; }
.work-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--gap); }
@media (max-width: 760px) { .repository-controls, .work-grid { grid-template-columns: 1fr; } .repo-catalog { max-height: 220px; } }
</style>
