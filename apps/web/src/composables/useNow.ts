import { getCurrentInstance, onBeforeUnmount, ref } from 'vue'

/** One shared 1 s ticker for every live elapsed-time display; it only runs while something uses it. */
const nowS = ref(Date.now() / 1000)
let users = 0
let timer: ReturnType<typeof setInterval> | null = null

/** Current time in epoch seconds, refreshed every second while the calling component is mounted. */
export function useNow() {
  nowS.value = Date.now() / 1000
  users++
  if (timer === null) {
    timer = setInterval(() => {
      nowS.value = Date.now() / 1000
    }, 1000)
  }
  if (getCurrentInstance()) {
    onBeforeUnmount(() => {
      users--
      if (users <= 0 && timer !== null) {
        clearInterval(timer)
        timer = null
        users = 0
      }
    })
  }
  return nowS
}
