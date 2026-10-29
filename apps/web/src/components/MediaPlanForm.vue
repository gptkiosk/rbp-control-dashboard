<script setup lang="ts">
// The asset-plan editor, shared by slots not made yet and published slots being revised.
export interface PlanFields { prompt: string; purpose: string; world: string; width: number; height: number; resolution: string; minSeconds: number; maxSeconds: number }
defineProps<{ kind: 'image' | 'video'; published?: boolean; saving: boolean; busy: boolean }>()
const plan = defineModel<PlanFields>({ required: true })
const emit = defineEmits<{ save: []; cancel: [] }>()
</script>
<template>
  <form class="asset-plan" @submit.prevent="emit('save')">
    <p v-if="published" class="muted small">Revise this published asset. The published file stays on the site until you accept a new take. Names, types and references stay fixed. Saving does not generate or approve spending.</p>
    <p v-else class="muted small">Refine this ungenerated asset. Names, types and references stay fixed; add/remove assets through a reviewed inventory amendment. Saving does not generate or approve spending.</p>
    <label>Artwork prompt<textarea v-model="plan.prompt" class="input" maxlength="4000" rows="4" required /></label>
    <label>Purpose<input v-model="plan.purpose" class="input" maxlength="500" /></label>
    <label>World / theme<input v-model="plan.world" class="input" maxlength="80" /></label>
    <div class="controls"><label>Width<input v-model.number="plan.width" class="input" type="number" min="128" max="4096" required /></label><label>Height<input v-model.number="plan.height" class="input" type="number" min="128" max="4096" required /></label><label>Resolution<select v-model="plan.resolution" class="input"><option value="">Use generation tier</option><template v-if="kind === 'image'"><option value="1K">1K</option><option value="2K">2K</option><option value="4K">4K</option></template><template v-else><option value="480P">480P</option><option value="768P">768P</option><option value="1080P">1080P</option></template></select></label></div>
    <p class="muted small">Display dimensions choose the aspect ratio; resolution controls provider output and cost.</p>
    <div v-if="kind === 'video'" class="controls"><label>Minimum seconds<input v-model.number="plan.minSeconds" class="input" type="number" min="2" max="10" /></label><label>Maximum seconds<input v-model.number="plan.maxSeconds" class="input" type="number" min="2" max="10" /></label></div>
    <div class="controls"><button class="btn primary" :disabled="saving || busy">{{ saving ? 'Saving…' : 'Save asset plan' }}</button><button class="btn" type="button" :disabled="saving" @click="emit('cancel')">Cancel</button></div>
  </form>
</template>
<style scoped>
.asset-plan { display:grid; gap:var(--gap-sm); width:100%; min-width:0; padding:var(--gap); border:1px solid var(--surface-border); border-radius:var(--radius); }
.asset-plan label { display:grid; gap:var(--gap-xs); min-width:0; }
.asset-plan .controls label { flex:1; }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap); }
</style>
