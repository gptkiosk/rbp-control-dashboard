<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { getJson, postJson, type Card } from '@/lib/api'

interface State { pid:number; port:number; sha:string; started:string }
interface Verify { ok:boolean; at:number; summary:string; output:string }
interface Preview { last_verify?:Verify|null; available:boolean; kind?:'preview-verify'|'preview-review'; actions?:string[]; running?:boolean; state?:State|null; proxy_url?:string|null }
interface Result { action:string; ok:boolean; exit_code:number; duration_s:number; output:string; state?:State|null; proxy_url?:string|null }
const props=defineProps<{card:Card}>()
const emit=defineEmits<{changed:[]}>()
const preview=ref<Preview|null>(null), busy=ref(false), error=ref(''), output=ref('')
const base=computed(()=>`/api/projects/${props.card.project!.id}/stories/${props.card.id}/host-preview`)
const blocked=computed(()=>props.card.blocked_by.length>0)
async function load(){
  if(!props.card.project) return
  error.value=''
  try { preview.value=await getJson<Preview>(base.value) }
  catch(e) {
    preview.value=null
    error.value=e instanceof Error?e.message:String(e)
  }
}
async function action(value:'verify'|'serve'|'stop'){
  if(busy.value||blocked.value) return
  busy.value=true;error.value=''
  try { const result=await postJson<Result>(base.value,{action:value}); output.value=result.output; await load(); emit('changed') }
  catch(e){error.value=e instanceof Error?e.message:String(e)} finally {busy.value=false}
}
// A recorded result can be hours old (from before an update), so say when it ran.
const when=(at:number)=>new Date(at*1000).toLocaleString([], { dateStyle:'medium', timeStyle:'short' })
onMounted(load)
watch(()=>[props.card.id,props.card.project?.id],load)
</script>

<template>
  <section v-if="preview?.available || error" class="host-preview" aria-label="Host preview controls" @click.stop>
    <h3>Host preview</h3>
    <template v-if="preview?.available">
      <p class="muted small">Runs the approved preview script on this dashboard host. Its output is recorded with this project; no host terminal is required.</p>
      <p v-if="blocked" class="notice-warn">Finish this story’s prerequisites before running the host action.</p>
      <div class="actions">
        <button v-if="preview.actions?.includes('verify')" type="button" class="btn primary" :disabled="busy||blocked" @click="action('verify')"><AppIcon name="run" size="sm" />{{busy?'Verifying…':'Run verifier on host'}}</button>
        <button v-if="preview.actions?.includes('serve')" type="button" class="btn primary" :disabled="busy||blocked||preview.running" @click="action('serve')"><AppIcon name="run" size="sm" />{{busy?'Starting…':'Start preview on host'}}</button>
        <button v-if="preview.actions?.includes('stop')" type="button" class="btn" :disabled="busy||blocked||!preview.running" @click="action('stop')">Stop preview</button>
        <a v-if="preview.proxy_url" class="btn" :href="preview.proxy_url" target="_blank" rel="noopener noreferrer">Open remote preview</a>
      </div>
      <p v-if="preview.state" class="small muted">Running on the host: PID {{preview.state.pid}} · port {{preview.state.port}} · {{preview.state.sha.slice(0,7)}}.</p>
      <template v-if="preview.kind==='preview-verify' && preview.last_verify">
        <p v-if="preview.last_verify.ok" class="ok-text small" role="status" data-testid="verify-result">Last verifier run passed ({{ when(preview.last_verify.at) }}). You can accept this story.</p>
        <p v-else class="error-text" role="alert" data-testid="verify-result">Last verifier run failed ({{ when(preview.last_verify.at) }}). This story cannot be accepted until it passes; the end of the output says why. Run it again after fixing the cause or updating the dashboard.</p>
      </template>
      <pre v-if="output || preview.last_verify?.output" class="log-window" aria-label="Host preview output">{{output || preview.last_verify?.output}}</pre>
    </template>
    <p v-if="error" class="error-text" role="alert">{{error}}</p>
  </section>
</template>

<style scoped>
.host-preview{display:grid;gap:var(--gap-sm);padding:var(--gap);margin:var(--gap) 0;border:1px solid var(--accent);border-radius:var(--radius);background:var(--accent-soft)}
.host-preview h3,.host-preview p{margin:0}.actions{display:flex;gap:var(--gap-sm);flex-wrap:wrap;align-items:center}.error-text{margin:0;color:var(--danger);font-size:var(--font-size-sm)}.ok-text{margin:0;color:var(--ok)}
</style>
