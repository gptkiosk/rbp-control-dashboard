<script setup lang="ts">
import MembershipPrerequisites from '@/components/MembershipPrerequisites.vue'
import AppSelect from '@/components/AppSelect.vue'
import MediaGeneratePanel from '@/components/MediaGeneratePanel.vue'
import { computed, onMounted, ref, watch } from 'vue'
import ModalShell from '@/components/ModalShell.vue'
import { getJson, patchJson, type Agent, type BillingSettings, type MediaCatalog, type ModelRate } from '@/lib/api'
const props = defineProps<{ agents: Agent[]; models: string[] }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const settings = ref<BillingSettings | null>(null)
const error = ref('')
const saving = ref(false)
const media = ref<MediaCatalog | null>(null)
const mediaPrices = ref<Record<string, number | ''>>({})
const mediaSaved = ref<Record<string, number | ''>>({})
const limits = ref({ require_reviewed_pricing: false, per_run_cap_usd: '' as number | '' | null, paid_needs_runtime_limit: false })
const model = ref('')
const custom = ref(false)
const rate = ref<ModelRate>({ input: 0, output: 0, cached: 0, write: 0, write_1h: 0, max_input: null })
const modelOptions = computed(() =>
  [...new Set([...props.models, ...Object.keys(settings.value?.rates ?? {})])].sort(),
)
const current = computed(() => settings.value?.rates[model.value])
watch(model, () => {
  rate.value = current.value
    ? { ...current.value }
    : { input: 0, output: 0, cached: 0, write: 0, write_1h: 0, max_input: null }
  custom.value = false
})
onMounted(async () => {
  try {
    settings.value = await getJson<BillingSettings>('/api/billing')
    try {
      media.value = await getJson<MediaCatalog>('/api/media/models')
      const mine: Record<string, number | ''> = {}
      for (const m of media.value.models) mine[m.id] = m.price_source === 'operator' && m.price_usd !== null ? m.price_usd : ''
      mediaPrices.value = { ...mine }
      mediaSaved.value = { ...mine }
    } catch {
      media.value = null
    }
    const l = settings.value.limits
    limits.value = {
      require_reviewed_pricing: !!l?.require_reviewed_pricing,
      per_run_cap_usd: l?.per_run_cap_usd ?? '',
      paid_needs_runtime_limit: !!l?.paid_needs_runtime_limit,
    }
  } catch (e) {
    error.value = String(e)
  }
})
async function save() {
  if (!settings.value) return
  error.value = ''
  saving.value = true
  try {
    const rates: Record<string, ModelRate> = {}
    if (custom.value) {
      if (
        !model.value.trim() ||
        ![
          rate.value.input,
          rate.value.output,
          rate.value.cached,
          rate.value.write,
          rate.value.write_1h,
        ].every((v) => typeof v === 'number' && Number.isFinite(v) && v >= 0)
      )
        throw new Error('Enter a model ID and all five non-negative token rates.')
      rates[model.value.trim()] = {
        input: rate.value.input,
        output: rate.value.output,
        cached: rate.value.cached,
        write: rate.value.write,
        write_1h: rate.value.write_1h,
        max_input: rate.value.max_input || null,
      }
    }
    const mediaRates: Record<string, number | null> = {}
    for (const [id, value] of Object.entries(mediaPrices.value)) {
      if (value === mediaSaved.value[id]) continue
      if (value === '' || value === null) mediaRates[id] = null
      else if (typeof value === 'number' && Number.isFinite(value) && value >= 0) mediaRates[id] = value
      else throw new Error('A media price must be a number of dollars, or blank to use the listed price.')
    }
    const cap = limits.value.per_run_cap_usd
    if (cap !== '' && cap !== null && !(typeof cap === 'number' && Number.isFinite(cap) && cap >= 0))
      throw new Error('Cap per run must be a number of dollars, or blank for no cap.')
    await patchJson('/api/billing', {
      accounts: settings.value.accounts,
      rates,
      ...(Object.keys(mediaRates).length ? { media_rates: mediaRates } : {}),
      limits: {
        require_reviewed_pricing: limits.value.require_reviewed_pricing,
        per_run_cap_usd: cap === '' || cap === null || cap === 0 ? null : cap,
        paid_needs_runtime_limit: limits.value.paid_needs_runtime_limit,
      },
    })
    emit('saved')
    emit('close')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}
</script>
<template>
  <ModalShell labelledby="billing-title" @close="emit('close')">
    <form class="billing-form" @submit.prevent="save">
      <header>
        <h2 id="billing-title" class="section-title">Billing & API rates</h2>
        <MembershipPrerequisites />
        <button class="btn" type="button" aria-label="Close billing settings" @click="emit('close')">
          ×
        </button>
      </header>
      <p class="muted small">
        Savings use captured usage for the current calendar month in
        {{ settings?.timezone || 'America/Los_Angeles' }}, less the full monthly subscription. Each
        subscription is counted once per agent, across its sub-agents.
      </p>
      <p v-if="!settings && !error" role="status">Loading billing settings…</p>
      <div v-if="settings" class="accounts">
        <div v-for="a in agents" :key="a.id" class="account">
          <strong>{{ a.name }}</strong>
          <label
            >Billing mode<AppSelect
              v-model="settings.accounts[a.id].mode"
              class="input"
              :aria-label="`${a.name} billing mode`"
            >
              <option value="api">API usage</option>
              <option value="subscription">Subscription</option>
            </AppSelect></label
          >
          <label
            >USD / month<input
              v-model.number="settings.accounts[a.id].monthly_usd"
              class="input"
              type="number"
              min="0"
              max="10000"
              step="0.01"
              :disabled="settings.accounts[a.id].mode !== 'subscription'"
              :aria-label="`${a.name} monthly subscription`"
          /></label>
          <p v-if="a.id === 'grok'" class="muted small grok-note">
            Grok Build only runs on a Subscription here. Saving Subscription also means you accept that it sends the
            task and the files it reads to xAI. Runs have telemetry and trace upload off and stay inside a sandbox.
          </p>
        </div>
      </div>
      <fieldset v-if="settings" class="limits">
        <legend>Spending &amp; limits</legend>
        <p class="muted small">
          Nothing here is on by default. Without a limit, a paid route spends against your own provider account or
          key, so set a credit limit with your provider too (for example a key limit on your OpenRouter key). MCD
          shows its cost estimates but does not stop a run on spend unless you turn a limit on.
        </p>
        <label class="check"
          ><input v-model="limits.require_reviewed_pricing" type="checkbox" /> Require a reviewed price before a run
          starts</label
        >
        <label
          >Cap per run (USD, blank = no cap)<input
            v-model.number="limits.per_run_cap_usd"
            class="input"
            type="number"
            min="0"
            max="100000"
            step="0.01"
            aria-label="Cap per run in USD"
        /></label>
        <label class="check"
          ><input v-model="limits.paid_needs_runtime_limit" type="checkbox" /> Only start paid runs on agents with a
          built-in dollar limit (Claude)</label
        >
      </fieldset>
      <details v-if="media" class="media-models">
        <summary>Media models (fal.ai) · image and video generation</summary>
        <p class="muted small">
          Listed prices are fal's published list prices from {{ media.models[0]?.price_verified }} and are approximate; resolution, duration and
          audio change the final cost. A blank price means fal's pricing page did not list the model: run the media tool's <code>price</code>
          command for the live figure, or enter your own. Prices you enter replace the listed ones for display. Nothing here limits spending.
          fal key: <strong>{{ media.fal_key_saved ? 'saved (Profile, Private credentials)' : 'not saved' }}</strong>.
        </p>
        <div v-for="m in media.models" :key="m.id" class="media-row">
          <div>
            <strong>{{ m.label }}</strong>
            <span class="muted small"> · {{ m.id }} · per {{ m.unit }}<template v-if="m.tier"> · {{ m.tier }} tier</template></span>
            <p v-if="m.note" class="muted small">{{ m.note }}</p>
          </div>
          <label
            >USD per {{ m.unit }}<input
              v-model.number="mediaPrices[m.id]"
              class="input"
              type="number"
              min="0"
              max="10000"
              step="any"
              :placeholder="m.listed_price_usd === null ? 'not listed' : String(m.listed_price_usd)"
              :aria-label="`${m.label} price per ${m.unit}`"
          /></label>
        </div>
        <MediaGeneratePanel :key-saved="media.fal_key_saved" />
        <p class="muted small">
          Create the fal key with the <strong>{{ media.key_rules.preset }}</strong> preset and restrict its allowed models to:
          <code>{{ media.key_rules.allowed_models.join('  ') }}</code>
        </p>
      </details>
      <details v-if="settings" class="rate-settings">
        <summary>Model rates · USD per million tokens</summary>
        <p class="muted small">
          Source-reported cost takes precedence. Models whose name ends in :free cost 0. Other missing rates stay
          unpriced. Default estimates use standard published rates, with long-context tiers where the provider
          has one, verified October 13, 2026; tools, taxes and speed/residency surcharges are
          excluded. Requests above a configured input limit stay unpriced. A custom rate applies uniformly up
          to that limit.
        </p>
        <label
          >Model ID<AppSelect v-model="model" class="input" editable aria-label="Model ID" placeholder="Choose or enter the exact model ID">
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
          </AppSelect></label>
        <p v-if="current?.source && current.source !== 'custom'" class="small">
          <a :href="current.source" target="_blank" rel="noopener">Verified pricing source</a>
        </p>
        <p v-if="current?.long_after" class="muted small">
          Default tier above {{ current.long_after.toLocaleString() }} input tokens:
          {{ current.long_input_multiplier }}× input/cache rates and {{ current.long_output_multiplier }}×
          output.
        </p>
        <label class="check"
          ><input v-model="custom" type="checkbox" :disabled="!model.trim()" /> Save custom rates for this
          model</label
        >
        <div v-if="model" class="rates">
          <label
            >Input<input
              v-model.number="rate.input"
              class="input"
              type="number"
              min="0"
              step="any"
              :disabled="!custom"
          /></label>
          <label
            >Output<input
              v-model.number="rate.output"
              class="input"
              type="number"
              min="0"
              step="any"
              :disabled="!custom"
          /></label>
          <label
            >Cache read<input
              v-model.number="rate.cached"
              class="input"
              type="number"
              min="0"
              step="any"
              :disabled="!custom"
          /></label>
          <label
            >Cache write<input
              v-model.number="rate.write"
              class="input"
              type="number"
              min="0"
              step="any"
              :disabled="!custom"
          /></label>
          <label
            >1h cache write<input
              v-model.number="rate.write_1h"
              class="input"
              type="number"
              min="0"
              step="any"
              :disabled="!custom"
          /></label>
          <label
            >Max input tokens (blank = any)<input
              v-model.number="rate.max_input"
              class="input"
              type="number"
              min="1"
              step="1"
              :disabled="!custom"
          /></label>
        </div>
      </details>
      <p v-if="error" class="error-text" role="alert">{{ error }}</p>
      <footer>
        <button type="button" class="btn" @click="emit('close')">Cancel</button
        ><button type="submit" class="btn primary" :disabled="saving || !settings">
          {{ saving ? 'Saving…' : 'Save billing' }}
        </button>
      </footer>
    </form>
  </ModalShell>
</template>
<style scoped>
.billing-form {
  padding: var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
}
header,
footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
}
footer {
  justify-content: flex-end;
}
p {
  margin: 0;
}
.accounts,
.rate-settings,
.limits {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}
.limits {
  border: 1px solid var(--glass-border);
  border-radius: var(--radius, 8px);
  padding: var(--gap);
  margin: 0;
}
.media-models {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}
.media-row {
  display: grid;
  grid-template-columns: 1fr 9rem;
  align-items: end;
  gap: var(--gap);
  padding-bottom: var(--gap);
  border-bottom: 1px solid var(--glass-border);
}
.grok-note {
  grid-column: 1 / -1;
  margin: 0;
}
.account {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  align-items: end;
  gap: var(--gap);
  padding-bottom: var(--gap);
  border-bottom: 1px solid var(--glass-border);
}
label {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}
.rates {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--gap);
}
.check {
  flex-direction: row;
  align-items: center;
}
summary {
  cursor: pointer;
  color: var(--accent);
}
.rate-settings > * {
  margin-top: var(--gap);
}
@media (max-width: 600px) {
  .account {
    grid-template-columns: 1fr 1fr;
  }
  .account > strong {
    grid-column: 1 / -1;
  }
}
</style>
