<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import LoadingCard from '@/components/LoadingCard.vue'
import { RouterLink } from 'vue-router'
import { getJson, postJson, type Card } from '@/lib/api'
import type { Project } from '@/lib/projects'
import { agentLabel } from '@/lib/cards'
const props=defineProps<{card:Card}>()
const emit=defineEmits<{changed:[]}>()
const visible=computed(()=>props.card.project?.role==='story' && props.card.assignee_type!=='human' && ['queued','backlog'].includes(props.card.column))
const project=ref<Project|null>(null), selected=ref(''), acknowledged=ref(false), busy=ref(false), loading=ref(false), error=ref(''), notice=ref('')
const blocker=computed(()=>project.value?.tasks.find(t=>t.card_id===props.card.id)?.queued_route_blocker)
const options=computed(()=>project.value?.tasks.find(t=>t.card_id===props.card.id)?.queued_route_options ?? [])
let generation=0
watch(()=>[props.card.id,props.card.column,props.card.agent,props.card.model],async()=>{
 const mine=++generation;project.value=null;selected.value='';acknowledged.value=false;notice.value='';error.value=''
 if(!visible.value)return
 loading.value=true
 try {const p=await getJson<Project>(`/api/projects/${props.card.project!.id}`);if(mine===generation)project.value=p}
 catch(e){if(mine===generation)error.value=e instanceof Error?e.message:String(e)}
 finally{if(mine===generation)loading.value=false}
},{immediate:true})
watch(selected,()=>acknowledged.value=false)
async function change(){
 if(busy.value||!acknowledged.value)return
 const route=options.value.find(r=>`${r.agent}:${r.model}`===selected.value)
 if(!route||!project.value)return
 busy.value=true;error.value=''
 try{
  await postJson(`/api/projects/${props.card.project!.id}/stories/${props.card.id}/route`,{
   revision:project.value.revision,...route,expected_agent:props.card.agent,expected_model:props.card.model??'',acknowledge:true})
  notice.value='Task route updated. It keeps its dependencies and the project’s pause state.';emit('changed')
 }catch(e){error.value=e instanceof Error?e.message:String(e)}finally{busy.value=false}
}
</script>
<template>
 <section v-if="visible" class="queued-route" aria-label="Change pending task route">
  <strong>Change model or platform</strong>
  <p class="muted small">Switch this pending task when a membership runs out. Scope and dependencies stay the same.</p>
  <LoadingCard v-if="loading" title="Loading configured subscription routes…" :rows="1" />
  <p v-else-if="blocker" role="status">{{blocker}}</p>
  <template v-else-if="options.length">
   <label>Subscription route<select aria-label="Subscription route" v-model="selected" :disabled="busy"><option value="">Choose a route…</option><option v-for="r in options" :key="`${r.agent}:${r.model}`" :value="`${r.agent}:${r.model}`">{{agentLabel(r.agent)}} · {{r.model}}</option></select></label>
   <p class="muted small">Uses membership quota. Provider limits and enabled overage still apply.</p>
   <label class="approval"><input v-model="acknowledged" type="checkbox" :disabled="busy||!selected" />I approve this route for this task.</label>
   <button class="btn primary" :disabled="busy||!selected||!acknowledged" @click="change">{{busy?'Switching route…':'Switch task route'}}</button>
  </template>
  <p v-else-if="!error" class="muted small">No other configured subscription route is available. <RouterLink to="/profile?action=billing#accounts">Review Billing &amp; rates</RouterLink> and <RouterLink to="/profile#route-recovery">Model recovery</RouterLink>.</p>
  <p v-if="error" role="alert" class="error">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
 </section>
</template>
<style scoped>
.queued-route{display:grid;gap:var(--gap-sm);padding:var(--gap);border:1px solid var(--panel-border);border-radius:var(--radius);background:var(--panel-raised)}
.approval{display:flex;align-items:center;gap:var(--gap-sm)}.approval input{width:auto;margin:0}
p{margin:0}label{display:grid;gap:var(--gap-xs)}select{max-width:100%;min-width:0}
</style>
