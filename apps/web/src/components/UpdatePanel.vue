<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppSelect from '@/components/AppSelect.vue'
import { ApiError, getJson, postJson } from '@/lib/api'

// Only this product and repository are ever offered. The server enforces the same rule; this is a second check.
const PRODUCT = 'rcd'
const REPOSITORY = 'gptkiosk/rbp-control-dashboard'
const POLL_MS = 2000, MAX_POLLS = 150, NOT_STARTED_POLLS = 15 // about 5 minutes overall; 30 seconds before "never started"
const DOWNLOAD_POLLS = 300 // three assets can take up to 10 minutes; polling only reads status, it never starts anything

// Shapes of GET /api/app-updates/check, GET /api/app-updates and the release description the server returns.
interface Asset { kind: string; name: string; size: number }
interface Candidate {
  product: string; platform: string; repository: string; channel: string; tag: string; version: string
  change: string; prerelease: boolean; notes: string; html_url: string | null; published_at: string | null
  manifest_sha256: string | null; archive_sha256: string | null; assets: Asset[]; authenticity: string
}
interface CheckResponse { available: boolean; candidate: Candidate | null; installed: string | null }
interface Version { id: string; complete: boolean; version: string | null; channel: string | null; change: string | null; repository: string | null; authenticity: string | null; staged_at: number | null }
interface Last { tx: string | null; kind: string | null; outcome: string; detail: string; target: string | null; from: string | null; at: number }
interface Install { current: string | null; previous: string | null; versions: Version[]; tx: { id: string; kind: string; phase: string; target: string } | null; last: Last | null; needs_recovery: boolean }
interface UpdateStatus { kind: string; detail: string; configured: boolean; problems: string[]; manual_instructions: string[]; install?: Install; blockers?: string[] }
interface Pending { kind: 'install' | 'rollback'; version: Version }
interface Operation { kind: Pending['kind']; target: string; beforeTx: string | null; sawTx: boolean; polls: number }

const PHASES: Record<string, string> = {
  staging: 'Staging the package', prepared: 'Stopping the service and saving a data snapshot', switching: 'Switching versions',
  starting: 'Starting the service and checking its health', rolling_back: 'Health check failed; rolling back', restoring: 'Restoring the data snapshot',
}
const channel = ref('stable')
const pinnedManifestDigest = ref('')
const found = ref<CheckResponse | null>(null), checkedAt = ref<number | null>(null)
const status = ref<UpdateStatus | null>(null)
const pending = ref<Pending | null>(null), confirmed = ref(false)
const downloadAsk = ref(false), downloadConfirmed = ref(false), downloading = ref(false)
const operation = ref<Operation | null>(null), reconnecting = ref(false), busy = ref(false)
const error = ref(''), notice = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let alive = true

const install = computed(() => status.value?.install)
const managed = computed(() => !!status.value && status.value.kind === 'release' && status.value.configured && !!install.value)
const blockers = computed(() => status.value?.blockers ?? [])
const inProgress = computed(() => !!install.value?.tx || !!install.value?.needs_recovery || !!operation.value || downloading.value)
const canChange = computed(() => managed.value && !busy.value && !inProgress.value && blockers.value.length === 0)
const previous = computed(() => find(install.value?.previous))
const canRollback = computed(() => canChange.value && !!previous.value?.complete)
const others = computed(() => (install.value?.versions ?? []).filter(v => v.id !== install.value?.current))
const installable = computed(() => others.value.filter(v => !unavailable(v)))
const notOffered = computed(() => others.value.filter(v => unavailable(v)))
const summary = computed(() => {
  const s = status.value
  if (!s) return ''
  if (!managed.value && s.kind === 'release') return 'Managed updates are not set up on this host yet. Details are below.'
  if (!managed.value) return `Managed updates are off: ${s.detail}.`
  const n = installable.value.length
  return `Running ${label(install.value?.current)}. ${n} staged ${n === 1 ? 'update is' : 'updates are'} ready on this host.`
})
const progressText = computed(() => {
  const tx = install.value?.tx
  return tx ? PHASES[tx.phase] ?? 'Working' : 'Waiting for the update helper to start…'
})

const candidate = computed(() => found.value?.candidate ?? null)
const refused = computed(() => {
  const c = candidate.value
  if (!c) return ''
  if (c.product !== PRODUCT || c.repository !== REPOSITORY) return `This release is not ${PRODUCT} from ${REPOSITORY}, so it cannot be installed here.`
  return ''
})
const releaseLink = computed(() => {
  const url = candidate.value?.html_url
  return url && url.startsWith(`https://github.com/${REPOSITORY}/`) ? url : null
})

function find(id: string | null | undefined) { return install.value?.versions.find(v => v.id === id) }
function label(id: string | null | undefined) { return find(id)?.version ?? id ?? 'none' }
function when(seconds: number | null | undefined) { return seconds ? new Date(seconds * 1000).toLocaleString() : 'an unknown time' }
function stagedVersion(version: string) { return install.value?.versions.find(v => v.version === version && v.complete) ?? null }
// Only complete, stable or prerelease application packages from this repository are offered. Anything else says why and gets no button.
function unavailable(v: Version): string {
  if (!v.complete || !v.version) return 'It is only partly staged, so it cannot be installed.'
  if (v.channel === 'dev') return 'A development build. It is never offered as an update.'
  if (v.channel !== 'stable' && v.channel !== 'prerelease') return `Channel “${v.channel ?? 'unknown'}” is not an application release, so it is not installable.`
  if (v.repository !== REPOSITORY) return `It was built from ${v.repository ?? 'an unrecorded repository'}, not ${REPOSITORY}, so it is not installed here.`
  return ''
}
function denied(e: unknown, fallback: string) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return 'Operator sign-in is required to see or change updates.'
  return e instanceof Error ? e.message : fallback
}
// A refusal carries {message, blockers, problems}; the client flattens it into the message text, so unpack it when it is JSON.
function refusal(e: unknown, fallback: string) {
  if (e instanceof ApiError && e.status === 409) {
    try {
      const body = JSON.parse(e.message) as { message?: string; blockers?: string[]; problems?: string[] }
      return [body.message, ...(body.blockers ?? []), ...(body.problems ?? [])].filter(Boolean).join(' ')
    } catch { /* plain message */ }
  }
  if (e instanceof ApiError && e.status === 502) {
    try {
      const body = JSON.parse(e.message) as { message?: string; problems?: string[] }
      return [body.message, ...(body.problems ?? [])].filter(Boolean).join(' ')
    } catch { /* plain message */ }
  }
  return denied(e, fallback)
}

// Reads this host's install state only. It never contacts GitHub.
async function read(): Promise<boolean> {
  try {
    status.value = await getJson<UpdateStatus>('/api/app-updates')
    reconnecting.value = false; error.value = ''
    return true
  } catch (e) {
    // While an operation runs, a network error or 5xx usually means the service is restarting.
    reconnecting.value = !!operation.value && (!(e instanceof ApiError) || e.status >= 500)
    if (!reconnecting.value) error.value = denied(e, 'Updates could not be read right now.')
    return false
  }
}

// Read-only look at the public GitHub Releases API, sent only when the operator clicks. Nothing is downloaded or changed.
async function check() {
  if (busy.value || !!operation.value) return
  busy.value = true; error.value = ''; notice.value = ''; cancelDownload()
  try {
    const body = await getJson<CheckResponse>(`/api/app-updates/check?channel=${encodeURIComponent(channel.value)}`)
    found.value = body
    pinnedManifestDigest.value = ''
    checkedAt.value = Date.now()
    if (!body.available) notice.value = `No newer ${channel.value} release than the installed version.`
  } catch (e) {
    found.value = null
    error.value = refusal(e, 'Could not check for updates.')
  } finally { busy.value = false }
}

function askDownload() { downloadAsk.value = true; downloadConfirmed.value = false; error.value = ''; notice.value = '' }
function cancelDownload() { downloadAsk.value = false; downloadConfirmed.value = false }

// Step 1: the server downloads the three allowlisted assets, verifies them and stages them. Nothing is stopped.
// No digest is sent as a pin: GitHub's published digests come from the same API the release came from.
async function download() {
  const c = candidate.value
  if (!c || !downloadConfirmed.value || busy.value || refused.value || !/^[0-9a-f]{64}$/i.test(pinnedManifestDigest.value)) return
  busy.value = true; downloading.value = true; error.value = ''; notice.value = ''; cancelDownload()
  try {
    await postJson('/api/app-updates/fetch', { version: c.version, channel: channel.value, confirm: true, manifest_sha256: pinnedManifestDigest.value.toLowerCase() })
    const ready = await waitForStaged(c.version)
    if (ready) notice.value = `Verified and staged ${c.version}. It is not installed until you confirm the install below.`
    else error.value = 'Not staged yet. Nothing was installed. If the download is still running, check again shortly; otherwise check helper.log on the host.'
  } catch (e) {
    await read()
    error.value = refusal(e, 'The download could not be started.')
  } finally { downloading.value = false; busy.value = false }
}

// Bounded wait for the helper to stage the package. It only observes; the caller decides every action.
async function waitForStaged(version: string): Promise<boolean> {
  for (let i = 0; i < DOWNLOAD_POLLS; i++) {
    await new Promise(resolve => setTimeout(resolve, POLL_MS))
    if (!alive) return false
    await read()
    if (stagedVersion(version)) return true
  }
  return false
}

function ask(kind: Pending['kind'], version: Version) {
  pending.value = { kind, version }; confirmed.value = false; error.value = ''; notice.value = ''
}
function cancel() { pending.value = null; confirmed.value = false }

// Step 2: a separate, explicit confirmation. Only this stops the service, switches versions and checks health.
async function submit() {
  const p = pending.value
  if (!p || !confirmed.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    await postJson('/api/app-updates/apply', { version_id: p.version.id })
    operation.value = { kind: p.kind, target: p.version.id, beforeTx: install.value?.last?.tx ?? null, sawTx: false, polls: 0 }
    pending.value = null; confirmed.value = false
    notice.value = `${p.kind === 'rollback' ? 'Rollback' : 'Install'} started on the host. Progress is shown below.`
    timer = setTimeout(poll, POLL_MS)
  } catch (e) {
    await read() // refreshes blockers; read() clears errors, so set the refusal after it
    error.value = refusal(e, 'The update could not be started.')
  } finally { busy.value = false }
}

async function poll() {
  const op = operation.value
  if (!op) return
  const ok = await read()
  if (!ok && !reconnecting.value) return stop(error.value) // sign-in lapsed or refused: stop polling
  const cur = status.value?.install
  if (ok && cur) {
    if (cur.tx) op.sawTx = true
    // Done once the journal is idle and either a transaction ran (sawTx) or its outcome is new.
    const finished = !cur.tx && (op.sawTx || (cur.last?.tx ?? null) !== op.beforeTx)
    if (finished) return finish(cur.last)
  }
  op.polls++
  if (ok && !cur?.tx && !op.sawTx && op.polls >= NOT_STARTED_POLLS) {
    return stop('The update helper has not started. Nothing was switched as far as the status shows. Check helper.log on the host.')
  }
  if (op.polls >= MAX_POLLS) return stop('Still waiting after about 5 minutes. Check the host with update_recovery.py status; nothing more is started from here.')
  timer = setTimeout(poll, POLL_MS)
}
function finish(last: Last | null | undefined) {
  const op = operation.value
  operation.value = null; reconnecting.value = false
  if (!last) return stop('The update finished, but no outcome was recorded.')
  if (last.outcome === 'committed') {
    notice.value = `${op?.kind === 'rollback' ? 'Rolled back to' : 'Now running'} ${label(last.target)}. Health check: ${last.detail}`
  } else {
    error.value = `Not completed (${last.outcome}): ${last.detail}`
  }
}
function stop(message: string) {
  operation.value = null; reconnecting.value = false
  error.value = message
}

onMounted(read)
onBeforeUnmount(() => { alive = false; if (timer) clearTimeout(timer) })
</script>
<template>
  <section id="updates" class="card update-panel" aria-labelledby="updates-title">
    <h2 id="updates-title">Updates</h2>
    <p class="muted">Updates are never automatic. Checking reads the public GitHub release list only: it downloads nothing and changes nothing. Downloading, installing and rolling back each need your confirmation.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="reconnecting" class="muted" role="status">Reconnecting to the service. It is restarting, so this can take a minute. Nothing is started again from here.</p>
    <template v-if="status">
      <p class="status" role="status">{{ summary }}</p>
      <template v-if="!managed">
        <ul v-if="status.manual_instructions.length" class="updates">
          <li v-for="step in status.manual_instructions" :key="step">{{ step }}</li>
        </ul>
        <p v-for="problem in status.problems" :key="problem" class="muted small">{{ problem }}</p>
      </template>
      <template v-else>
        <div class="actions">
          <label>Channel<AppSelect v-model="channel" aria-label="Update channel"><option value="stable">Stable</option><option value="prerelease">Prerelease</option></AppSelect></label>
          <button class="btn" :disabled="busy || !!operation" @click="check">Check for updates</button>
          <span v-if="checkedAt" class="muted small">Checked GitHub {{ when(checkedAt / 1000) }}</span>
        </div>
        <p v-if="found" class="muted small">Installed version: {{ found.installed ?? 'none recorded' }}</p>

        <article v-if="candidate" class="release">
          <h3>{{ candidate.change === 'upgrade' ? 'Update' : 'Install' }} available: {{ candidate.version }}</h3>
          <p class="muted small">{{ candidate.tag }} · {{ candidate.channel }} channel{{ candidate.prerelease ? ' (prerelease)' : '' }} · published {{ candidate.published_at ?? 'unknown' }}</p>
          <dl class="facts">
            <dt>Product</dt><dd>{{ candidate.product }} · {{ candidate.platform }}</dd>
            <dt>Source repository</dt><dd>{{ candidate.repository }}</dd>
            <dt>Manifest sha256</dt><dd class="mono">{{ candidate.manifest_sha256 ?? 'not published by GitHub' }}</dd>
            <dt>Archive sha256</dt><dd class="mono">{{ candidate.archive_sha256 ?? 'not published by GitHub' }}</dd>
            <dt>Authenticity</dt><dd>{{ candidate.authenticity }}</dd>
          </dl>
          <h4>Release notes (plain text)</h4>
          <pre class="notes">{{ candidate.notes || 'This release has no notes.' }}</pre>
          <a v-if="releaseLink" :href="releaseLink" target="_blank" rel="noopener noreferrer">View this release on GitHub</a>
          <p v-if="refused" class="notice-warn" role="alert">{{ refused }}</p>
          <button v-else class="btn primary" :disabled="!canChange" @click="askDownload">Download and verify {{ candidate.version }}</button>
        </article>

        <section v-if="downloadAsk && candidate" class="confirm" aria-labelledby="download-title">
          <h3 id="download-title">Download and verify {{ candidate.version }}</h3>
          <p>Downloads the release's three assets from {{ candidate.repository }} into the private update inbox, then verifies product, platform, version, digests and signature. Nothing is stopped and no version is switched by this step.</p>
          <label>Manifest SHA-256 from the release page<input v-model.trim="pinnedManifestDigest" class="mono" autocomplete="off" spellcheck="false" maxlength="64" /></label>
          <p class="muted small">The GitHub API digest above is informational. Enter the digest independently from the release page to pin it.</p>
          <label class="check"><input v-model="downloadConfirmed" type="checkbox" />I have read this and want to download and verify {{ candidate.version }}.</label>
          <div class="actions">
            <button class="btn primary" :disabled="!downloadConfirmed || !/^[0-9a-f]{64}$/i.test(pinnedManifestDigest) || busy" @click="download">Download and verify</button>
            <button class="btn" :disabled="busy" @click="cancelDownload">Cancel</button>
          </div>
        </section>

        <p v-if="downloading" class="status" role="status">Downloading and verifying. Nothing is installed yet.</p>

        <p>Installed <strong>{{ label(install?.current) }}</strong> · Previous: {{ install?.previous ? label(install.previous) : 'none kept' }}</p>
        <ul v-if="blockers.length" class="updates" aria-label="Work that must finish first">
          <li v-for="b in blockers" :key="b">{{ b }}</li>
        </ul>
        <p v-if="blockers.length" class="muted small">Drain first. Nothing is stopped or cancelled for you.</p>
        <p v-if="install?.needs_recovery" class="notice-warn" role="alert">An earlier update was interrupted. Run recovery on the host before changing versions.</p>

        <h3>Available</h3>
        <ul v-if="installable.length" class="updates">
          <li v-for="v in installable" :key="v.id" class="release">
            <strong>{{ v.version }}</strong> · {{ v.channel }} · {{ v.change ?? 'change unknown' }} · staged {{ when(v.staged_at) }}
            <div class="muted small">Verified: {{ v.authenticity ?? 'not recorded' }} · Source repository: {{ v.repository ?? 'not recorded' }}</div>
            <div class="muted small">Release notes: not included in this package.</div>
            <button class="btn primary" :disabled="!canChange" @click="ask('install', v)">Install {{ v.version }}</button>
          </li>
        </ul>
        <p v-else class="muted">No staged update is waiting on this host. Check for updates to download and verify one.</p>
        <ul v-if="notOffered.length" class="updates" aria-label="Staged but not offered">
          <li v-for="v in notOffered" :key="v.id">{{ v.version ?? v.id }}: {{ unavailable(v) }}</li>
        </ul>

        <h3>Rollback</h3>
        <p v-if="previous?.complete">Roll back to <strong>{{ previous.version }}</strong>, the version before the current one.</p>
        <p v-else class="muted">No previous version is kept, so there is nothing to roll back to.</p>
        <button v-if="previous?.complete" class="btn" :disabled="!canRollback" @click="ask('rollback', previous)">Roll back to {{ previous.version }}</button>

        <section v-if="pending" class="confirm" aria-labelledby="confirm-title">
          <h3 id="confirm-title">{{ pending.kind === 'install' ? `Install ${pending.version.version}` : `Roll back to ${pending.version.version}` }}</h3>
          <p v-if="pending.kind === 'install'">Replaces {{ label(install?.current) }}. The service stops briefly, then starts the new version. If it fails its health check, it rolls back automatically.</p>
          <p v-else>Code goes back to {{ pending.version.version }}. This button does not roll data back: anything written while the newer version ran stays in the database. Restoring an older data snapshot is a separate step on the host.</p>
          <p class="small muted">Before anything stops:</p>
          <ul class="preflight">
            <li>Managed updates on this host: yes.</li>
            <li>Update already running: {{ inProgress ? 'yes, wait for it to finish' : 'no' }}.</li>
            <li>Running or waiting work: {{ blockers.length ? blockers.join('; ') : 'none found' }}.</li>
            <li>Database schema: the server checks it compatible before stopping anything.</li>
            <li>Data snapshot: taken automatically before the switch.</li>
          </ul>
          <label class="check"><input v-model="confirmed" type="checkbox" />I have read this and want to continue.</label>
          <div class="actions">
            <button class="btn primary" :disabled="!confirmed || busy || !canChange" @click="submit">{{ pending.kind === 'install' ? `Install ${pending.version.version}` : `Roll back to ${pending.version.version}` }}</button>
            <button class="btn" :disabled="busy" @click="cancel">Cancel</button>
          </div>
        </section>

        <p v-if="operation" class="status" role="status">{{ progressText }}</p>
      </template>
    </template>
  </section>
</template>
<style scoped>
.update-panel { margin: var(--gap-lg) 0; display: grid; gap: var(--gap-sm); }
h2, h3, h4 { margin: 0; }
.status { font-weight: 600; margin: 0; }
.small { font-size: var(--font-size-xs); margin: 0; }
.actions { display: flex; gap: var(--gap); flex-wrap: wrap; align-items: center; }
.actions label { display: flex; gap: var(--gap-sm); align-items: center; margin: 0; }
.updates { display: grid; gap: var(--gap-sm); padding-left: var(--gap); }
.release, .confirm { display: grid; gap: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); padding: var(--gap); justify-items: start; }
.facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: var(--gap-xs) var(--gap); margin: 0; font-size: var(--font-size-sm); }
.facts dt { color: var(--text-muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.mono { font-family: var(--font-mono, ui-monospace, monospace); font-size: var(--font-size-xs); }
.notes { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 16rem; overflow: auto; margin: 0; width: 100%; box-sizing: border-box; padding: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); }
.preflight { margin: 0; padding-left: var(--gap); }
.check { display: flex; align-items: flex-start; gap: var(--gap-sm); }
.check input { flex: none; margin-top: var(--gap-xs); accent-color: var(--accent); }
</style>
