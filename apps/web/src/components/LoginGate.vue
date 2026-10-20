<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import BrandMark from '@/components/BrandMark.vue'
import AppIcon from '@/components/AppIcon.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAuthStore } from '@/stores/auth'
import { postJson } from '@/lib/api'
const auth = useAuthStore()
const route = useRoute()
const token = ref('')
const recoveryError = ref('')
const recovering = ref(false)
const loginUrl = computed(() => '/auth/login?next=' + encodeURIComponent(typeof route.query.next === 'string' ? route.query.next : route.path === '/login' ? '/' : route.fullPath))
async function recover() {
  recovering.value = true
  recoveryError.value = ''
  try { await postJson('/auth/recover', { token: token.value }); token.value = ''; window.location.assign('/') }
  catch { recoveryError.value = 'Recovery failed. Check the local token and try again shortly.' }
  finally { recovering.value = false; token.value = '' }
}
</script>
<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <div class="login-brand"><BrandMark /><span>Raspberry Pi Control Dashboard</span><ThemeToggle compact /></div>
      <span class="eyebrow">YOUR PI. YOUR AGENTS.</span>
      <h1 id="login-title">{{ auth.enabled === false ? 'Local dashboard' : 'Welcome to RCD' }}</h1>
      <p class="muted">Monitor your Raspberry Pi, follow your agents, and keep work moving.</p>
      <p v-if="auth.error" class="warning-text" role="alert">{{ auth.error }}</p>
      <button v-if="auth.error" class="btn" @click="auth.refresh">Retry connection</button>
      <p v-else-if="auth.enabled === null" class="muted" role="status">Checking access…</p>
      <template v-else-if="auth.enabled === false">
        <p class="muted">Google sign-in is being prepared. This dashboard is currently available on this Pi.</p>
        <a class="btn primary" href="/">Open dashboard <AppIcon name="chevron-right" /></a>
      </template>
      <template v-else-if="auth.user">
        <p class="muted">Signed in as {{ auth.user.email }}</p>
        <a class="btn primary" href="/">Open dashboard <AppIcon name="chevron-right" /></a>
        <button class="btn" @click="auth.logout">Sign out</button>
      </template>
      <template v-else>
        <p v-if="route.query.error === 'signin_failed'" class="warning-text" role="alert">Sign-in did not complete. Try again with an allowed Google account.</p>
        <a class="btn primary" :href="loginUrl">Continue with Google <AppIcon name="chevron-right" /></a>
        <p class="small muted">Access is limited to approved accounts. Your session lasts 12 hours.</p>
        <details v-if="auth.localRecovery">
          <summary>Local administrator recovery</summary>
          <form @submit.prevent="recover">
            <label for="recovery-token">Recovery token</label>
            <input id="recovery-token" v-model="token" class="input" type="password" autocomplete="off" required maxlength="128" />
            <p class="small muted">Use the private recovery token stored on this Pi.</p>
            <p v-if="recoveryError" class="warning-text" role="alert">{{ recoveryError }}</p>
            <button class="btn" :disabled="recovering">{{ recovering ? 'Checking…' : 'Recover access' }}</button>
          </form>
        </details>
      </template>
      <footer class="small muted">© {{ new Date().getFullYear() }} Pi Control</footer>
    </section>
  </main>
</template>
<style scoped>
.login-page { min-height: 100vh; min-height: 100dvh; display: flex; align-items: center; justify-content: center; padding: var(--gap-lg); background: var(--chat-glow); }
.login-card { display: flex; flex-direction: column; gap: var(--gap-lg); width: min(100%, var(--login-width)); padding: var(--gap-xl); background: var(--dialog-glass); border: 1px solid var(--select-border); border-radius: var(--dialog-radius); -webkit-backdrop-filter: blur(var(--glass-blur)); backdrop-filter: blur(var(--glass-blur)); box-shadow: var(--shadow); }
.login-brand { display: flex; align-items: center; gap: var(--gap); font-weight: var(--font-weight-strong); }
.login-brand .theme-toggle { margin-left: auto; }
h1 { margin: 0; font-size: var(--font-size-2xl); }
p { margin: 0; }
.btn { min-height: var(--select-height); justify-content: center; }
.primary { background: var(--dialog-action); }
details, footer { border-top: 1px solid var(--glass-border); padding-top: var(--gap); }
summary { cursor: pointer; color: var(--text-muted); }
form { display: flex; flex-direction: column; gap: var(--gap-sm); margin-top: var(--gap); }
@supports not (backdrop-filter: blur(1px)) { .login-card { background: var(--panel-raised); } }
@media (max-width: 600px) { .login-page, .login-card { padding: var(--gap-lg); } .login-brand { font-size: var(--font-size-sm); } }
</style>
