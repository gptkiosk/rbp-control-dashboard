import { afterEach, describe, expect, it } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import AppSelect from '@/components/AppSelect.vue'
import ModalShell from '@/components/ModalShell.vue'

afterEach(() => { document.body.innerHTML = '' })
const choices = '<option value="a" data-description="Agent a · Default">Orchestrator</option><option value="b" disabled>Offline agent</option><option value="c" data-description="Agent c">Developer</option>'

describe('Shared themed dropdown', () => {
  it('shows separated details and selects with the keyboard, skipping disabled options', async () => {
    const w = mount(AppSelect, { props: { id: 'agent', modelValue: 'a' }, slots: { default: choices }, attachTo: document.body })
    await flushPromises()
    expect(w.get('.selection-label').text()).toBe('Orchestrator')
    expect(w.get('.selection small').text()).toBe('Agent a · Default')
    const control = w.get('[role="combobox"]')
    await control.trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()
    expect(control.attributes('aria-expanded')).toBe('true')
    await control.trigger('keydown', { key: 'ArrowDown' })
    await control.trigger('keydown', { key: 'Enter' })
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['c'])
    expect((w.emitted('change')?.[0]?.[0] as Event).target).toBe(w.get('select').element)
    expect(control.attributes('aria-expanded')).toBe('false')
    w.unmount()
  })

  it('uses typeahead and closes on outside focus without changing the value', async () => {
    const w = mount(AppSelect, { props: { modelValue: 'a' }, slots: { default: choices }, attachTo: document.body })
    await flushPromises()
    await w.get('[role="combobox"]').trigger('keydown', { key: 'd' })
    await flushPromises()
    expect(w.get('.select-option.active').text()).toContain('Developer')
    document.body.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    await flushPromises()
    expect(w.get('[role="combobox"]').attributes('aria-expanded')).toBe('false')
    expect(w.emitted('update:modelValue')).toBeUndefined()
    w.unmount()
  })

  it('filters editable models, preserves custom IDs and supports menu selection', async () => {
    const Wrapper = defineComponent({ components: { AppSelect }, setup: () => ({ model: ref('') }),
      template: '<AppSelect v-model="model" editable><option value="claude-sonnet">Claude Sonnet</option><option value="gpt-sol">GPT Sol</option></AppSelect>' })
    const w = mount(Wrapper, { attachTo: document.body })
    await flushPromises()
    await w.get('input').setValue('custom-model')
    await flushPromises()
    expect(w.get('input').element.value).toBe('custom-model')
    expect(w.get('.select-empty').text()).toContain('ID you typed')
    await w.get('input').setValue('sol')
    await flushPromises()
    expect(w.findAll('[role="option"]')).toHaveLength(1)
    await w.get('input').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.get('input').element.value).toBe('gpt-sol')
    expect(w.get('input').attributes('aria-expanded')).toBe('false')
    w.unmount()
  })

  it('handles Escape in the menu before closing the enclosing dialog', async () => {
    const Wrapper = defineComponent({ components: { AppSelect, ModalShell }, setup: () => ({ closed: ref(false) }),
      template: '<ModalShell labelledby="title" @close="closed = true"><h2 id="title">Settings</h2><AppSelect id="agent" :model-value="\'a\'"><option value="a">Agent</option></AppSelect><span>{{ closed }}</span></ModalShell>' })
    const w = mount(Wrapper, { attachTo: document.body })
    await flushPromises()
    const control = w.get('[role="combobox"]')
    await control.trigger('click'); await flushPromises()
    await control.trigger('keydown', { key: 'Escape' })
    expect(control.attributes('aria-expanded')).toBe('false')
    expect(w.text()).toContain('false')
    await control.trigger('keydown', { key: 'Escape' })
    expect(w.text()).toContain('true')
    w.unmount()
  })

  it('selects inside a wrapping label without the label reopening the menu', async () => {
    const Wrapper = defineComponent({ components: { AppSelect }, setup: () => ({ value: ref('a') }),
      template: '<label for="agent">Agent<AppSelect id="agent" v-model="value"><option value="a">Orchestrator</option><option value="c">Developer</option></AppSelect></label>' })
    const w = mount(Wrapper, { attachTo: document.body })
    await flushPromises()
    await w.get('[role="combobox"]').trigger('click'); await flushPromises()
    await w.findAll('[role="option"]')[1]!.trigger('click'); await flushPromises()
    expect(w.get('.selection-label').text()).toBe('Developer')
    expect(w.get('[role="combobox"]').attributes('aria-expanded')).toBe('false')
    w.unmount()
  })

  it('retains native required validation, focuses the visible control and cannot open disabled controls', async () => {
    const w = mount(AppSelect, { props: { id: 'required-agent', modelValue: '', required: true }, slots: { default: '<option value="">Choose</option>' }, attachTo: document.body })
    await flushPromises()
    expect((w.get('select').element as HTMLSelectElement).checkValidity()).toBe(false)
    await flushPromises()
    expect(document.activeElement).toBe(w.get('[role="combobox"]').element)
    await w.setProps({ disabled: true })
    await w.get('[role="combobox"]').trigger('keydown', { key: 'ArrowDown' })
    expect(w.get('[role="combobox"]').attributes('aria-expanded')).toBe('false')
    w.unmount()
  })
})
