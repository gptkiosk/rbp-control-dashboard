<script setup lang="ts">
import RecommendedAgentMix from '@/components/RecommendedAgentMix.vue'
import HostReadinessPanel from '@/components/HostReadinessPanel.vue'
import MembershipPrerequisites from '@/components/MembershipPrerequisites.vue'
import ReportStoragePanel from '@/components/ReportStoragePanel.vue'
import GithubSettingsPanel from '@/components/GithubSettingsPanel.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import AppSelect from '@/components/AppSelect.vue'
import { getJson, patchJson, postJson, putJson, type AgentsPayload, type Workdir } from '@/lib/api'
import type { Profile, SetupProgress } from '@/lib/profile'
import { useAuthStore } from '@/stores/auth'
import { useHelpStore } from '@/stores/help'
import { navItems } from '@/router/routes'
import { directoryName, directoryDetail } from '@/lib/selectLabels'
import { anyInstalled, NATIVE_AGENTS } from '@/lib/agentMix'
const steps = ['Your Raspberry Pi', 'Google sign-in', 'Coordinator & workers', 'OpenRouter', 'Memberships (optional)', 'GitHub (optional)', 'Find your way']
const auth = useAuthStore(), help = useHelpStore(), route = useRoute(), router = useRouter()
const profile = ref<Profile | null>(null), agents = ref<AgentsPayload | null>(null), workdirs = ref<Workdir[]>([])
const progress = ref<SetupProgress>({ step: 0, status: 'new', confirmed: [] })
const busy = ref(false), loading = ref(true), error = ref(''), notice = ref(''), checksError = ref('')
const replacingKey = ref(false)
const key = ref(''), workingDir = ref(''), spending = ref<Record<string, unknown> | null>(null)
const heading = ref<HTMLElement | null>(null), finished = ref(false)
const hasKey = computed(() => profile.value?.credentials.some(c => c.provider === 'openrouter') ?? false)
const available = (id: string) => agents.value?.agents.find(a => a.id === id)?.available
function applyProfile(p: Profile) { profile.value = { ...p, origins: p.origins ?? profile.value?.origins } }
const confirmed = (id: SetupProgress['confirmed'][number]) => progress.value.confirmed.includes(id)
const googleReady = computed(() => auth.enabled === true && auth.user?.method === 'google')
const workspaceReady = computed(() => !!profile.value?.preferences.working_dir && workdirs.value.some(w => w.path === profile.value?.preferences.working_dir))
const readiness = computed(() => [
  { label: 'Raspberry Pi and local installation', ok: confirmed('host') && workspaceReady.value, detail: 'Confirm the host and save an allowed workspace.' },
  { label: 'Google sign-in', ok: googleReady.value, detail: 'Configure host OAuth and sign in with an allowed Google account.' },
  { label: 'Hermes and OpenClaw', ok: anyInstalled(available, NATIVE_AGENTS) && confirmed('native_routes'), detail: 'Install the ones you use and confirm their provider and model configuration. Either one is enough.' },
  { label: 'OpenRouter spending key', ok: hasKey.value, detail: 'Save a profile key if you want actual key spending in RCD.' },
  { label: 'Optional memberships', ok: confirmed('subscriptions'), detail: 'Review membership access for CLIs you choose. A free-only setup can continue without a paid membership.' },
  { label: 'Help and navigation', ok: confirmed('tour'), detail: 'Review the menu and try Help chat.' },
])
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch (e) { error.value = e instanceof Error ? e.message : 'Could not save setup. Try again.' }
  finally { busy.value = false }
}
async function refresh() {
  key.value = ''
  loading.value = true; error.value = ''; checksError.value = ''
  try {
    const p = await getJson<Profile>('/api/profile'); applyProfile(p); workingDir.value = p.preferences.working_dir
    progress.value = structuredClone(p.preferences.setup ?? { step: 0, status: 'new', confirmed: [] })
    const requested = Number(route.query.step)
    if (typeof route.query.step === 'string' && Number.isInteger(requested) && requested >= 0 && requested < steps.length) progress.value.step = requested
    const results = await Promise.allSettled([getJson<AgentsPayload>('/api/agents'), getJson<{ workdirs: Workdir[] }>('/api/workdirs'), auth.refresh()])
    if (results[0].status === 'fulfilled') agents.value = results[0].value
    else { agents.value = null; checksError.value = 'Agent checks are unavailable. Refresh after the host is reachable.' }
    if (results[1].status === 'fulfilled') workdirs.value = results[1].value.workdirs
    else { workdirs.value = []; checksError.value += ' Workspace checks are unavailable.' }
  } catch (e) { error.value = e instanceof Error ? e.message : 'Could not load setup.' }
  finally { loading.value = false }
}
async function persist(state = progress.value) {
  const p = await patchJson<Profile>('/api/profile/setup', state)
  applyProfile(p)
  progress.value = structuredClone(p.preferences.setup!)
}
async function move(step: number) {
  await action(async () => {
    key.value = ''; replacingKey.value = false
    await persist({ ...progress.value, step, status: 'in_progress' }); finished.value = false
    await router.replace({ path: '/setup' })
    await nextTick(); heading.value?.focus()
  })
}
async function confirm(id: SetupProgress['confirmed'][number], event: Event) {
  const selected = (event.target as HTMLInputElement).checked
  await action(async () => {
    const values = progress.value.confirmed.filter(v => v !== id)
    if (selected) values.push(id)
    await persist({ ...progress.value, confirmed: values, status: 'in_progress' })
  })
}
async function saveWorkspace() {
  await action(async () => {
    const current = await getJson<Profile>('/api/profile')
    applyProfile(await putJson<Profile>('/api/profile', { ...current.preferences, working_dir: workingDir.value }))
    notice.value = 'Default workspace saved.'
  })
}
async function saveKey() {
  await action(async () => {
    try {
      applyProfile(await putJson<Profile>('/api/profile/credentials/openrouter', { value: key.value }))
      replacingKey.value = false
      spending.value = null; notice.value = 'Key saved privately. Native agent routes are unchanged.'
    } catch { throw new Error('Could not save the key. Check the value and private credential storage in Settings.') }
    finally { key.value = '' }
  })
}
async function checkKey() {
  await action(async () => {
    const result = await postJson<{ spending: Record<string, unknown> }>('/api/profile/openrouter/check')
    spending.value = result.spending; notice.value = 'OpenRouter key check completed. No model task was started.'
  })
}
async function finish() {
  await action(async () => { await persist({ ...progress.value, status: 'complete' }); finished.value = true })
}
onMounted(refresh)
onBeforeUnmount(() => { key.value = '' })
</script>

<template>
  <section class="setup-page" aria-labelledby="setup-title">
    <header class="setup-header"><div><h1 id="setup-title" class="page-title has-icon"><AppIcon name="settings" size="lg" />Set up RCD</h1><p class="muted">Connect your Raspberry Pi, your accounts and your agents. Pick up where you left off.</p></div><RouterLink to="/" class="btn">Return to dashboard</RouterLink></header>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="loading" role="status">Checking this installation…</p>
    <p v-if="!loading && !profile" class="card">Sign in with Google to save setup to your profile. <RouterLink to="/login?next=/setup">Open sign-in</RouterLink></p>
    <ReportStoragePanel />
    <div v-if="profile" class="wizard-layout">
      <nav class="card setup-steps" aria-label="Setup steps"><ol><li v-for="(title,i) in steps" :key="title"><button class="step-button" :class="{ current: progress.step === i }" :aria-current="progress.step === i ? 'step' : undefined" :disabled="busy || loading" @click="move(i)"><span class="step-number">{{ i+1 }}</span>{{ title }}</button></li></ol><p class="small muted">Progress is saved to your profile. You can return from Account → Setup wizard, Settings or Help.</p></nav>
      <div class="card step-content">
        <div class="step-heading"><p class="eyebrow">STEP {{ progress.step+1 }} OF {{ steps.length }}</p><h2 ref="heading" tabindex="-1">{{ steps[progress.step] }}</h2><progress :value="progress.step+1" :max="steps.length" aria-label="Setup walkthrough progress" /></div>
        <p v-if="notice" class="setup-notice" role="status">{{ notice }}</p>
        <p v-if="checksError" class="notice-warn" role="status">{{ checksError }}</p>
        <RecommendedAgentMix v-if="progress.step === 0" platform="pi" />
        <template v-if="progress.step === 0">
          <p>RCD runs locally on a Raspberry Pi. You can use its browser interface from another computer or your phone; the agents and their sign-ins belong on the Pi hosting RCD.</p>
          <ol class="instructions"><li>Use Raspberry Pi OS (64-bit) on a Raspberry Pi 4 or newer. The packaged RCD runtime uses Python 3.11 and the installer manages its isolated environment. Follow the clean-OS installation guide for the compatible Python and Node versions rather than relying on the OS defaults.</li><li>Once installed, use Settings → Agent tools for reviewed runtime installation. The packaged systemd service runs RCD across reboots; source-development setup is a separate path.</li><li>Keep installation settings in the private <code>~/.rcd-control/.env</code>. Configure allowed workspace roots and agent executable paths there, then restart RCD when no jobs are running.</li></ol>
          <div class="field-group">
            <label for="setup-workdir">Default working directory</label><AppSelect id="setup-workdir" v-model="workingDir" aria-label="Setup working directory"><option value="">Choose an allowed workspace…</option><option v-for="w in workdirs" :key="w.path" :value="w.path" :data-description="directoryDetail(w.path,w.branch)">{{ directoryName(w.path) }}</option></AppSelect>
            <button class="btn" :disabled="busy || !workingDir" @click="saveWorkspace">Save workspace</button>
            <p v-if="!workdirs.length" class="small muted">No workspace detected. Ask the Pi administrator to configure MAC_CONTROL_WORKDIR_ROOTS, then refresh checks.</p>
          </div>
          <HostReadinessPanel @changed="refresh" />
          <label class="check"><input type="checkbox" :checked="confirmed('host')" :disabled="busy" @change="confirm('host',$event)" />I have checked the Pi’s local installation and prerequisites.</label>
        </template>
        <template v-else-if="progress.step === 1">
          <p class="setup-state" :class="{ ready: googleReady }">{{ googleReady ? 'Signed in with Google' : auth.enabled ? 'Google sign-in is enabled; this session is not a Google login.' : 'Google sign-in is not configured on this installation.' }}</p>
          <p v-if="googleReady" class="small muted">{{ auth.user?.email }} · RCD sign-in is separate from your model subscriptions.</p>
          <p>Google protects access to RCD. It does not grant Gmail, Drive or model-provider access.</p>
          <details :open="!googleReady"><summary>Configure Google sign-in on the host</summary><ol class="instructions"><li>In <a href="https://console.cloud.google.com/auth/overview" target="_blank" rel="noopener noreferrer">Google Auth Platform</a>, create a Web application OAuth client. Each installer configures their own OAuth client and approved accounts. Choose External for personal Gmail accounts. The host email allowlist must contain the actual account selected at sign-in; repeat --allowed-email for additional operators.</li><li>Register the exact callback for each dashboard address, including its port. Use HTTPS for remote addresses. Download the client JSON in the creation dialog before closing it and store it privately as <code>~/.rcd-control/google-oauth-client.json</code>.</li></ol><p class="small muted">Default local callback: <code>http://127.0.0.1:8800/auth/callback</code>. For an SSH tunnel, register its browser port, for example <code>http://127.0.0.1:5173/auth/callback</code>. For Tailscale Serve, use your own machine’s HTTPS name and port: <code>https://YOUR-MACHINE.YOUR-TAILNET.ts.net:9443/auth/callback</code>.</p><p>Register every exact callback in Google and pass its origin with <code>--origin</code> when importing. A shared OAuth client can serve several installations; its other callbacks are not automatically trusted by this host.</p><details><summary>Private addresses configured on this installation</summary><p class="small muted">These addresses come from your host settings. They are not bundled defaults. Avoid including them in shared screenshots.</p><ul><li v-for="origin in profile.origins || ['http://127.0.0.1:8800']" :key="origin"><code>{{ origin }}/auth/callback</code></li></ul></details><pre>apps/api/.venv/bin/python scripts/configure-google-auth.py \
  ~/.rcd-control/google-oauth-client.json --data-dir ~/.rcd-control --enable \
  --allowed-email 'you@example.com'</pre><p class="small muted">Replace the example email before running. For a Mac SSH tunnel on port 5173, append <code>--origin http://127.0.0.1:5173</code>. For private HTTPS, append <code>--origin https://YOUR-MACHINE.YOUR-TAILNET.ts.net:9443</code> using your own address. Run the helper with your source venv Python or the installed release’s <code>current/runtime/bin/python</code>.</p><p>Replace the example email with your approved account. From the RCD checkout, restart the background service when no jobs are running. Then return here and sign in.</p></details>
          <a v-if="auth.enabled && !googleReady" class="btn primary" href="/auth/login?next=%2Fsetup">Sign in with Google</a><RouterLink to="/help?topic=sign-in" class="btn">Sign-in troubleshooting</RouterLink>
          <p class="small muted">OAuth JSON, recovery tokens and subscription credentials stay in private host storage. The wizard does not request them.</p>
        </template>
        <template v-else-if="progress.step === 2">
          <p>Hermes coordinates project planning and handoffs. OpenClaw handles assigned tasks through its configured agents and gateway.</p><div class="setup-notice"><h3>Install → configure → refresh</h3><p>A missing executable means the runtime is not installed or its configured path cannot be found. Start with Hermes as coordinator; add workers you plan to use.</p><ol class="instructions"><li>Open Settings → Agent tools below. Choose Install for a missing runtime, review the download and requirements, then confirm. Required supporting runtimes are included in the reviewed plan.</li><li>After installation, run the tool’s displayed setup or sign-in command in a terminal on the dashboard host. If you are browsing from another device, use a terminal or SSH session on the host.</li><li>Return here and choose Refresh checks. Detection confirms the executable is available; provider sign-in, model routing and gateway configuration still need your review.</li></ol><RouterLink to="/profile#agent-tools" class="btn primary">Install or upgrade agent runtimes</RouterLink><p class="small muted">Google operator sign-in is required to install. Already installed? Review the detected version in Agent tools and use Upgrade when offered. You do not need to reinstall an existing runtime.</p></div>
          <div class="agent-checks"><article v-for="id in ['hermes','openclaw']" :key="id"><h3>{{ id === 'hermes' ? 'Hermes' : 'OpenClaw' }}</h3><p class="setup-state" :class="{ ready: available(id) }">{{ available(id) === true ? 'Executable detected' : available(id) === false ? 'Executable not found at the configured path' : 'Not checked' }}</p><RouterLink v-if="available(id) === false" to="/profile#agent-tools" class="btn">Install runtime</RouterLink><a :href="id === 'hermes' ? 'https://hermes-agent.nousresearch.com/docs/getting-started/installation' : 'https://docs.openclaw.ai/getting-started'" target="_blank" rel="noopener noreferrer">Official installation guide ↗</a></article></div>
          <ol class="instructions"><li>Use Agent tools to install Hermes as coordinator on the Pi. Use a reviewed worker route; lightweight claw integrations remain experimental. Use <code>hermes setup</code> for Hermes, and OpenClaw’s onboarding to configure its gateway and agents.</li><li>Set their executable paths in RCD’s private host configuration if the default paths do not match. Refresh checks after installation or a service restart.</li><li>Choose OpenRouter free-first routes in the native agents. If you use Google BYOK fallback, configure its shared spending cap and review it before dispatching work. Free models can have capacity limits; BYOK can be billable.</li><li>Confirm that RCD’s assigned agent and model are honored for each task. Review the requested and reported model in the task’s run details.</li></ol>
          <label class="check"><input type="checkbox" :checked="confirmed('native_routes')" :disabled="busy" @change="confirm('native_routes',$event)" />I have reviewed the native agent routing, provider credentials and fallback spending cap.</label>
          <RouterLink to="/agents" class="btn">Inspect agents</RouterLink><RouterLink to="/profile#discord-profile" class="btn">Optional: pair Hermes on Discord</RouterLink><RouterLink to="/help?topic=hermes-access" class="btn">Hermes access how-to</RouterLink>
          <p class="small muted">Executable detection does not verify provider login or gateway health. This wizard starts no agents and changes no routes or permissions.</p>
        </template>
        <template v-else-if="progress.step === 3">
          <p>Save your OpenRouter key in your private profile to check actual key spending. Configure the inference key separately in Hermes and OpenClaw on the Pi.</p>
          <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">Create or manage an OpenRouter key ↗</a>
          <div v-if="hasKey" class="setup-notice" data-test="saved-openrouter"><p>OpenRouter key already saved for your profile. The wizard and Settings use the same saved key; you do not need to enter it again.</p><div class="actions"><button class="btn" :disabled="busy" @click="checkKey">Check key with OpenRouter</button><button v-if="!replacingKey" class="btn" :disabled="busy" @click="replacingKey = true">Replace saved key</button></div></div>
          <form v-if="!hasKey || replacingKey" class="key-form" @submit.prevent="saveKey"><label for="setup-openrouter">{{ hasKey ? 'Replacement OpenRouter key' : 'OpenRouter key' }}</label><input id="setup-openrouter" v-model="key" class="input" type="password" autocomplete="new-password" maxlength="4000" placeholder="Enter your OpenRouter key" required /><div class="actions"><button class="btn primary" :disabled="busy || !key.trim()">{{ hasKey ? 'Save replacement key' : 'Save private key' }}</button><button v-if="hasKey" type="button" class="btn" :disabled="busy" @click="key = ''; replacingKey = false">Cancel replacement</button></div></form>
          <div v-if="spending" class="setup-notice" role="status"><p>API usage this month: {{ spending.month_usd == null ? 'not reported' : '$'+spending.month_usd }}</p><p>BYOK usage this month: {{ spending.byok_month_usd == null ? 'not reported' : '$'+spending.byok_month_usd }}</p></div>
          <p class="small muted">Saving sends the key only to this RCD installation’s encrypted, write-only storage. Checking contacts OpenRouter to read this key’s spending; it starts no model request. Key-wide totals can include other apps using the same key.</p>
          <p>Hermes or OpenClaw may separately ask for an inference key during their native setup. That configures the agent itself; this saved dashboard key is for spending checks and is not copied into agents. Saving it does not choose paid models or change the existing fallback cap. Claude and Codex keep their subscription routes.</p><RouterLink to="/profile#credentials-profile" class="btn">Manage private credentials</RouterLink>
        </template>
        <template v-else-if="progress.step === 4">
          <div class="setup-notice"><p>Missing Codex, Claude Code or Grok Build? Install the CLI runtime in Agent tools first, then complete its native account sign-in on this host. A desktop app or Google dashboard login does not install or sign in the worker CLI.</p><RouterLink to="/profile#agent-tools" class="btn primary">Install or upgrade membership runtimes</RouterLink><p class="small muted">Return to this wizard’s Memberships step and choose Refresh checks after installation.</p></div><p>Paid memberships are optional for the free-only baseline. For membership-priced coding, use a supported native CLI and sign into its eligible paid account. Using OpenRouter or an API key for OpenAI/Anthropic models is separate usage billing and does not use your membership allowance.</p>
          <div class="agent-checks"><article><h3>ChatGPT / Codex</h3><p class="setup-state" :class="{ ready: available('codex') }">{{ available('codex') === true ? 'Codex executable detected' : available('codex') === false ? 'Codex executable not detected' : 'Not checked' }}</p><p>Install the Codex CLI used by RCD (there is no desktop app on Raspberry Pi OS). In the CLI run <code>codex login</code>, choose ChatGPT subscription sign-in, then check <code>codex login status</code>.</p><a href="https://learn.chatgpt.com/docs/auth" target="_blank" rel="noopener noreferrer">Official subscription sign-in guide ↗</a></article><article><h3>Claude / Claude Code</h3><p class="setup-state" :class="{ ready: available('claude') }">{{ available('claude') === true ? 'Claude Code executable detected' : available('claude') === false ? 'Claude Code executable not detected' : 'Not checked' }}</p><p>Install the Claude Code CLI. Run <code>claude</code> and sign into an eligible Claude subscription rather than API billing.</p><a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noopener noreferrer">Official installation and account guide ↗</a></article><article><h3>Grok Build</h3><p class="setup-state" :class="{ ready: available('grok') }">{{ available('grok') === true ? 'Grok Build executable detected' : available('grok') === false ? 'Grok Build executable not detected' : 'Not checked' }}</p><p>Optional. Install the Grok CLI (it runs on 64-bit Raspberry Pi OS) and sign in with <code>grok login --device-code</code> to a SuperGrok plan. Grok sends the task and the files it reads to xAI, so use it only on work you are willing to share; RCD runs it with telemetry and trace upload off and inside a filesystem sandbox, and only on a subscription route.</p><a href="https://x.ai/cli" target="_blank" rel="noopener noreferrer">Official Grok Build ↗</a></article></div>
          <MembershipPrerequisites />
          <p>The CLIs and their host sign-ins are what RCD executes; a sign-in on another device does not establish CLI readiness. Subscription limits still apply. Review per-story models and approved fallback routes before submitting a project.</p>
          <label class="check"><input type="checkbox" :checked="confirmed('subscriptions')" :disabled="busy" @change="confirm('subscriptions',$event)" />I reviewed the optional membership path. For agents I use, I confirmed native sign-in and limits; otherwise I will use reviewed free routes.</label>
          <RouterLink to="/help?topic=project-models" class="btn">Model and quota how-to</RouterLink>
          <p class="small muted">This is your confirmation, not an automated entitlement check. RCD does not collect subscription tokens. A paid API route needs separate approval.</p>
        </template>
        <template v-else-if="progress.step === 5">
          <p>GitHub is optional. Skip this step with Save &amp; continue if you do not want repository and pull request views; nothing is checked in the background unless you turn it on.</p>
          <GithubSettingsPanel wizard />
        </template>
        <template v-else>
          <p>On desktop, the main menu is on the left. On a phone, use the header Menu icon. Settings is at the bottom of the menu and in the account icon.</p>
          <div class="tour-actions"><button class="btn primary" @click="help.show('getting-started')"><AppIcon name="chat" />Try Help chat</button><RouterLink to="/help" class="btn">Browse step-by-step how-tos</RouterLink></div>
          <p>Help chat is available from the header on every page. It uses built-in guides with links to the relevant controls.</p>
          <ul class="feature-tour"><li v-for="item in navItems" :key="item.name"><RouterLink :to="item.path"><AppIcon :name="item.icon" /><strong>{{ item.label }}</strong></RouterLink><p>{{ item.description }}</p></li></ul>
          <label class="check"><input type="checkbox" :checked="confirmed('tour')" :disabled="busy" @change="confirm('tour',$event)" />I know where to find Help, how-tos and the main menu.</label>
          <h3>Your setup checklist</h3><p class="small muted">These checks distinguish detected settings from your confirmations. Pending items can be completed later; finishing the walkthrough does not install or authorize anything.</p>
          <ul class="readiness"><li v-for="item in readiness" :key="item.label"><strong>{{ item.ok ? '✓ Reviewed' : '○ Pending' }} · {{ item.label }}</strong><p v-if="!item.ok">{{ item.detail }}</p></li></ul>
          <p v-if="finished" class="setup-notice" role="status">Walkthrough saved. {{ readiness.every(r => r.ok) ? 'All checklist items are reviewed; test a small task when you are ready.' : 'Your pending checklist items remain visible here.' }}</p>
          <div v-if="finished" class="actions"><RouterLink to="/" class="btn primary">Open Overview</RouterLink><RouterLink to="/help?topic=agent-tasks" class="btn">Learn how to create your first task</RouterLink></div>
        </template>
        <footer class="wizard-footer"><button class="btn" :disabled="busy || loading || progress.step === 0" @click="move(progress.step-1)">Back</button><button class="btn" :disabled="busy || loading" @click="refresh">Refresh checks</button><button v-if="progress.step < steps.length-1" class="btn primary" :disabled="busy || loading" @click="move(progress.step+1)">Save & continue</button><button v-else class="btn primary" :disabled="busy || loading" @click="finish">Finish walkthrough</button></footer>
      </div>
    </div>
  </section>
</template>
<style scoped>
.setup-header { display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:var(--gap); }
.setup-header p { margin-top:var(--gap-sm); }
.wizard-layout { display:grid; grid-template-columns:var(--help-catalog-width) minmax(0,1fr); gap:var(--gap-lg); align-items:start; }
.setup-steps { position:sticky; top:var(--gap); background:var(--agent-glass); }
.setup-steps ol { list-style:none; padding:0; margin:0; display:grid; gap:var(--gap-sm); }
.step-button { width:100%; display:flex; align-items:center; gap:var(--gap-sm); padding:var(--gap-sm); min-height:var(--touch-target); text-align:left; background:transparent; color:var(--text); border:1px solid transparent; border-radius:var(--radius); font:inherit; cursor:pointer; }
.step-button.current { background:var(--nav-active); border-color:var(--surface-border); font-weight:var(--font-weight-strong); }
.step-number { display:grid; place-items:center; width:var(--touch-target); height:var(--touch-target); flex:none; border:1px solid var(--surface-border); border-radius:50%; }
.step-content { min-width:0; display:flex; flex-direction:column; gap:var(--gap); background:var(--agent-glass); }
.step-content h2,.step-content h3,.step-content p { margin:0; }
.step-content h2 { margin:var(--gap-xs) 0 var(--gap); font-size:var(--font-size-xl); }
.step-heading progress { width:100%; height:var(--gap-sm); accent-color:var(--accent); }
.step-heading h2:focus { outline:none; }
.instructions { margin:0; padding-left:var(--gap-lg); display:grid; gap:var(--gap-sm); }
.setup-state { color:var(--warn); font-weight:var(--font-weight-strong); font-size:var(--font-size-sm); }
.setup-state.ready { color:var(--ok); }
.setup-notice { padding:var(--gap); border:1px solid var(--surface-border); border-radius:var(--radius); background:var(--accent-soft); }
.agent-checks { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,var(--tile-min-width)),1fr)); gap:var(--gap); }
.agent-checks article { display:grid; gap:var(--gap-sm); align-content:start; padding:var(--gap); border:1px solid var(--surface-border); border-radius:var(--radius); min-width:0; }
.key-form { display:grid; gap:var(--gap-sm); }
.field-group { display:grid; gap:var(--gap-xs); }
.field-group > .btn { justify-self:start; margin-top:var(--gap-xs); }
.actions,.tour-actions,.wizard-footer { display:flex; flex-wrap:wrap; gap:var(--gap-sm); align-items:center; }
.wizard-footer { border-top:1px solid var(--surface-border); padding-top:var(--gap); margin-top:var(--gap); }
.wizard-footer .primary { margin-left:auto; }
.small { font-size:var(--font-size-xs); color:var(--text-muted); }
.check { display:flex; align-items:flex-start; gap:var(--gap-sm); }
.check input { accent-color:var(--accent); flex:none; margin-top:var(--gap-xs); }
.feature-tour { list-style:none; padding:0; display:grid; gap:var(--gap); grid-template-columns:repeat(auto-fit,minmax(min(100%,var(--tile-min-width)),1fr)); }
.feature-tour a { display:flex; gap:var(--gap-sm); align-items:center; }
.feature-tour p { font-size:var(--font-size-sm); color:var(--text-muted); margin-top:var(--gap-xs); }
.readiness { list-style:none; padding:0; display:grid; gap:var(--gap-sm); }
.readiness li { border-bottom:1px solid var(--surface-border); padding-bottom:var(--gap-sm); }
.readiness p { color:var(--text-muted); font-size:var(--font-size-sm); }
code,pre { overflow-wrap:anywhere; white-space:pre-wrap; font-family:var(--font-mono); }
pre { padding:var(--gap); background:var(--bg); border:1px solid var(--surface-border); border-radius:var(--radius); }
details { display:grid; gap:var(--gap); } summary { cursor:pointer; font-weight:var(--font-weight-strong); margin-bottom:var(--gap); }
@media(max-width:767.98px) { .wizard-layout { grid-template-columns:minmax(0,1fr); } .setup-steps { position:static; } .setup-steps ol { grid-template-columns:repeat(2,minmax(0,1fr)); } .step-button { font-size:var(--font-size-xs); padding:var(--gap-xs); } .step-number { width:var(--gap-lg); height:var(--gap-lg); } }
</style>
