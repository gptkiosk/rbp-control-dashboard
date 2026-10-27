<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJson, putJson, patchJson } from '@/lib/api'
import { agentLabel } from '@/lib/cards'
import type { RecoveryInfo, RecoveryPolicy, RecoveryRoute } from '@/lib/routeRecovery'
import PanelHead from './PanelHead.vue'
import ManagedItem from './ManagedItem.vue'
import ToggleSwitch from './ToggleSwitch.vue'
import NoteFold from './NoteFold.vue'
import RouteRecoveryNotice from './RouteRecoveryNotice.vue'
const emit = defineEmits<{ saved: [policy: RecoveryPolicy] }>()
const data = ref<RecoveryInfo|null>(null), saved = ref(false), busy = ref(false), error = ref('')
const policy = ref<RecoveryPolicy>({enabled:false, apply_to_stories:false, routes:[]})
function apply(value: RecoveryInfo) { data.value = value; policy.value = structuredClone(value.policy) }
onMounted(async () => { try { apply(await getJson('/api/profile/route-reliability')) } catch { error.value = 'Model recovery settings could not be loaded. Refresh to try again.' } })
function selected(route: RecoveryRoute) { return policy.value.routes.some(r => r.agent === route.agent && r.model === route.model) }
function choose(route: RecoveryRoute, on: boolean) {
  saved.value = false
  policy.value.routes = on ? [...policy.value.routes, {agent:route.agent, model:route.model}] : policy.value.routes.filter(r => r.agent !== route.agent || r.model !== route.model)
}
function move(index: number, offset: number) {
  const values = [...policy.value.routes], item = values.splice(index, 1)[0]
  if (item) values.splice(index + offset, 0, item)
  policy.value.routes = values; saved.value = false
}
async function save() {
  busy.value = true; error.value = ''; saved.value = false
  try { apply(await putJson('/api/profile/route-reliability', policy.value)); saved.value = true; emit('saved', JSON.parse(JSON.stringify(policy.value))) }
  catch(e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
async function membership(on: boolean, paid = false) {
  busy.value = true; error.value = ''
  try {
    await patchJson('/api/routes/policy/cost', {[paid ? 'paid' : 'membership']: on})
    const fresh = await getJson<RecoveryInfo>('/api/profile/route-reliability')
    data.value = fresh
  } catch(e) { error.value = e instanceof Error ? e.message : String(e) } finally { busy.value = false }
}
</script>
<template>
  <section id="route-recovery" class="card recovery-panel" aria-labelledby="route-recovery-title">
    <PanelHead id="route-recovery-title" title="Model recovery" :status="policy.enabled ? 'Enabled' : 'Manual'" :tone="policy.enabled ? 'ok' : 'muted'" help="project-models" />
    <p class="muted small">Choose alternatives once. Failed planning attempts keep the same task and validated project boundaries.</p>
    <RouteRecoveryNotice :info="data" />
    <ToggleSwitch v-model="policy.enabled" label="Enable automatic route recovery" hint="One output repair, then the next approved route. Each route is tried once per planning step." />
    <ToggleSwitch v-model="policy.apply_to_stories" :disabled="!policy.enabled" label="Include alternatives in future project plans" hint="Adds eligible free and membership routes to the editable map. Plan approval authorizes their use." />
    <ToggleSwitch v-if="data" :model-value="data.subscription_allowed" :disabled="busy" label="Allow membership routes" hint="Uses a configured Claude, Codex or Grok Build membership and its quota. Provider overage settings still apply." @update:model-value="membership" />
    <ToggleSwitch v-if="data" :model-value="data.paid_allowed" :disabled="busy" label="Allow separately approved paid API routes" hint="Additional provider API charges, always tried last. Each plan or task still needs paid-route approval; price and budget checks remain active." @update:model-value="on => membership(on,true)" />
    <p v-if="data" class="muted small">These switches are the app route policy's cost classes. Membership uses account quota; provider overage settings still apply. Membership routes are preferred, then free models; paid API is the last resort.</p>
    <ol v-if="policy.routes.length" class="route-order" aria-label="Recovery order">
      <li v-for="(r, i) in policy.routes" :key="r.agent + r.model"><span>{{ agentLabel(r.agent) }} · {{ r.model }}</span><button type="button" class="btn small-btn" :disabled="i === 0" :aria-label="`Move ${r.model} earlier`" @click="move(i,-1)">↑</button><button type="button" class="btn small-btn" :disabled="i === policy.routes.length - 1" :aria-label="`Move ${r.model} later`" @click="move(i,1)">↓</button><button type="button" class="btn small-btn" @click="choose(r,false)">Remove</button></li>
    </ol>
    <ul class="route-list">
      <ManagedItem v-for="r in data?.options ?? []" :key="r.agent + r.model" :name="`${agentLabel(r.agent)} · ${r.model}`" :mark="!r.installed ? 'missing' : !r.allowed ? 'warn' : 'info'" :word="!r.installed ? 'not installed' : r.allowed ? r.price_class : 'blocked by policy'" :detail="r.cost" health-disabled>
        <RouterLink v-if="r.installed && !r.allowed" class="btn small-btn" to="/agents?action=billing">Configure billing &amp; membership</RouterLink>
        <label class="route-check"><input type="checkbox" :checked="selected(r)" :disabled="busy || !r.allowed || (!selected(r) && policy.routes.length >= 6)" @change="choose(r,($event.target as HTMLInputElement).checked)" />Use as a recovery route</label>
      </ManagedItem>
    </ul>
    <p v-if="data && !data.options.length" class="muted small">Install and sign in to an agent, then configure its models. <RouterLink to="/profile#agent-tools">Open Agent tools</RouterLink></p>
    <NoteFold label="Billing, approvals and reliability"><p>Paid API alternatives require separate planning approval each time a plan starts or a new route is chosen. A membership does not include API charges. Provider credit limits, app budget caps and execution permissions still apply. Native runtime fallback and overage settings can affect actual billing. Model lock stops automatic story switching. Timeouts on editing tasks require review of partial work.</p><p>Telemetry covers up to {{ data?.sample_limit ?? 500 }} recent local runs over {{ data?.window_days ?? 7 }} days. Three provider, runtime, timeout or output failures in the last five attempts trigger advice and lower that route’s recovery priority. A successful process is not independent proof that its work is correct. Provider availability cannot be guaranteed.</p></NoteFold>
    <details v-if="data?.health.length"><summary class="small">Recent route outcomes</summary><ul class="health-list"><li v-for="r in data.health" :key="r.agent + r.model">{{ agentLabel(r.agent) }} · {{ r.model }}: {{ r.failures }}/{{ r.attempts }} attempts failed{{ r.persistent ? ' · consider another route' : '' }}</li></ul></details>
    <div class="actions"><button type="button" class="btn primary" :disabled="busy || !data || (policy.enabled && !policy.routes.length)" @click="save">{{ busy ? 'Saving…' : 'Save recovery settings' }}</button><RouterLink to="/agents?action=billing" class="btn">Billing &amp; routes</RouterLink><RouterLink to="/profile#ai-settings" class="btn">Choose primary AI</RouterLink></div>
    <p v-if="saved" role="status">Recovery settings saved. Existing approved stories keep their reviewed routes.</p><p v-if="error" class="error-text" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.recovery-panel{display:grid;gap:var(--gap);max-width:70rem;margin:var(--gap-lg) auto 0}.recovery-panel p{margin:0}.route-list{display:grid;gap:var(--gap-sm);padding:0;list-style:none}.route-check,.actions,.route-order li{display:flex;align-items:center;gap:var(--gap-sm);flex-wrap:wrap}.route-order{padding-left:1.4rem}.route-order li{margin:var(--gap-sm) 0}.route-order span{flex:1;overflow-wrap:anywhere}.health-list{padding-left:1.4rem;overflow-wrap:anywhere}.small{font-size:var(--font-size-xs)}.actions .btn{white-space:normal}
</style>
