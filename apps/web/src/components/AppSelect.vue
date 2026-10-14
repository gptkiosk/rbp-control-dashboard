<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, onUpdated, ref, useAttrs, useId, watch, type StyleValue } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  id?: string
  modelValue?: string | number | null
  value?: string | number | null
  disabled?: boolean
  required?: boolean
  editable?: boolean
  placeholder?: string
}>(), { placeholder: 'Choose an option…' })
const emit = defineEmits<{
  'update:modelValue': [value: string | number]
  change: [event: Event]
}>()
const attrs = useAttrs()
const uid = useId()
const controlId = computed(() => props.id || `select-${uid}`)
const menuId = `select-menu-${uid}`
const controlAttrs = computed(() => Object.fromEntries(
  Object.entries(attrs).filter(([key]) => !['class', 'style', 'name', 'list'].includes(key)),
))
const root = ref<HTMLElement | null>(null)
const control = ref<HTMLElement | null>(null)
const native = ref<HTMLSelectElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const active = ref(-1)
const filter = ref('')
const placement = ref<Record<string, string>>({})
const selectedValue = computed(() => props.modelValue !== undefined ? props.modelValue : props.value)
type Option = { value: string; raw: string | number; label: string; detail: string; disabled: boolean }
const options = ref<Option[]>([])
const selected = computed(() => options.value.find(o => o.value === String(selectedValue.value ?? '')))
const visible = computed(() => !props.editable || !filter.value ? options.value : options.value.filter(o =>
  `${o.label} ${o.detail}`.toLowerCase().includes(filter.value.toLowerCase()),
))
const activeId = computed(() => open.value && active.value >= 0 ? `${menuId}-${active.value}` : undefined)

/** Read slot options so existing typed values, form validation and change handlers stay intact. */
function syncOptions() {
  const next = Array.from(native.value?.options ?? []).map(o => {
    const text = o.textContent?.replace(/\s+/g, ' ').trim() || o.value
    const [label, ...rest] = text.split(' · ')
    return {
      value: o.value, raw: (o as HTMLOptionElement & { _value?: string | number })._value ?? o.value,
      label: o.getAttribute('data-label') || label || text,
      detail: o.getAttribute('data-description') || rest.join(' · '),
      disabled: o.disabled || (o.parentElement instanceof HTMLOptGroupElement && o.parentElement.disabled),
    }
  })
  if (JSON.stringify(next) !== JSON.stringify(options.value)) options.value = next
}
function positionMenu() {
  if (!control.value || !menu.value) return
  const rect = control.value.getBoundingClientRect()
  const gap = parseFloat(getComputedStyle(menu.value).getPropertyValue('--select-edge')) || 8
  const preferred = parseFloat(getComputedStyle(menu.value).maxHeight) || 288
  const below = innerHeight - rect.bottom - gap * 2
  const above = rect.top - gap * 2
  const upwards = below < preferred && above > below
  const height = Math.max(0, Math.min(preferred, upwards ? above : below))
  const width = Math.min(Math.max(rect.width, parseFloat(getComputedStyle(menu.value).minWidth) || rect.width), innerWidth - gap * 2)
  placement.value = {
    left: `${Math.max(gap, Math.min(rect.left, innerWidth - width - gap))}px`,
    top: `${upwards ? rect.top - gap : rect.bottom + gap}px`,
    transform: upwards ? 'translateY(-100%)' : 'none',
    width: `${width}px`, maxHeight: `${height}px`,
  }
}
async function show() {
  if (props.disabled || open.value) return
  open.value = true
  active.value = visible.value.findIndex(o => o.value === String(selectedValue.value ?? '') && !o.disabled)
  if (active.value < 0) active.value = visible.value.findIndex(o => !o.disabled)
  await nextTick()
  if (!open.value) return
  positionMenu()
  if (menu.value?.showPopover) menu.value.showPopover()
  await nextTick()
  revealActive()
}
function close() {
  if (!open.value) return
  if (menu.value?.hidePopover && menu.value.matches(':popover-open')) menu.value.hidePopover()
  open.value = false
  active.value = -1
  filter.value = ''
}
function toggle() {
  const wasOpen = open.value
  control.value?.focus()
  if (wasOpen) close()
  else { filter.value = ''; void show() }
}
function nativeChanged(event: Event) {
  const option = options.value.find(o => o.value === native.value?.value)
  emit('update:modelValue', option?.raw ?? native.value?.value ?? '')
  emit('change', event)
}
function choose(index: number) {
  const option = visible.value[index]
  if (!option || option.disabled || props.disabled) return
  if (props.editable) emit('update:modelValue', option.raw)
  else if (native.value) {
    native.value.value = option.value
    native.value.dispatchEvent(new Event('change', { bubbles: true }))
  }
  control.value?.focus()
  close()
}
function typed(event: Event) {
  const value = (event.target as HTMLInputElement).value
  emit('update:modelValue', value)
  filter.value = value
  active.value = visible.value.findIndex(o => !o.disabled)
  void show()
}
function move(direction: number, edge = false) {
  if (!visible.value.length) return
  let index = edge ? direction > 0 ? -1 : visible.value.length : active.value
  for (let i = 0; i < visible.value.length; i++) {
    index = (index + direction + visible.value.length) % visible.value.length
    if (!visible.value[index]!.disabled) { active.value = index; break }
  }
}
let typeahead = ''
let typedAt = 0
function keydown(event: KeyboardEvent) {
  if (props.disabled) return
  if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); close(); return }
  if (event.key === 'Tab') { close(); return }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) void show()
    else move(event.key === 'ArrowDown' ? 1 : -1)
  } else if (open.value && ['Home', 'End'].includes(event.key) && !props.editable) {
    event.preventDefault(); move(event.key === 'Home' ? 1 : -1, true)
  } else if (event.key === 'Enter' || (event.key === ' ' && !props.editable)) {
    if (open.value) { event.preventDefault(); if (active.value >= 0) choose(active.value); else close() }
    else if (!props.editable) { event.preventDefault(); void show() }
  } else if (!props.editable && event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault()
    typeahead = Date.now() - typedAt > 700 ? event.key : typeahead + event.key
    typedAt = Date.now()
    void show()
    const needle = typeahead.toLowerCase()
    const prefix = visible.value.findIndex(o => !o.disabled && o.label.toLowerCase().startsWith(needle))
    const found = prefix >= 0 ? prefix : visible.value.findIndex(o => !o.disabled && `${o.label} ${o.detail}`.toLowerCase().includes(needle))
    if (found >= 0) active.value = found
  }
}
function revealActive() {
  menu.value?.querySelectorAll('[role="option"]')[active.value]?.scrollIntoView?.({ block: 'nearest' })
}
watch(active, () => { if (open.value) void nextTick(revealActive) })
watch(() => props.disabled, value => { if (value) close() })
watch(visible, values => {
  if (active.value >= values.length || values[active.value]?.disabled) active.value = values.findIndex(o => !o.disabled)
})
function outside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) close() }
function focused(event: FocusEvent) { if (!root.value?.contains(event.target as Node)) close() }
function scrolled(event: Event) { if (!menu.value?.contains(event.target as Node)) close() }
function invalid(event: Event) { event.preventDefault(); control.value?.focus(); void show() }
onMounted(() => {
  syncOptions()
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', focused)
  window.addEventListener('scroll', scrolled, true)
  window.addEventListener('resize', close)
})
onUpdated(syncOptions)
onBeforeUnmount(() => {
  close()
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('focusin', focused)
  window.removeEventListener('scroll', scrolled, true)
  window.removeEventListener('resize', close)
})
</script>

<template>
  <div ref="root" class="themed-select" :class="attrs.class" :style="attrs.style as StyleValue" :data-select-open="open">
    <input v-if="editable" :id="controlId" ref="control" v-bind="controlAttrs" class="select-control select-editable"
      role="combobox" type="text" autocomplete="off" :value="selectedValue" :disabled="disabled" :required="required"
      :placeholder="placeholder" :aria-expanded="open" :aria-controls="menuId" :aria-activedescendant="activeId" aria-autocomplete="list"
      @focus="show" @click="show" @input="typed" @keydown="keydown" />
    <button v-else :id="controlId" ref="control" v-bind="controlAttrs" type="button" class="select-control" role="combobox"
      :disabled="disabled" :aria-required="required || undefined" :aria-expanded="open" :aria-controls="menuId"
      :aria-activedescendant="activeId" aria-haspopup="listbox" @click="toggle" @keydown="keydown">
      <span class="selection"><span class="selection-label">{{ selected?.label || placeholder }}</span><small v-if="selected?.detail">{{ selected.detail }}</small></span>
      <AppIcon name="chevron-down" class="select-chevron" />
    </button>
    <button v-if="editable" type="button" class="editable-toggle" tabindex="-1" aria-hidden="true" :disabled="disabled" @click="toggle"><AppIcon name="chevron-down" /></button>
    <select :id="`${controlId}-native`" ref="native" hidden aria-hidden="true" tabindex="-1"
      :name="editable ? undefined : attrs.name as string" :value="selectedValue" :disabled="disabled || editable" :required="required && !editable"
      @change="nativeChanged" @invalid="invalid" @focus="control?.focus()"><slot /></select>
    <div v-show="open" :id="menuId" ref="menu" class="select-menu" popover="manual" role="listbox"
      :aria-label="String(attrs['aria-label'] || 'Options')" :style="placement" @pointerdown.prevent>
      <div v-for="(option, index) in visible" :id="`${menuId}-${index}`" :key="option.value" class="select-option" role="option"
        :aria-selected="option.value === String(selectedValue ?? '')" :aria-disabled="option.disabled || undefined"
        :class="{ active: index === active, unavailable: option.disabled }" @pointermove="!option.disabled && (active = index)" @click.prevent.stop="choose(index)">
        <span class="option-copy"><span>{{ option.label }}</span><small v-if="option.detail">{{ option.detail }}</small></span>
        <AppIcon v-if="option.value === String(selectedValue ?? '')" name="check" />
      </div>
      <p v-if="!visible.length" class="select-empty">{{ editable ? 'No matching models. You can use the ID you typed.' : 'No options available.' }}</p>
    </div>
  </div>
</template>

<style scoped>
.themed-select { position: relative; min-width: 0; width: 100%; }
.themed-select.input { padding: 0; border: 0; background: transparent; }
.select-control { width: 100%; min-width: 0; min-height: var(--select-height); display: flex; align-items: center; justify-content: space-between; gap: var(--gap); padding: var(--gap-sm) var(--gap); border: 1px solid var(--select-border); border-radius: var(--radius); background: var(--select-bg); color: var(--text); font: inherit; font-size: var(--font-size); line-height: var(--line-height); text-align: left; cursor: pointer; transition: border-color var(--transition), background var(--transition); }
.select-control:hover:not(:disabled), .themed-select[data-select-open='true'] .select-control { border-color: var(--accent); background: var(--select-hover); }
.select-control:disabled { opacity: var(--disabled-opacity); cursor: not-allowed; }
.selection, .option-copy { min-width: 0; display: flex; flex-direction: column; gap: var(--gap-xs); }
.selection-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selection small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
small { color: var(--text-muted); font-size: var(--font-size-xs); }
.select-chevron { color: var(--accent); transition: transform var(--transition); }
[data-select-open='true'] .select-chevron { transform: rotate(180deg); }
.select-editable { padding-right: var(--select-toggle-width); cursor: text; }
.editable-toggle { position: absolute; right: 0; top: 0; bottom: 0; width: var(--select-toggle-width); display: flex; align-items: center; justify-content: center; border: 0; border-radius: var(--radius); background: transparent; color: var(--accent); cursor: pointer; }
.select-menu { --select-edge: var(--select-menu-edge); position: fixed; inset: auto; margin: 0; min-width: var(--select-menu-min-width); max-height: var(--select-menu-max-height); padding: var(--gap-xs); overflow-y: auto; overscroll-behavior: contain; background: var(--select-menu-bg); border: 1px solid var(--select-border); border-radius: var(--radius); color: var(--text); box-shadow: var(--shadow); -webkit-backdrop-filter: blur(var(--glass-blur)); backdrop-filter: blur(var(--glass-blur)); z-index: var(--z-select); }
.select-option { display: flex; align-items: center; justify-content: space-between; gap: var(--gap); padding: var(--gap-sm) var(--gap); min-height: var(--touch-target); border-radius: var(--radius-sm); font-size: var(--font-size); cursor: pointer; }
.option-copy { overflow-wrap: anywhere; }
.select-option.active { background: var(--accent-soft); }
.select-option[aria-selected='true'] { color: var(--accent); }
.select-option.unavailable { opacity: var(--disabled-opacity); cursor: not-allowed; }
.select-empty { padding: var(--gap); margin: 0; color: var(--text-muted); font-size: var(--font-size-sm); }
@supports not (backdrop-filter: blur(1px)) { .select-menu { background: var(--panel-raised); } }
</style>
