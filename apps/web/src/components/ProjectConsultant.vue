<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import ChatConversation from '@/components/ChatConversation.vue'
import AppSelect from '@/components/AppSelect.vue'
import { getJson, postJson, type ChatThread, type ChatThreadDetail } from '@/lib/api'
import type { Preferences } from '@/lib/profile'
const props = defineProps<{ preferences?: Preferences; workdirs: {path:string;branch:string|null}[]; available: boolean; resumeId?: number }>()
const emit = defineEmits<{ review: [draft:{title:string;brief:string;working_dir:string}]; started:[id:number] }>()
const open=ref(false), threadId=ref(props.resumeId || 0), title=ref(''), goal=ref(''), workingDir=ref(''), busy=ref(false), error=ref('')
const agent=computed(()=>props.preferences?.ai_agent || 'hermes')
const model=computed(()=>props.preferences?.ai_model || 'openrouter/free')
const guidance='You are a project consultant in a read-only planning conversation with the person who owns the project. Answer what they ask first, in plain language, then ask the few clarifying questions that would most change the plan (two or three at a time, never a long form). Draw on what this installation knows (below) when it matters: the delivery model, which agent runtimes are installed and the spending policy, the standards and their minimum risks, the methods and security practices that apply, and which kinds of model suit which work; say plainly where something is unproven, and do not recite this background back unless asked. Keep talking until the person says they have enough; do not write the full brief before then. Once they say they are done, stop asking questions: confirm in a sentence and wait. When they ask for it, write a Markdown project brief with Goal, Working directory, Approach and methods, Phases, Stories, Scope, Definitions of done, Risks and the standards areas they fall under, Security considerations, Model and route considerations (free or paid, and why), Dependencies, Constraints, and open questions, so the coordinator can plan and create stories from it directly. Keep the brief below 20000 characters and distinguish assumptions from confirmed requirements. Your output is a proposal for the owner to review before the coordinator sees it. Stay within discussion and planning; leave all operational actions to the dashboard workflow.'
const draftAsk='That is enough. Please write the complete project brief now from everything we discussed, following the brief outline you were given.'
const draftBackground='The person is ready for the brief. Reply with the full Markdown project brief only: no preamble and no closing question. Do not leave questions hanging. Anything still undecided becomes either a stated assumption or a human decision story (an owner decision with its own scope and definition of done) in the Stories section, or is dropped if it does not change the plan.'
const drafting=ref(false);let timer:ReturnType<typeof setTimeout>|undefined
onBeforeUnmount(()=>{if(timer)clearTimeout(timer)})
async function start() {
  busy.value=true;error.value=''
  try {
    const dir=workingDir.value || props.preferences?.working_dir || props.workdirs[0]?.path || ''
    if (!dir || !goal.value.trim() || !title.value.trim()) throw Error('Choose a workspace and add a name and initial goal.')
    if (!threadId.value) {
      const t=await postJson<ChatThread>('/api/chat/threads',{agent:agent.value,model:model.value,working_dir:dir,title:`Project consultant: ${title.value}`.slice(0,200),mode:'read'})
      threadId.value=t.id;emit('started',t.id)
    }
    // The same knowledge the plan run gets: delivery models, the standards for this directory, and the models' track record here.
    let known=''
    try { known=(await getJson<{text:string}>(`/api/projects/consultant-context?working_dir=${encodeURIComponent(dir)}`)).text } catch { known='' }
    // The guidance and installation knowledge travel as background, so the approval check reads only what the operator wrote.
    await postJson(`/api/chat/threads/${threadId.value}/messages`,{context:`${guidance}${known?`\n\nWhat this installation knows (advice for this conversation, not authorization):\n${known}`:''}\n\nProject: ${title.value}\nWorking directory: ${dir}`,text:goal.value.trim()})
  } catch(e) {error.value=e instanceof Error?e.message:String(e)} finally {busy.value=false}
}
async function finishThen(done:()=>void,tries=0) {
  try {
    const t=await getJson<ChatThreadDetail>(`/api/chat/threads/${threadId.value}`)
    const working=t.busy || t.messages.some(m=>m.status==='running'||m.status==='pending_approval')
    if(!working){done();return}
    if(t.messages.some(m=>m.status==='pending_approval')) throw Error('A message is waiting for your approval. Approve or reject it, then try again.')
  } catch(e) {error.value=e instanceof Error?e.message:String(e);drafting.value=false;return}
  if(tries>300){error.value='The consultant is taking too long. Try again when the conversation shows it has finished.';drafting.value=false;return}
  timer=setTimeout(()=>void finishThen(done,tries+1),2000)
}
/** The owner decides when the discussion is enough: ask for the brief, wait for it, then open the editable review. */
async function draft() {
  drafting.value=true;error.value=''
  try {
    await postJson(`/api/chat/threads/${threadId.value}/messages`,{context:draftBackground,text:draftAsk})
  } catch(e) {error.value=e instanceof Error?e.message:String(e);drafting.value=false;return}
  void finishThen(async()=>{drafting.value=false;await review()})
}
async function review() {
  busy.value=true;error.value=''
  try {
    const t=await getJson<ChatThreadDetail>(`/api/chat/threads/${threadId.value}`)
    if(t.busy || t.messages.some(m=>m.status==='running'||m.status==='pending_approval')) throw Error('Wait for the conversation to finish and resolve any pending approval first.')
    const response=[...t.messages].reverse().find(m=>m.role==='assistant'&&m.status==='done'&&m.text.trim())
    if(!response) throw Error('Ask the consultant to produce a complete project brief first.')
    emit('review',{title:title.value.trim() || t.title.replace(/^Project consultant: /,''),brief:response.text,working_dir:t.working_dir})
  } catch(e) {error.value=e instanceof Error?e.message:String(e)} finally {busy.value=false}
}
</script>
<template>
  <div class="consultant-entry"><button class="btn" :aria-expanded="open" @click="open=!open">{{open?'Hide project consultant':'Refine with project consultant'}}</button>
    <section v-if="open" class="consultant-glass" aria-labelledby="consultant-title">
      <h3 id="consultant-title">Project consultant</h3>
      <p>Describe what you want to build. The consultant answers, asks what it needs to know, and keeps going until you say that is enough. Then it writes up the plan for you to review and send to the coordinator, which creates the stories.</p>
      <p class="muted">New conversations use {{agent}} · {{model}}. Free OpenRouter is the default (for Hermes and OpenClaw it means the free model they are set up with) and can throttle or time out. Membership routes use your native CLI account; API routes can incur charges. <RouterLink to="/profile#ai-settings">Configure AI defaults</RouterLink> · <RouterLink to="/help?topic=project-consultant">Consultant help</RouterLink></p>
      <p v-if="!available && !threadId" role="status">The configured consultant runtime is unavailable. <RouterLink to="/profile#agent-tools">Install an agent runtime</RouterLink> or change AI defaults.</p>
      <p v-if="error" role="alert">{{error}}</p>
      <p v-if="busy && threadId" role="status" class="muted">Sending your goal to the consultant…</p>
      <form v-if="!threadId" @submit.prevent="start">
        <label>Project name<input v-model="title" class="input" maxlength="200" required /></label>
        <label>Working directory<AppSelect v-model="workingDir" aria-label="Consultant working directory"><option value="">Profile or first allowed workspace</option><option v-for="w in workdirs" :key="w.path" :value="w.path">{{w.path}}</option></AppSelect></label>
        <label>Initial goal<textarea v-model="goal" class="input" rows="4" maxlength="12000" required /></label>
        <button class="btn primary" :disabled="busy || !available">Start consultant conversation</button>
      </form>
      <template v-else><p>Conversation #{{threadId}} keeps its original agent/model. Changed defaults apply to new conversations.</p><div class="conversation"><ChatConversation :thread-id="threadId" embedded @deleted="threadId=0; emit('started',0)" @back="open=false" /></div><p v-if="drafting" role="status" class="muted">Writing up the plan from this conversation…</p><div class="actions"><button class="btn primary" :disabled="busy || drafting" @click="draft">That’s enough, write up the plan</button><button class="btn" :disabled="busy || drafting" @click="review">Review brief &amp; submit to the coordinator</button></div><p class="muted">“Write up the plan” asks the consultant for the brief and opens it for you to edit. Nothing reaches the coordinator until you confirm there, and stories run only after their separate project approval. If the last reply already is the brief, use the second button.</p></template>
    </section>
  </div>
</template>
<style scoped>
.consultant-entry {margin-top:var(--gap);}
.consultant-glass {margin-top:var(--gap);padding:var(--gap-lg);background:var(--dialog-glass);backdrop-filter:blur(var(--glass-blur));border:1px solid var(--select-border);border-radius:var(--radius);display:flex;flex-direction:column;gap:var(--gap);}
form {display:flex;flex-direction:column;gap:var(--gap);}
.actions {display:flex;flex-wrap:wrap;gap:var(--gap);}
.conversation {height:36rem;max-height:65vh;min-height:20rem;overflow:hidden;}
label {display:flex;flex-direction:column;gap:var(--gap-xs);}
</style>
