<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import PageHead from '@/components/PageHead.vue'
import ChatConversation from '@/components/ChatConversation.vue'
import ChipTag from '@/components/ChipTag.vue'
import NewChatDialog from '@/components/NewChatDialog.vue'
import IssueTaskDialog from '@/components/IssueTaskDialog.vue'
import { useNow } from '@/composables/useNow'
import { usePolledJson } from '@/composables/usePolledJson'
import type { ChatThread, ChatThreadsPayload } from '@/lib/api'
import { agentLabel, isCoordinatorAgent } from '@/lib/cards'
import { formatSince } from '@/lib/format'
import { navIcon } from '@/router/routes'
import { useGuideAction } from '@/composables/useGuideAction'

const route = useRoute()
const router = useRouter()
const now = useNow()

const { data, error, loaded, refresh } = usePolledJson<ChatThreadsPayload>('/api/chat/threads', 5000)

const threads = computed(() => data.value?.threads ?? [])
const showNew = ref(false)
const showIssueTask = ref(false)
useGuideAction('new', () => { showNew.value = true })

// The open thread lives in ?thread= so it can be linked to and survives a reload.
const selectedId = computed(() => {
  const raw = Array.isArray(route.query.thread) ? route.query.thread[0] : route.query.thread
  const n = Number(raw)
  return Number.isInteger(n) && n > 0 ? n : null
})

function open(id: number): void {
  void router.push({ query: { ...route.query, thread: String(id) } })
}

function close(): void {
  const { thread: _drop, ...rest } = route.query
  void router.push({ query: rest })
}

function onCreated(thread: ChatThread): void {
  showNew.value = false
  refresh()
  open(thread.id)
}

function onDeleted(): void {
  const { thread: _drop, ...rest } = route.query
  void router.replace({ query: rest })
  refresh()
}

function preview(t: ChatThread): string {
  const m = t.last_message
  if (!m) return 'No messages yet'
  const who = m.role === 'user' ? 'You: ' : ''
  return `${who}${m.text.replace(/\s+/g, ' ').trim() || '(empty)'}`
}
</script>

<template>
  <section class="page" aria-labelledby="chat-title">
    <PageHead id="chat-title" title="Chat" :icon="navIcon('chat')" sub="Talk to an agent." help="agent-chat">
      <button type="button" class="btn" @click="showIssueTask = true">Give Hermes an issue</button><button type="button" class="btn primary" @click="showNew = true"><AppIcon name="plus" />New chat</button>
    </PageHead>

    <div class="chat" :data-open="selectedId !== null ? 'true' : 'false'">
      <nav class="list" aria-label="Chat threads">
        <p v-if="error && !data" class="error-text pad" role="alert">Could not load chats: {{ error }}</p>
        <p v-else-if="!loaded" class="muted pad" role="status">Loading…</p>
        <p v-else-if="threads.length === 0" class="muted pad" data-testid="no-threads">
          No chats yet. Start one with New chat.
        </p>
        <ul v-if="threads.length" class="threads">
          <li v-for="t in threads" :key="t.id">
            <button
              type="button"
              class="thread"
              :aria-current="selectedId === t.id ? 'true' : undefined"
              :data-thread-id="t.id"
              @click="open(t.id)"
            >
              <span class="row">
                <span class="name">{{ t.title || 'Untitled chat' }}</span>
                <span v-if="t.busy" class="busy" data-testid="busy-dot" role="img" aria-label="Agent is working"></span>
              </span>
              <span class="row">
                <ChipTag tone="accent">{{ agentLabel(t.agent) }}</ChipTag>
                <ChipTag v-if="isCoordinatorAgent(t.agent)" tone="muted">Coordinator</ChipTag>
                <span class="muted small when">{{ formatSince(t.last_activity_at, now) }}</span>
              </span>
              <span class="muted small last">{{ preview(t) }}</span>
            </button>
          </li>
        </ul>
      </nav>

      <div class="pane">
        <ChatConversation
          v-if="selectedId !== null"
          :key="selectedId"
          :thread-id="selectedId"
          @back="close"
          @deleted="onDeleted"
          @changed="refresh"
        />
        <p v-else class="muted pad empty" data-testid="no-selection">Choose a chat on the left, or start a new one.</p>
      </div>
    </div>

    <NewChatDialog v-if="showNew" @close="showNew = false" @created="onCreated" />
    <IssueTaskDialog v-if="showIssueTask" @close="showIssueTask = false" @created="id => { showIssueTask = false; void router.push({ path: '/tasks', query: { card: String(id) } }) }" />
  </section>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
}

.chat {
  display: grid;
  grid-template-columns: var(--chat-list-width) minmax(0, 1fr);
  gap: var(--gap);
  height: var(--chat-height);
  min-height: var(--chat-min-height);
  background: var(--chat-glow);
}

.list,
.pane {
  min-width: 0;
  min-height: 0;
}

.list {
  overflow-y: auto;
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
}

.pad {
  margin: 0;
  padding: var(--gap);
}

.threads {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.thread {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  width: 100%;
  padding: var(--gap-sm) var(--gap);
  border: 0;
  border-bottom: 1px solid var(--panel-border);
  border-left: var(--severity-bar-width) solid transparent;
  background: transparent;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.thread:hover {
  background: var(--panel-raised);
}

.thread[aria-current='true'] {
  background: var(--accent-soft);
  border-left-color: var(--accent);
}

.thread:focus-visible {
  outline-offset: calc(-1 * var(--focus-ring-width));
}

.row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
}

.name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: var(--font-weight-strong);
}

.when {
  margin-left: auto;
  white-space: nowrap;
}

.last {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.busy {
  flex-shrink: 0;
  width: var(--busy-dot-size);
  height: var(--busy-dot-size);
  border-radius: var(--radius-pill);
  background: var(--accent);
  animation: pulse var(--pulse-duration) ease-in-out infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.25;
  }
}

@media (prefers-reduced-motion: reduce) {
  .busy {
    animation: none;
  }
}

@media (max-width: 767.98px) {
  .chat {
    display: block;
    height: auto;
    min-height: 0;
  }

  .chat[data-open='true'] .list,
  .chat[data-open='false'] .pane {
    display: none;
  }

  .chat[data-open='true'] .pane {
    height: var(--chat-height);
    min-height: var(--chat-min-height);
  }
}
@supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .list { background: var(--glass-panel); border-color: var(--glass-border); -webkit-backdrop-filter: blur(var(--glass-blur)); backdrop-filter: blur(var(--glass-blur)); box-shadow: var(--shadow); }
}
</style>
