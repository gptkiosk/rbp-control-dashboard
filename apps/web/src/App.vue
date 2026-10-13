<script setup lang="ts">
import { nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppSidebar from '@/components/AppSidebar.vue'
import TopBar from '@/components/TopBar.vue'
import AppFooter from '@/components/AppFooter.vue'
import { useHealthStore } from '@/stores/health'
import { useAuthStore } from '@/stores/auth'
import LoginGate from '@/components/LoginGate.vue'
import HelpChat from '@/components/HelpChat.vue'
import SetupPrompt from '@/components/SetupPrompt.vue'
import { useThemeStore } from '@/stores/theme'
import { getJson } from '@/lib/api'
import type { Profile } from '@/lib/profile'

const health = useHealthStore()
const auth = useAuthStore()
const route = useRoute()
const menuOpen = ref(false)
const theme = useThemeStore()
watch(() => auth.user?.email, async email => {
  if (!email || auth.user?.method !== 'google') return
  try {
    const p = await getJson<Profile>('/api/profile')
    if (auth.user?.email === email && p.preferences.theme !== 'system') theme.choose(p.preferences.theme)
  } catch { /* Device theme works while the profile is unavailable. */ }
})

watch(() => route.fullPath, () => {
  menuOpen.value = false
})

// The shell owns scrolling, so native window hash scrolling does not reach these sections.
watch([() => route.fullPath, () => auth.access], async (_, _previous, onCleanup) => {
  let cancelled = false
  let observer: MutationObserver | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let layoutObserver: ResizeObserver | undefined
  let settleTimer: ReturnType<typeof setTimeout> | undefined
  let layoutTimer: ReturnType<typeof setTimeout> | undefined
  const stopLayout = () => {
    layoutObserver?.disconnect()
    if (settleTimer) clearTimeout(settleTimer)
    if (layoutTimer) clearTimeout(layoutTimer)
    for (const event of ['wheel', 'touchstart', 'pointerdown', 'keydown']) document.removeEventListener(event, stopLayout, true)
  }
  onCleanup(() => { cancelled = true; observer?.disconnect(); if (timer) clearTimeout(timer); stopLayout() })
  await nextTick()
  if (cancelled || !auth.access) return
  const id = route.hash.slice(1)
  function locate() {
    const target = id ? document.getElementById(id) : document.getElementById('main-content')
    if (!target) return false
    target.scrollIntoView?.({ block: 'start' })
    if (id) {
      if (!target.matches('button, input, textarea, a[href], select')) target.setAttribute('tabindex', '-1')
      target.focus({ preventScroll: true })
      // Live data above the section can change its position after the first render.
      // Follow that initial layout briefly, stopping as soon as the operator interacts.
      const content = document.getElementById('main-content')
      if (content && typeof ResizeObserver !== 'undefined') {
        layoutObserver = new ResizeObserver(() => {
          target.scrollIntoView?.({ block: 'start' })
          if (settleTimer) clearTimeout(settleTimer)
          settleTimer = setTimeout(stopLayout, 1500)
        })
        layoutObserver.observe(content)
        layoutTimer = setTimeout(stopLayout, 10000)
        for (const event of ['wheel', 'touchstart', 'pointerdown', 'keydown']) document.addEventListener(event, stopLayout, true)
      }
    }
    observer?.disconnect()
    if (timer) clearTimeout(timer)
    return true
  }
  if (!locate() && id) {
    observer = new MutationObserver(locate)
    observer.observe(document.getElementById('main-content') ?? document.body, { childList: true, subtree: true })
    timer = setTimeout(() => observer?.disconnect(), 10000)
  }
}, { flush: 'post', immediate: true })

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') menuOpen.value = false
}

onMounted(() => {
  theme.start()
  health.start()
  auth.start()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  theme.stop()
  health.stop()
  auth.stop()
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <LoginGate v-if="!auth.access || route.path === '/login'" />
  <div v-else class="shell">
    <a class="skip-link" href="#main-content">Skip to content</a>
    <TopBar :menu-open="menuOpen" @toggle-menu="menuOpen = !menuOpen" />
    <div class="body">
      <AppSidebar :open="menuOpen" @navigate="menuOpen = false" />
      <div v-if="menuOpen" class="overlay" aria-hidden="true" @click="menuOpen = false"></div>
      <div class="content">
        <div class="content-inner" :class="{ 'project-content': route.name === 'projects' }">
          <main id="main-content" tabindex="-1">
            <SetupPrompt />
            <RouterView />
          </main>
          <AppFooter />
        </div>
      </div>
    </div>
    <HelpChat />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  background: var(--shell-glow);
}

.body {
  flex: 1;
  min-height: 0;
  display: flex;
}

.content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--gap-lg);
}

.content-inner {
  max-width: var(--content-max-width);
  margin: 0 auto;
}

.project-content { max-width: var(--project-content-width); }

.overlay {
  display: none;
}

@media (max-width: 767.98px) {
  .content {
    padding: var(--gap);
  }

  .overlay {
    display: block;
    position: fixed;
    inset: var(--topbar-height) 0 0 0;
    background: var(--overlay);
    z-index: var(--z-overlay);
  }
}
</style>
