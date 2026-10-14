import { ref } from 'vue'
import { defineStore } from 'pinia'
export const useHelpStore = defineStore('help', () => {
  const open = ref(false)
  const topic = ref<string | null>(null)
  function show(id?: string) { topic.value = id ?? null; open.value = true }
  function close() { open.value = false; topic.value = null }
  return { open, topic, show, close }
})
