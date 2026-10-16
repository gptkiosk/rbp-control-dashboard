import { ref } from 'vue'
import { defineStore } from 'pinia'
export const useBugReportStore = defineStore('bugReport', () => {
  const open = ref(false)
  function show() { open.value = true }
  function close() { open.value = false }
  return { open, show, close }
})
