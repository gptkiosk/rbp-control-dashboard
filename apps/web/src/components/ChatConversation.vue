<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ChatBubble from '@/components/ChatBubble.vue'
import ChatLive from '@/components/ChatLive.vue'
import ChipTag from '@/components/ChipTag.vue'
import { useNow } from '@/composables/useNow'
import { usePolledJson } from '@/composables/usePolledJson'
import { deleteJson, postJson, type ChatMessage, type ChatThreadDetail } from '@/lib/api'
import { agentLabel, isManagerAgent } from '@/lib/cards'

const props = defineProps<{ threadId: number; embedded?: boolean }>()
const emit = defineEmits<{ back: []; deleted: [id: number]; changed: [] }>()

/** Poll quickly while the agent is working or a message awaits a decision, slowly otherwise. */
const FAST_MS = 2000
const SLOW_MS = 10000
/** How close to the bottom (px) still counts as "following" the conversation. */
const FOLLOW_SLACK_PX = 48

const now = useNow()
const fast = ref(false)
const { data, error, loaded, refresh } = usePolledJson<ChatThreadDetail>(
  () => `/api/chat/threads/${props.threadId}`,
  () => (fast.value ? FAST_MS : SLOW_MS),
)

const messages = computed<ChatMessage[]>(() => data.value?.messages ?? [])
const runningMessage = computed(() => messages.value.find((m) => m.role === 'user' && m.status === 'running') ?? null)
const pendingMessage = computed(() => messages.value.find((m) => m.status === 'pending_approval') ?? null)
const busy = computed(() => !!data.value && (data.value.busy || messages.value.some((m) => m.status === 'running')))

watch(
  [busy, pendingMessage],
  () => {
    fast.value = busy.value || !!pendingMessage.value
  },
  { immediate: true },
)

// Tell the list the moment a turn finishes, so its preview and busy dot do not lag behind.
watch(busy, (isBusy, was) => {
  if (was && !isBusy) emit('changed')
})

const composerReason = computed(() => {
  if (pendingMessage.value) return 'A message is waiting for your approval. Approve or reject it to continue.'
  if (busy.value) return 'The agent is answering. You can send again when it finishes.'
  return null
})

// ---- auto-scroll ----
const scroller = ref<HTMLElement | null>(null)
const following = ref(true)

function onScroll(): void {
  const el = scroller.value
  if (!el) return
  following.value = el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_SLACK_PX
}

function toBottom(): void {
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
  following.value = true
}

async function followIfPinned(): Promise<void> {
  if (!following.value) return
  await nextTick()
  toBottom()
}

watch(
  () => {
    const last = messages.value[messages.value.length - 1]
    return [messages.value.length, last?.status, last?.text.length]
  },
  followIfPinned,
)
watch(loaded, followIfPinned)
onMounted(followIfPinned)

// ---- actions ----
const draft = ref('')
const sending = ref(false)
const deciding = ref<number | null>(null)
const stopping = ref(false)
const deleting = ref(false)
const actionError = ref<string | null>(null)

const canSend = computed(
  () => !!data.value && !composerReason.value && !sending.value && draft.value.trim().length > 0,
)

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** Merge a message the server just returned into the open thread so the UI moves before the next poll. */
function adopt(updated: ChatMessage): void {
  const d = data.value
  if (!d) return
  const exists = d.messages.some((m) => m.id === updated.id)
  const next = exists ? d.messages.map((m) => (m.id === updated.id ? updated : m)) : [...d.messages, updated]
  data.value = { ...d, busy: d.busy || updated.status === 'running', messages: next }
}

async function send(): Promise<void> {
  if (!canSend.value) return
  const text = draft.value.trim()
  sending.value = true
  actionError.value = null
  try {
    const sent = await postJson<ChatMessage>(`/api/chat/threads/${props.threadId}/messages`, { text })
    draft.value = ''
    following.value = true
    adopt(sent)
    refresh()
    emit('changed')
  } catch (e) {
    actionError.value = message(e)
  } finally {
    sending.value = false
  }
}

function onComposerKey(e: KeyboardEvent): void {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return
  e.preventDefault()
  void send()
}

async function decide(id: number, verb: 'approve' | 'reject'): Promise<void> {
  if (deciding.value !== null) return
  deciding.value = id
  actionError.value = null
  try {
    adopt(await postJson<ChatMessage>(`/api/chat/messages/${id}/${verb}`))
    refresh()
    emit('changed')
  } catch (e) {
    actionError.value = message(e)
  } finally {
    deciding.value = null
  }
}

async function stop(): Promise<void> {
  if (stopping.value) return
  stopping.value = true
  actionError.value = null
  try {
    await postJson(`/api/chat/threads/${props.threadId}/stop`)
    refresh()
    emit('changed')
  } catch (e) {
    actionError.value = message(e)
  } finally {
    stopping.value = false
  }
}

async function remove(): Promise<void> {
  const t = data.value
  if (!t || busy.value || deleting.value) return
  if (!window.confirm(`Delete "${t.title}" and its messages? This cannot be undone.`)) return
  deleting.value = true
  actionError.value = null
  try {
    await deleteJson(`/api/chat/threads/${t.id}`)
    emit('deleted', t.id)
  } catch (e) {
    actionError.value = message(e)
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <section class="convo" aria-label="Conversation">
    <p v-if="error && !data" class="error-text pad" role="alert">
      Could not load this chat: {{ error }}
      <button type="button" class="btn back-inline" @click="emit('back')">
        <AppIcon name="back" />
        Back to chats
      </button>
    </p>
    <p v-else-if="!loaded" class="muted pad" role="status">Loading…</p>

    <template v-if="data"><p v-if="!embedded" class="muted small pad">New AI chats default to OpenRouter free. <RouterLink to="/profile#ai-settings">Configure AI defaults</RouterLink> · <RouterLink to="/help?topic=project-consultant">Model settings help</RouterLink>. This conversation keeps its selected route.</p>
      <header class="head">
        <button type="button" class="btn back" @click="emit('back')">
          <AppIcon name="back" />
          Back
        </button>
        <div class="title-row">
          <h2 class="section-title title">{{ data.title || 'Untitled chat' }}</h2>
          <button
            type="button"
            class="btn danger"
            :disabled="busy || deleting"
            :title="busy ? 'Wait for the agent to finish before deleting' : undefined"
            @click="remove"
          >
            <AppIcon name="trash" />
            Delete thread
          </button>
        </div>
        <div class="chips">
          <ChipTag tone="accent">{{ agentLabel(data.agent) }}</ChipTag>
          <ChipTag v-if="isManagerAgent(data.agent)" tone="muted">Manager</ChipTag>
          <ChipTag :tone="data.mode === 'edit' ? 'warn' : 'muted'">{{ data.mode === 'edit' ? 'Edit' : 'Read' }}</ChipTag>
          <span class="has-icon-inline small"><AppIcon name="model" size="sm" />{{ data.model ?? 'default' }}</span>
        </div>
        <p class="facts muted small">
          <span class="mono wrap" data-testid="working-dir">{{ data.working_dir }}</span>
          <span class="mono wrap" data-testid="session-id">{{ data.session_id ?? 'new session' }}</span>
        </p>
      </header>

      <div class="scroller-wrap">
        <div ref="scroller" class="scroller" role="log" aria-label="Messages" tabindex="0" @scroll="onScroll">
          <p v-if="messages.length === 0" class="muted empty">No messages yet. Say something below.</p>
          <template v-for="m in messages" :key="m.id">
            <ChatBubble
              :message="m"
              :now="now"
              :deciding="deciding === m.id"
              @approve="decide($event, 'approve')"
              @reject="decide($event, 'reject')"
            />
            <ChatLive
              v-if="runningMessage && m.id === runningMessage.id && m.run_id != null"
              :key="`live-${m.run_id}`"
              :run-id="m.run_id"
              :stopping="stopping"
              @stop="stop"
              @grew="followIfPinned"
              @finished="refresh"
            />
          </template>
        </div>
        <button v-if="!following" type="button" class="btn jump" @click="toBottom">Jump to latest</button>
      </div>

      <form class="composer" @submit.prevent="send">
        <p v-if="actionError" class="error-text" role="alert" data-testid="action-error">{{ actionError }}</p>
        <p v-if="composerReason" id="composer-reason" class="hint" role="status" data-testid="composer-reason">
          {{ composerReason }}
        </p>
        <div class="composer-row">
          <label for="composer-text" class="sr-only">Message</label>
          <textarea
            id="composer-text"
            v-model="draft"
            class="input"
            rows="2"
            placeholder="Message the agent. Enter sends, Shift+Enter adds a line."
            :disabled="!!composerReason"
            :aria-describedby="composerReason ? 'composer-reason' : undefined"
            @keydown="onComposerKey"
          ></textarea>
          <button type="submit" class="btn primary" :disabled="!canSend">
            <AppIcon name="send" />
            {{ sending ? 'Sending…' : 'Send' }}
          </button>
        </div>
      </form>
    </template>
  </section>
</template>

<style scoped>
.convo {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-width: 0;
  min-height: 0;
  height: 100%;
}

.pad {
  margin: 0;
  padding: var(--gap);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--gap-sm);
}

.head {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.back {
  align-self: flex-start;
}

.title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
  flex-wrap: wrap;
}

.title {
  min-width: 0;
  overflow-wrap: anywhere;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

.facts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs) var(--gap);
  margin: 0;
}

.wrap {
  overflow-wrap: anywhere;
}

.scroller-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}

.scroller {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap);
  overflow-y: auto;
  background: var(--bg);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
}

.empty {
  margin: auto;
}

.jump {
  position: absolute;
  right: var(--gap);
  bottom: var(--gap);
}

.composer {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.composer p {
  margin: 0;
}

.composer-row {
  display: flex;
  align-items: flex-end;
  gap: var(--gap-sm);
}

.composer-row textarea {
  flex: 1;
  min-height: var(--touch-target);
  max-height: var(--composer-max-height);
  field-sizing: content;
}

.back-inline {
  margin-top: var(--gap-xs);
}

@media (min-width: 768px) {
  .back {
    display: none;
  }
}
@supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .scroller { background: var(--glass-bg); border-color: var(--glass-border); -webkit-backdrop-filter: blur(var(--glass-blur)); backdrop-filter: blur(var(--glass-blur)); box-shadow: var(--shadow); }
  .composer { background: var(--glass-panel); border: 1px solid var(--glass-border); padding: var(--gap-sm); border-radius: var(--radius); -webkit-backdrop-filter: blur(var(--glass-blur)); backdrop-filter: blur(var(--glass-blur)); }
}
</style>
