<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import BrandMark from '@/components/BrandMark.vue'
import AppIcon from '@/components/AppIcon.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import GoogleSignInButton from '@/components/GoogleSignInButton.vue'
import { useAuthStore } from '@/stores/auth'
import { postJson } from '@/lib/api'
const auth = useAuthStore()
const route = useRoute()
const token = ref('')
const recoveryError = ref('')
const recovering = ref(false)
const year = new Date().getFullYear()
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
      <div class="google-stripe" aria-hidden="true"><i /><i /><i /><i /></div>
      <ThemeToggle compact class="login-theme" />
      <header class="login-head">
        <BrandMark class="login-mark" />
        <span class="eyebrow">Raspberry Pi Control Dashboard</span>
        <h1 id="login-title">{{ auth.enabled === false ? 'Local dashboard' : 'Sign in to RCD' }}</h1>
        <p class="muted">Monitor your Raspberry Pi, follow your agents, and keep work moving.</p>
      </header>
      <p v-if="auth.error" class="warning-text" role="alert">{{ auth.error }}</p>
      <button v-if="auth.error" class="btn" @click="auth.refresh">Retry connection</button>
      <p v-else-if="auth.enabled === null" class="muted status" role="status">Checking access…</p>
      <template v-else-if="auth.enabled === false">
        <p class="muted status">Google sign-in is being prepared. This dashboard is currently available on this Pi.</p>
        <a class="btn primary" href="/">Open dashboard <AppIcon name="chevron-right" /></a>
      </template>
      <template v-else-if="auth.user">
        <p class="muted status">Signed in as {{ auth.user.email }}</p>
        <a class="btn primary" href="/">Open dashboard <AppIcon name="chevron-right" /></a>
        <button class="btn" @click="auth.logout">Sign out</button>
      </template>
      <template v-else>
        <p v-if="route.query.error === 'signin_failed'" class="warning-text" role="alert">Sign-in did not complete. Try again with an allowed Google account.</p>
        <GoogleSignInButton :href="loginUrl" />
        <p class="small muted status">You'll sign in with your Google account on Google's own page. Access is limited to approved accounts, and your session lasts 12 hours.</p>
        <details v-if="auth.localRecovery">
          <summary><AppIcon name="chevron-right" class="chevron" />Local administrator recovery</summary>
          <form @submit.prevent="recover">
            <label for="recovery-token">Recovery token</label>
            <input id="recovery-token" v-model="token" class="input" type="password" autocomplete="off" required maxlength="128" />
            <p class="small muted">Use the private recovery token stored on this Pi.</p>
            <p v-if="recoveryError" class="warning-text" role="alert">{{ recoveryError }}</p>
            <button class="btn" :disabled="recovering">{{ recovering ? 'Checking…' : 'Recover access' }}</button>
          </form>
        </details>
      </template>
      <footer class="small muted">© {{ year }} Raspberry Pi Control Dashboard · Bamcio LLC</footer>
    </section>
  </main>
</template>
<style scoped>
.login-page { min-height: 100vh; min-height: 100dvh; display: flex; align-items: center; justify-content: center; padding: var(--gap-lg); background: var(--chat-glow); }
.login-card { position: relative; overflow: hidden; display: flex; flex-direction: column; gap: var(--gap-lg); width: min(100%, var(--login-width)); padding: calc(var(--gap-xl) + var(--gap-sm)) var(--gap-xl) var(--gap-lg); background: var(--dialog-glass); border: 1px solid var(--select-border); border-radius: var(--dialog-radius); -webkit-backdrop-filter: blur(var(--glass-blur)); backdrop-filter: blur(var(--glass-blur)); box-shadow: var(--shadow); }
/* Google's four brand colours as a thin top edge: a quiet cue for which account signs in here. */
.google-stripe { position: absolute; inset: 0 0 auto; display: flex; height: 4px; }
.google-stripe i { flex: 1; }
.google-stripe i:nth-child(1) { background: #4285f4; }
.google-stripe i:nth-child(2) { background: #ea4335; }
.google-stripe i:nth-child(3) { background: #fbbc05; }
.google-stripe i:nth-child(4) { background: #34a853; }
.login-card .login-theme { position: absolute; top: var(--gap); right: var(--gap); border-color: transparent; background: transparent; }
.login-head { display: flex; flex-direction: column; align-items: center; gap: var(--gap-sm); text-align: center; }
.login-mark { --brand-size: 3.5rem; margin-bottom: var(--gap-sm); filter: drop-shadow(0 6px 14px var(--accent-soft)); }
h1 { margin: 0; font-size: var(--font-size-2xl); letter-spacing: -0.01em; }
p { margin: 0; }
.status { text-align: center; }
.btn { min-height: var(--select-height); justify-content: center; }
.login-theme.btn { min-height: var(--touch-target); }
.primary { background: var(--dialog-action); }
details, footer { border-top: 1px solid var(--glass-border); padding-top: var(--gap); }
footer { text-align: center; }
summary { display: flex; align-items: center; gap: var(--gap-xs); cursor: pointer; color: var(--text-muted); font-size: var(--font-size-sm); list-style: none; }
summary::-webkit-details-marker { display: none; }
summary:hover { color: var(--text); }
.chevron { transition: transform 120ms ease; }
details[open] .chevron { transform: rotate(90deg); }
form { display: flex; flex-direction: column; gap: var(--gap-sm); margin-top: var(--gap); }
@supports not (backdrop-filter: blur(1px)) { .login-card { background: var(--panel-raised); } }
@media (max-width: 600px) { .login-page { padding: var(--gap); } .login-card { padding: calc(var(--gap-xl) + var(--gap-sm)) var(--gap-lg) var(--gap-lg); } }
@media (prefers-reduced-motion: reduce) { .chevron { transition: none; } }
</style>
