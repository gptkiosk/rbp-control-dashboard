<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import ChatConversation from '@/components/ChatConversation.vue'
import AppSelect from '@/components/AppSelect.vue'
import NoteFold from '@/components/NoteFold.vue'
import ProjectTypePicker from '@/components/ProjectTypePicker.vue'
import { getJson, postJson, type ChatThread, type ChatThreadDetail } from '@/lib/api'
import type { Preferences } from '@/lib/profile'
import { useRoutes } from '@/lib/routes'
const props = defineProps<{ preferences?: Preferences; workdirs: {path:string;branch:string|null}[]; scratchRoot?: string | null; available?: boolean; resumeId?: number }>()
const emit = defineEmits<{ review: [draft:{title:string;brief:string;working_dir:string;project_type?:string|null}]; started:[id:number] }>()
const typeKey=(id:number)=>`mcd-consultant-type-${id}`
// The type is remembered per conversation so a resumed consultant still hands it to the plan. Browser storage is only a convenience here.
const savedType=(id:number)=>{try{return localStorage.getItem(typeKey(id))||null}catch{return null}}
const open=ref(false), threadId=ref(props.resumeId || 0), projectType=ref<string|null>(props.resumeId?savedType(props.resumeId):null), typeCount=ref(0), title=ref(''), goal=ref(''), workingDir=ref(''), busy=ref(false), error=ref('')
// The consultant is a read-only chat: it starts on the Chat default in Models & providers.
const chatRoutes=useRoutes('chat')
const agent=computed(()=>chatRoutes.data.value?.default?.runtime || 'hermes')
const model=computed(()=>chatRoutes.data.value?.default?.model || '')
const available=computed(()=>props.available !== false && (!chatRoutes.data.value || !!chatRoutes.data.value.default))
const guidance='Help the owner shape a project through a read-only conversation. Use the shared intake questions for the selected template from installation context; do not mix other templates into it. Answer their question first, then ask only the missing facts that would change the outcome, two or three at a time. Reuse facts already given and accept Help me decide. Suggest sensible defaults, clearly marked as assumptions. Do not require a prewritten brief, technical commands, credentials or a story list from the person. Ask about visual direction and real media for a website; distinguish reference art from final assets. Media/cloud spending preferences do not grant approval. Keep routine tools/access readiness in the eventual plan. When asked to write up, return a compact summary of the goal, confirmed template answers, exclusions, proposed assumptions and genuine unresolved decisions. The dashboard planner will create the stories, prerequisites and verification gates later. No operational actions or provider calls are authorized by this conversation.'
const draftAsk=()=>`That is enough. Please write the project intake summary now from what we discussed. Project type: ${projectType.value||savedType(threadId.value)||'not chosen'}. Include confirmed template answers and clearly labelled assumptions. Do not repeat answered questions or generate the story plan. Keep it under 8000 characters.`
const draftBackground='Reply with the Markdown intake summary only. Preserve user requirements, required final media, theme states and delivery target. State undecided matters as assumptions or decisions; never invent access, completed work or spending approval. This summary opens for operator review before planning.'
const drafting=ref(false);let timer:ReturnType<typeof setTimeout>|undefined
onBeforeUnmount(()=>{if(timer)clearTimeout(timer)})
async function start() {
  busy.value=true;error.value=''
  try {
    const dir=workingDir.value || props.scratchRoot || props.preferences?.working_dir || props.workdirs[0]?.path || ''
    if (!dir || !goal.value.trim() || !title.value.trim()) throw Error('Choose a workspace and add a name and initial goal.')
    if (typeCount.value && !projectType.value) throw Error('Choose a project type, or Other if nothing fits exactly.')
    if (!threadId.value) {
      const t=await postJson<ChatThread>('/api/chat/threads',{agent:agent.value,model:model.value,working_dir:dir,title:`Project consultant: ${title.value}`.slice(0,200),mode:'read'})
      threadId.value=t.id;try{if(projectType.value)localStorage.setItem(typeKey(t.id),projectType.value)}catch{/* optional */};emit('started',t.id)
    }
    // The same knowledge the plan run gets: delivery models, the standards for this directory, and the models' track record here.
    let known=''
    try { known=(await getJson<{text:string}>(`/api/projects/consultant-context?working_dir=${encodeURIComponent(dir)}&project_type=${encodeURIComponent(projectType.value||'')}`)).text } catch { known='' }
    // The guidance and installation knowledge travel as background, so the approval check reads only what the operator wrote.
    await postJson(`/api/chat/threads/${threadId.value}/messages`,{context:`${guidance}${known?`\n\nWhat this installation knows (advice for this conversation, not authorization):\n${known}`:''}\n\nProject: ${title.value}\nProject type: ${projectType.value||'not chosen'}\nWorking directory: ${dir}`,text:goal.value.trim()})
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
    await postJson(`/api/chat/threads/${threadId.value}/messages`,{context:draftBackground,text:draftAsk()})
  } catch(e) {error.value=e instanceof Error?e.message:String(e);drafting.value=false;return}
  void finishThen(async()=>{drafting.value=false;await review()})
}
async function review() {
  busy.value=true;error.value=''
  try {
    const t=await getJson<ChatThreadDetail>(`/api/chat/threads/${threadId.value}`)
    if(t.busy || t.messages.some(m=>m.status==='running'||m.status==='pending_approval')) throw Error('Wait for the conversation to finish and resolve any pending approval first.')
    const response=[...t.messages].reverse().find(m=>m.role==='assistant'&&m.status==='done'&&m.text.trim())
    if(!response) throw Error('Ask the consultant to write the project summary first.')
    emit('review',{title:title.value.trim() || t.title.replace(/^Project consultant: /,''),brief:response.text,working_dir:t.working_dir,project_type:projectType.value||savedType(threadId.value)})
  } catch(e) {error.value=e instanceof Error?e.message:String(e)} finally {busy.value=false}
}
</script>
<template>
  <div class="consultant-entry"><button class="btn" :aria-expanded="open" @click="open=!open">{{open?'Hide project consultant':'Plan with chat'}}</button>
    <section v-if="open" class="consultant-glass" aria-labelledby="consultant-title">
      <h3 id="consultant-title">Project consultant</h3>
      <p>Shape the brief together, then review it before anything reaches planning. <RouterLink to="/help?topic=project-consultant">How-to</RouterLink></p>
      <p class="muted small">New chats: {{agent}} · {{model || 'its default model'}} · <RouterLink to="/profile#models-providers">Chat default</RouterLink></p>
      <NoteFold label="Route and billing"><p class="small">Free routes can throttle or time out. Membership routes use your native CLI account; API routes can incur charges. <RouterLink to="/help?topic=project-models">Model routes and billing</RouterLink>.</p></NoteFold>
      <p v-if="!available && !threadId" role="status">No chat route is available for the consultant. {{ chatRoutes.data.value?.empty_reason }} <RouterLink to="/profile#models-providers">Models &amp; providers</RouterLink> · <RouterLink to="/profile#agent-tools">Agent tools</RouterLink></p>
      <p v-else-if="!threadId" class="muted small">Uses {{ agent }} · {{ model || 'its default model' }} (the Chat default in <RouterLink to="/profile#models-providers">Models &amp; providers</RouterLink>).</p>
      <p v-if="error" role="alert">{{error}}</p>
      <p v-if="busy && threadId" role="status" class="muted">Sending your goal to the consultant…</p>
      <form v-if="!threadId" @submit.prevent="start">
        <label>Project name<input v-model="title" class="input" maxlength="200" required /></label>
        <label>Working directory<AppSelect v-model="workingDir" aria-label="Consultant working directory"><option value="">{{ scratchRoot ? 'Scratch folder (recommended)' : 'Profile or first allowed workspace' }}</option><option v-for="w in workdirs" :key="w.path" :value="w.path">{{ w.path === scratchRoot ? 'Scratch folder (new, private to the project)' : w.path }}</option></AppSelect></label>
        <label>Initial goal<textarea v-model="goal" class="input" rows="4" maxlength="12000" required /></label>
        <ProjectTypePicker v-model="projectType" :text="title + ' ' + goal" required @loaded="typeCount=$event" />
        <button class="btn primary" :disabled="busy || !available">Start consultant conversation</button>
      </form>
      <template v-else><p class="small muted">Conversation #{{threadId}} · route stays with this chat.</p><div class="conversation"><ChatConversation :thread-id="threadId" embedded @deleted="threadId=0; emit('started',0)" @back="open=false" /></div><p v-if="drafting" role="status" class="muted">Preparing your project summary…</p><div class="actions"><button class="btn primary" :disabled="busy || drafting" @click="draft">Review project summary</button><button class="btn" :disabled="busy || drafting" @click="review">Review existing brief</button></div><NoteFold label="Before submitting"><p class="small">The brief opens for you to edit. Nothing reaches the coordinator until you confirm there, and stories need a separate project approval before they run. Use Review existing brief when the last reply is already complete.</p><p class="small"><RouterLink to="/help?topic=project-consultant">Consultant how-to</RouterLink> · <RouterLink to="/help?topic=project-approvals">Project approvals</RouterLink></p></NoteFold></template>
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
