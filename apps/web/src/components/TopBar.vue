<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import BrandMark from '@/components/BrandMark.vue'
import HealthBadge from './HealthBadge.vue'
import { useAuthStore } from '@/stores/auth'
import { useHelpStore } from '@/stores/help'
import AppIcon from '@/components/AppIcon.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
const auth = useAuthStore()
const help = useHelpStore()
const route = useRoute(), accountOpen = ref(false), account = ref<HTMLElement | null>(null), accountButton = ref<HTMLButtonElement | null>(null)
function closeAccount() { accountOpen.value = false }
function escapeAccount() { closeAccount(); accountButton.value?.focus() }
function outside(event: PointerEvent) { if (accountOpen.value && !account.value?.contains(event.target as Node)) closeAccount() }
watch(() => route.fullPath, closeAccount)
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))

defineProps<{ menuOpen: boolean }>()
const emit = defineEmits<{ toggleMenu: [] }>()
</script>

<template>
  <header class="topbar" :class="{ 'signed-in': auth.user }">
    <button
      type="button"
      class="menu-button"
      aria-label="Menu"
      aria-controls="app-sidebar"
      :aria-expanded="menuOpen ? 'true' : 'false'"
      @click="emit('toggleMenu')"
    >
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
        <path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none" />
      </svg>
    </button>
    <RouterLink to="/" class="brand" aria-label="Raspberry Pi Control Dashboard, home">
      <BrandMark />
      <span class="wordmark" aria-hidden="true">
        <span class="wm-full">Raspberry Pi Control <span class="wm-accent">Dashboard</span></span>
        <span class="wm-short">RCD</span>
      </span>
    </RouterLink>
    <span class="spacer"></span>
    <HealthBadge class="topbar-health" />
    <ThemeToggle />
    <button type="button" class="btn help-trigger" aria-label="Open help chat" title="Help & how-tos" @click="help.show()"><AppIcon name="chat" /><span>Help</span></button>
    <div ref="account" class="account" @keydown.esc.stop.prevent="escapeAccount">
      <button ref="accountButton" type="button" class="btn account-trigger" aria-label="Account and settings" title="Account and settings" aria-controls="header-account-menu" :aria-expanded="accountOpen" @click="accountOpen = !accountOpen"><AppIcon name="user" /></button>
      <div v-if="accountOpen" id="header-account-menu" class="account-panel">
        <p v-if="auth.user" class="account-email">{{ auth.user.email }}</p>
        <RouterLink to="/profile" class="account-action" @click="closeAccount"><AppIcon name="settings" />Settings</RouterLink>
        <RouterLink to="/setup" class="account-action" @click="closeAccount"><AppIcon name="tasks" />Setup wizard</RouterLink>
        <button v-if="auth.user" type="button" class="account-action" @click="closeAccount(); auth.logout()">Sign out</button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  height: var(--topbar-height);
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--gap);
  padding: 0 var(--gap);
  background: var(--panel);
  background-image: var(--nav-glass);
  border-bottom: 1px solid var(--surface-border);
}


.spacer {
  flex: 1;
}
.help-trigger { flex: none; min-height: var(--touch-target); }
.account { position:relative; flex:none; }
.account-trigger { width:var(--touch-target); height:var(--touch-target); padding:0; }
.account-panel { position:absolute; top:calc(100% + var(--gap-sm)); right:0; min-width:var(--select-menu-min-width); max-width:calc(100vw - var(--gap-lg)); padding:var(--gap-sm); border:1px solid var(--select-border); border-radius:var(--surface-radius); background:var(--select-menu-bg); box-shadow:var(--surface-shadow); backdrop-filter:blur(var(--surface-blur)); z-index:var(--z-select); }
.account-email { font-size:var(--font-size-xs); color:var(--text-muted); padding:var(--gap-sm); margin:0; overflow-wrap:anywhere; }
.account-action { display:flex; align-items:center; gap:var(--gap-sm); width:100%; min-height:var(--touch-target); padding:var(--gap-sm); border:0; border-radius:var(--radius); background:transparent; color:var(--text); font:inherit; text-align:left; cursor:pointer; }
.account-action:hover,.account-action:focus-visible { background:var(--nav-active); }

.menu-button {
  display: none;
  align-items: center;
  justify-content: center;
  padding: var(--gap-sm);
  min-width: var(--touch-target);
  min-height: var(--touch-target);
  background: transparent;
  color: var(--text);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  cursor: pointer;
}

.menu-button:hover {
  background: var(--panel-raised);
}

@media (max-width: 600px) {
  .topbar { gap: var(--gap-sm); }
  .help-trigger { padding: 0; min-width: var(--touch-target); }
  .help-trigger span { display: none; }
  .topbar .topbar-health { display: none; }
}

@media (max-width: 767.98px) {
  .menu-button {
    display: inline-flex;
  }
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--icon-gap);
  color: var(--text);
  text-decoration: none;
  font-weight: var(--font-weight-strong);
  letter-spacing: -0.01em;
  white-space: nowrap;
}
.brand:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus-ring);
  outline-offset: var(--focus-ring-offset);
  border-radius: var(--radius);
}
@media (prefers-reduced-transparency: reduce) { .topbar { background-image: none; } }
.wm-accent {
  color: var(--brand-to);
}
.wm-short {
  display: none;
}
@media (max-width: 767px) {
  .wm-full {
    display: none;
  }
  .wm-short {
    display: inline;
  }
}
</style>
