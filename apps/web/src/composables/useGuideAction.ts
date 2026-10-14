import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

/** Help links can open a form, never submit it. Consume the action so Cancel stays closed. */
export function useGuideAction(action: string, open: () => void) {
  const route = useRoute()
  const router = useRouter()
  watch(() => route.query.action, value => {
    if (value !== action) return
    open()
    const { action: _drop, ...query } = route.query
    void router.replace({ path: route.path, query, hash: route.hash })
  }, { immediate: true, flush: 'post' })
}
