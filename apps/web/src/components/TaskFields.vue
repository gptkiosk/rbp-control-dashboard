<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import TagPill from '@/components/TagPill.vue'
import { PRIORITIES, MAX_TAGS, normalizeTag, type EstimateUnit } from '@/lib/cards'
import type { Priority } from '@/lib/api'
import { ref } from 'vue'
export interface TaskFieldValues {
  priority: Priority
  due_date: string
  estimate: string
  estimateUnit: EstimateUnit
  tags: string[]
  acceptance: string
}
const props = defineProps<{ modelValue: TaskFieldValues; prefix: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: TaskFieldValues] }>()
const draft = ref('')
const tagError = ref('')
function update<K extends keyof TaskFieldValues>(key: K, value: TaskFieldValues[K]): void {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
function addTag(): void {
  const tag = normalizeTag(draft.value)
  if (!tag) return
  if (!/^[a-z0-9][a-z0-9 &._-]{0,31}$/.test(tag)) {
    tagError.value = 'Tags use letters, numbers, spaces and & . _ -.'
    return
  }
  if (props.modelValue.tags.includes(tag)) {
    draft.value = ''
    return
  }
  if (props.modelValue.tags.length >= MAX_TAGS) {
    tagError.value = 'Use up to 10 tags.'
    return
  }
  update('tags', [...props.modelValue.tags, tag])
  draft.value = ''
  tagError.value = ''
}
</script>
<template>
  <div class="task-fields">
    <div class="field">
      <label :for="`${prefix}-priority`">Priority</label
      ><AppSelect
        :id="`${prefix}-priority`"
        class="input"
        :value="modelValue.priority"
        @change="update('priority', ($event.target as HTMLSelectElement).value as Priority)"
      >
        <option v-for="p in PRIORITIES" :key="p.id" :value="p.id">
          {{ p.label }}
        </option>
      </AppSelect>
    </div>
    <div class="field">
      <label :for="`${prefix}-due`">Due date</label
      ><input
        :id="`${prefix}-due`"
        class="input"
        type="date"
        :value="modelValue.due_date"
        @input="update('due_date', ($event.target as HTMLInputElement).value)"
      />
    </div>
    <div class="field">
      <label :for="`${prefix}-estimate`">Estimate</label>
      <div class="estimate">
        <input
          :id="`${prefix}-estimate`"
          class="input"
          type="number"
          min="0.01"
          step="any"
          :value="modelValue.estimate"
          @input="update('estimate', ($event.target as HTMLInputElement).value)"
        /><AppSelect
          class="input"
          :aria-label="`${prefix === 'nc' ? 'New task' : 'Task'} estimate unit`"
          :value="modelValue.estimateUnit"
          @change="update('estimateUnit', ($event.target as HTMLSelectElement).value as EstimateUnit)"
        >
          <option value="hours">Hours</option>
          <option value="minutes">Minutes</option>
        </AppSelect>
      </div>
    </div>
    <div class="field wide">
      <label :for="`${prefix}-tags`">Tags</label>
      <div class="tags">
        <TagPill v-for="tag in modelValue.tags" :key="tag" :tag="tag"
          >{{ tag
          }}<button
            type="button"
            class="remove-tag"
            :aria-label="`Remove tag ${tag}`"
            @click="
              update(
                'tags',
                modelValue.tags.filter((t) => t !== tag),
              )
            "
          >
            ×
          </button></TagPill
        >
      </div>
      <div class="estimate">
        <input
          :id="`${prefix}-tags`"
          v-model="draft"
          class="input"
          maxlength="32"
          placeholder="Add a tag"
          @keydown.enter.prevent="addTag"
          @keydown.esc.stop="draft = ''"
          @blur="addTag"
        /><button type="button" class="btn" @click="addTag">Add tag</button>
      </div>
      <p v-if="tagError" class="error-text" role="alert">{{ tagError }}</p>
    </div>
    <div class="field wide">
      <label :for="`${prefix}-acceptance`">Definition of done</label
      ><textarea
        :id="`${prefix}-acceptance`"
        class="input"
        maxlength="20000"
        placeholder="What must be true before this task is complete?"
        :value="modelValue.acceptance"
        @input="update('acceptance', ($event.target as HTMLTextAreaElement).value)"
      ></textarea>
    </div>
  </div>
</template>
<style scoped>
.task-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, var(--tile-min-width)), 1fr));
  gap: var(--gap);
}
.wide {
  grid-column: 1 / -1;
}
.estimate,
.tags {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
}
.tags {
  flex-wrap: wrap;
}
.estimate .input {
  min-width: 0;
}
.remove-tag {
  border: 0;
  padding: 0 var(--gap-xs);
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
</style>
