<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ChipTag from '@/components/ChipTag.vue'
import ReportedValue from '@/components/ReportedValue.vue'
import type { ChatMessage, ChatMessageStatus } from '@/lib/api'
import type { Tone } from '@/lib/cards'
import { formatCount, formatDuration, formatSince, formatUsd } from '@/lib/format'

const props = defineProps<{
  message: ChatMessage
  /** True while an approve / reject request for this message is in flight. */
  deciding?: boolean
  /** Current time in epoch seconds, for the relative timestamp. */
  now: number
}>()

const emit = defineEmits<{ approve: [id: number]; reject: [id: number] }>()

const STATUS_CHIPS: Partial<Record<ChatMessageStatus, { label: string; tone: Tone }>> = {
  pending_approval: { label: 'Needs approval', tone: 'warn' },
  running: { label: 'Working', tone: 'accent' },
  failed: { label: 'Failed', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: 'warn' },
}

const isUser = computed(() => props.message.role === 'user')
const chip = computed(() => STATUS_CHIPS[props.message.status] ?? null)
const reasons = computed(() => props.message.approval_reasons.filter(Boolean))

// ---- copy ----
const copyState = ref<'idle' | 'copied' | 'unavailable'>('idle')
let copyTimer: ReturnType<typeof setTimeout> | null = null

function settle(next: 'copied' | 'unavailable'): void {
  copyState.value = next
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    copyState.value = 'idle'
  }, 3000)
}

async function copy(): Promise<void> {
  const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined
  if (!clipboard || typeof clipboard.writeText !== 'function') {
    settle('unavailable')
    return
  }
  try {
    await clipboard.writeText(props.message.text)
    settle('copied')
  } catch {
    settle('unavailable')
  }
}

onBeforeUnmount(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<template>
  <article
    class="msg"
    :data-role="message.role"
    :data-status="message.status"
    :data-message-id="message.id"
    :aria-label="isUser ? 'You said' : 'Agent replied'"
  >
    <div class="bubble">
      <div v-if="chip" class="chip-row">
        <ChipTag :tone="chip.tone">{{ chip.label }}</ChipTag>
      </div>
      <p class="text">{{ message.text || (message.status === 'failed' ? 'The agent did not return a reply.' : '') }}</p>

      <div v-if="message.status === 'pending_approval'" class="approval" data-testid="approval">
        <p class="approval-title has-icon"><AppIcon name="approval" />This message needs your approval before it runs.</p>
        <ul v-if="reasons.length" class="reasons" data-testid="approval-reasons">
          <li v-for="r in reasons" :key="r">{{ r }}</li>
        </ul>
        <div class="approval-actions">
          <button type="button" class="btn primary" :disabled="deciding" @click="emit('approve', message.id)">
            <AppIcon name="check" />
            Approve
          </button>
          <button type="button" class="btn danger" :disabled="deciding" @click="emit('reject', message.id)">
            <AppIcon name="close" />
            Reject
          </button>
        </div>
      </div>
    </div>

    <div v-if="!isUser" class="meta" data-testid="message-meta">
      <span class="meta-item">
        <AppIcon name="model" size="sm" /><span class="sr-only">Model</span>
        <ReportedValue :value="message.model" />
      </span>
      <span class="meta-item">
        <AppIcon name="tokens" size="sm" /><span class="k">in</span><span class="sr-only">tokens</span>
        <ReportedValue :value="message.input_tokens" :format="formatCount" />
      </span>
      <span class="meta-item">
        <AppIcon name="tokens" size="sm" /><span class="k">out</span><span class="sr-only">tokens</span>
        <ReportedValue :value="message.output_tokens" :format="formatCount" />
      </span>
      <span class="meta-item">
        <AppIcon name="cost" size="sm" /><span class="sr-only">Cost</span>
        <ReportedValue :value="message.cost_usd" :format="formatUsd" />
      </span>
      <span class="meta-item">
        <AppIcon name="clock" size="sm" /><span class="sr-only">Duration</span>
        <ReportedValue :value="message.duration_s" :format="formatDuration" />
      </span>
      <button type="button" class="copy" aria-label="Copy message" @click="copy">
        <AppIcon name="copy" size="sm" />
        {{ copyState === 'copied' ? 'Copied' : 'Copy' }}
      </button>
      <span v-if="copyState === 'unavailable'" class="muted copy-note" role="status" data-testid="copy-unavailable">
        Copying is not available in this browser. Select the text and copy it by hand.
      </span>
    </div>
    <div v-else class="meta user-meta">
      <span class="muted">{{ formatSince(message.created_at, now) }}</span>
    </div>
  </article>
</template>

<style scoped>
.msg {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  max-width: min(100%, var(--bubble-max-width));
  min-width: 0;
}

.msg[data-role='user'] {
  align-self: flex-end;
  align-items: flex-end;
}

.msg[data-role='assistant'] {
  align-self: flex-start;
  align-items: flex-start;
}

.bubble {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  max-width: 100%;
  padding: var(--gap-sm) var(--gap);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  background: var(--panel);
}

.msg[data-role='user'] .bubble {
  background: var(--accent-soft);
  border-color: var(--accent);
}

.msg[data-status='pending_approval'] .bubble {
  border-color: var(--warn);
  background: var(--warn-soft);
}

.msg[data-role='assistant'][data-status='failed'] .bubble,
.msg[data-role='user'][data-status='failed'] .bubble {
  border-color: var(--danger);
  background: var(--danger-soft);
}

.msg[data-status='cancelled'] .bubble {
  border-color: var(--warn);
  background: var(--warn-soft);
}

.chip-row {
  display: flex;
}

.text {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.approval {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.approval-title {
  margin: 0;
  font-weight: var(--font-weight-strong);
}

.reasons {
  margin: 0;
  padding-left: var(--gap-lg);
  font-size: var(--font-size-sm);
}

.approval-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-xs) var(--gap);
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-xs);
}

.k {
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.copy {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-xs);
  min-height: var(--touch-target);
  padding: 0 var(--gap-sm);
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  cursor: pointer;
}

.copy:hover {
  color: var(--text);
}

.copy-note {
  flex-basis: 100%;
}
</style>
