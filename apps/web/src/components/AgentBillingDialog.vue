<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { computed, onMounted, ref, watch } from 'vue'
import ModalShell from '@/components/ModalShell.vue'
import { getJson, patchJson, type Agent, type BillingSettings, type ModelRate } from '@/lib/api'
const props = defineProps<{ agents: Agent[]; models: string[] }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const settings = ref<BillingSettings | null>(null)
const error = ref('')
const saving = ref(false)
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
    await patchJson('/api/billing', { accounts: settings.value.accounts, rates })
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
.rate-settings {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
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
