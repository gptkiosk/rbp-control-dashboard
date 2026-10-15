<script setup lang="ts">
import { ref, computed } from 'vue'
import ChatConversation from '@/components/ChatConversation.vue'
import AppSelect from '@/components/AppSelect.vue'
import { getJson, postJson, type ChatThread, type ChatThreadDetail } from '@/lib/api'
import type { Preferences } from '@/lib/profile'
const props = defineProps<{ preferences?: Preferences; workdirs: {path:string;branch:string|null}[]; available: boolean; resumeId?: number }>()
const emit = defineEmits<{ review: [draft:{title:string;brief:string;working_dir:string}]; started:[id:number] }>()
const open=ref(false), threadId=ref(props.resumeId || 0), title=ref(''), goal=ref(''), workingDir=ref(''), busy=ref(false), error=ref('')
const agent=computed(()=>props.preferences?.ai_agent || 'hermes')
const model=computed(()=>props.preferences?.ai_model || 'openrouter/free')
const guidance='You are a project consultant in a read-only planning conversation. Ask focused questions and refine the user’s goal collaboratively. Use what this installation knows (below) in the discussion: raise the delivery model, which agent runtimes are installed and the spending policy, the standards and their minimum risks, the methods and security practices that apply, and which kinds of model suit which work, and say plainly where something is unproven. Produce a Markdown project brief when asked, with Goal, Working directory, Approach and methods, Phases, Stories, Scope, Definitions of done, Risks and the standards areas they fall under, Security considerations, Model and route considerations (free or paid, and why), Dependencies, Constraints, and open questions, so the coordinator can plan from it directly. Keep the final brief below 20000 characters. Distinguish assumptions from confirmed requirements. Your output is a proposal for operator review and subsequent Hermes coordination. Stay within discussion and planning; leave all operational actions to the dashboard workflow.'
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
    await postJson(`/api/chat/threads/${threadId.value}/messages`,{text:`${guidance}${known?`\n\nWhat this installation knows (advice for this conversation, not authorization):\n${known}`:''}\n\nProject: ${title.value}\nWorking directory: ${dir}\nInitial goal: ${goal.value}`})
  } catch(e) {error.value=e instanceof Error?e.message:String(e)} finally {busy.value=false}
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
      <p>Talk through your goal, phases, scope, definitions of done and dependencies. Ask for a complete brief when ready, then review it and submit it to Hermes for coordination.</p>
      <p class="muted">New conversations use {{agent}} · {{model}}. Free OpenRouter is the default and can throttle or time out. Membership routes use your native CLI account; API routes can incur charges. <RouterLink to="/profile#ai-settings">Configure AI defaults</RouterLink> · <RouterLink to="/help?topic=project-consultant">Consultant help</RouterLink></p>
      <p v-if="!available && !threadId" role="status">The configured consultant runtime is unavailable. <RouterLink to="/profile#agent-tools">Install an agent runtime</RouterLink> or change AI defaults.</p>
      <p v-if="error" role="alert">{{error}}</p>
      <form v-if="!threadId" @submit.prevent="start">
        <label>Project name<input v-model="title" class="input" maxlength="200" required /></label>
        <label>Working directory<AppSelect v-model="workingDir" aria-label="Consultant working directory"><option value="">Profile or first allowed workspace</option><option v-for="w in workdirs" :key="w.path" :value="w.path">{{w.path}}</option></AppSelect></label>
        <label>Initial goal<textarea v-model="goal" class="input" rows="4" maxlength="12000" required /></label>
        <button class="btn primary" :disabled="busy || !available">Start consultant conversation</button>
      </form>
      <template v-else><p>Conversation #{{threadId}} keeps its original agent/model. Changed defaults apply to new conversations.</p><div class="conversation"><ChatConversation :thread-id="threadId" embedded @deleted="threadId=0; emit('started',0)" @back="open=false" /></div><button class="btn primary" :disabled="busy" @click="review">Review brief &amp; submit to Hermes</button><p class="muted">This opens an editable project review. Hermes coordination begins only after your confirmation; story execution requires its separate project approval.</p></template>
    </section>
  </div>
</template>
<style scoped>
.consultant-entry {margin-top:var(--gap);}
.consultant-glass {margin-top:var(--gap);padding:var(--gap-lg);background:var(--dialog-glass);backdrop-filter:blur(var(--glass-blur));border:1px solid var(--select-border);border-radius:var(--radius);display:flex;flex-direction:column;gap:var(--gap);}
form {display:flex;flex-direction:column;gap:var(--gap);}
.conversation {height:36rem;max-height:65vh;min-height:20rem;overflow:hidden;}
label {display:flex;flex-direction:column;gap:var(--gap-xs);}
</style>
