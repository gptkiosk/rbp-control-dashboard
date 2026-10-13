<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

withDefaults(
  defineProps<{
    /** id of the element that names the dialog. */
    labelledby: string
    variant?: 'dialog' | 'drawer' | 'help'
  }>(),
  { variant: 'dialog' },
)

const emit = defineEmits<{ close: [] }>()

const panel = ref<HTMLElement | null>(null)
let opener: HTMLElement | null = null

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables(): HTMLElement[] {
  return Array.from(panel.value?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []).filter(
    (el) => !el.hasAttribute('hidden') && el.getAttribute('aria-hidden') !== 'true',
  )
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    // An open combobox consumes Escape first; the next Escape closes the dialog.
    if (e.target instanceof HTMLElement && e.target.closest('[data-select-open="true"]')) return
    e.stopPropagation()
    emit('close')
    return
  }
  if (e.key !== 'Tab' || !panel.value) return
  const items = focusables()
  if (items.length === 0) {
    e.preventDefault()
    panel.value.focus()
    return
  }
  const first = items[0]!
  const last = items[items.length - 1]!
  const active = document.activeElement
  if (e.shiftKey && (active === first || !panel.value.contains(active))) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && (active === last || !panel.value.contains(active))) {
    e.preventDefault()
    first.focus()
  }
}

onMounted(() => {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  document.addEventListener('keydown', onKeydown, true)
  const autofocus = panel.value?.querySelector<HTMLElement>('[data-autofocus]')
  ;(autofocus ?? panel.value)?.focus()
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown, true)
  if (opener && document.contains(opener)) opener.focus()
})
</script>

<template>
  <div class="modal-root" :data-variant="variant">
    <div class="backdrop" aria-hidden="true" @click="emit('close')"></div>
    <div
      ref="panel"
      class="modal-panel"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="labelledby"
      tabindex="-1"
    >
      <slot />
    </div>
  </div>
</template>

<style scoped>
.modal-root {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  justify-content: center;
  align-items: center;
  padding: var(--gap);
}

.backdrop {
  position: absolute;
  inset: 0;
  background: var(--overlay);
}

.modal-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  background: var(--dialog-glass);
  border: 1px solid var(--select-border);
  border-radius: var(--dialog-radius);
  -webkit-backdrop-filter: blur(var(--glass-blur));
  backdrop-filter: blur(var(--glass-blur));
  box-shadow: var(--shadow);
  overflow-y: auto;
}

.modal-root[data-variant='dialog'] .modal-panel {
  max-width: var(--dialog-width);
  max-height: 100%;
}

.modal-root[data-variant='drawer'] {
  justify-content: flex-end;
  align-items: stretch;
  padding: 0;
}

.modal-root[data-variant='drawer'] .modal-panel {
  max-width: var(--drawer-width);
  border-radius: 0;
  border-top: 0;
  border-bottom: 0;
  border-right: 0;
}

.modal-root[data-variant='help'] { justify-content: flex-end; align-items: flex-end; }
.modal-root[data-variant='help'] .modal-panel { max-width: var(--help-chat-width); height: var(--help-chat-height); max-height: 100%; overflow: hidden; }

.modal-panel:focus-visible {
  outline-offset: calc(-1 * var(--focus-ring-width));
}

.modal-panel :deep(header .section-title) {
  font-size: var(--font-size-xl);
}

.modal-panel :deep(.input:not(.themed-select)) {
  min-height: var(--select-height);
  background: var(--glass-bg);
  border-color: var(--select-border);
}

.modal-panel :deep(.btn:not(.primary):not(.danger)) {
  background: var(--glass-bg);
  border-color: var(--select-border);
}

.modal-panel :deep(.btn.primary) {
  background: var(--dialog-action);
}

@supports not (backdrop-filter: blur(1px)) {
  .modal-panel { background: var(--panel-raised); }
}

@media (max-width: 767.98px) {
  .modal-root {
    padding: 0;
  }

  .modal-root[data-variant='dialog'] .modal-panel,
  .modal-root[data-variant='drawer'] .modal-panel,
  .modal-root[data-variant='help'] .modal-panel {
    max-width: none;
    max-height: none;
    height: 100%;
    border-radius: 0;
    border: 0;
  }
}
</style>
