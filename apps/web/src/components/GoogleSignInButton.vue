<script setup lang="ts">
// "Continue with Google" for the sign-in gate. Follows Google's sign-in branding guidelines
// (developers.google.com/identity/branding-guidelines): the light button on every theme, the
// standard four-colour "G" inline (no hosted asset), and Google's own label wording. The fixed
// colours below are Google's, not ours, so they deliberately stay out of the theme tokens.
defineProps<{ href: string }>()
</script>

<template>
  <a class="google-button" :href="href" data-testid="google-signin-button">
    <svg class="google-g" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" />
      <path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.997 8.997 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" />
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" />
    </svg>
    <span>Continue with Google</span>
  </a>
</template>

<style scoped>
.google-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  width: 100%;
  min-height: 3rem;
  padding: 0 var(--gap);
  border: 1px solid #747775;
  border-radius: var(--radius-pill);
  background: #ffffff;
  color: #1f1f1f;
  font-family: Roboto, var(--font-sans);
  font-size: var(--font-size);
  font-weight: 500;
  letter-spacing: 0.01em;
  text-decoration: none;
  box-shadow: 0 1px 2px rgb(60 64 67 / 18%);
  transition: background-color 120ms ease, box-shadow 120ms ease, transform 120ms ease;
}
.google-button:hover { background: #f2f6fc; box-shadow: 0 2px 6px rgb(60 64 67 / 26%); }
.google-button:active { background: #e8eef7; transform: translateY(1px); }
.google-g { width: 1.25rem; height: 1.25rem; flex-shrink: 0; }
@media (prefers-reduced-motion: reduce) { .google-button { transition: none; } .google-button:active { transform: none; } }
</style>
