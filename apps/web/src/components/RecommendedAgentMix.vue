<script setup lang="ts">
withDefaults(defineProps<{ platform?: 'mac' | 'pi' }>(), { platform: 'mac' })
</script>
<template>
  <aside class="card recommended-mix" aria-label="Recommended agent mix">
    <h3>Start free, add a membership when useful</h3>
    <ol>
      <li><a href="https://openrouter.ai/" target="_blank" rel="noopener noreferrer">Create an OpenRouter account</a> and a private key in <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">OpenRouter key settings</a>. Configure it in the native agents; saving the dashboard’s write-only key only enables its key-spending check.</li>
      <li>Install Hermes and run <code>hermes setup</code> on this host. Use Hermes as the coordinator with <code>openrouter/free</code> or an explicitly reviewed zero-priced model. Disable paid fallback for free-only work. <a href="https://hermes-agent.nousresearch.com/docs/getting-started/installation" target="_blank" rel="noopener noreferrer">Hermes setup guide</a>.</li>
      <li v-if="platform === 'mac'">Use OpenClaw for Mac worker tasks and configure its native OpenRouter free route. <a href="https://docs.openclaw.ai/getting-started" target="_blank" rel="noopener noreferrer">OpenClaw setup guide</a>.</li>
      <li v-else>Prefer a lightweight ZeroClaw or PicoClaw worker on Raspberry Pi. Their RCD adapters are experimental: ZeroClaw has offline/VM evidence; PicoClaw still needs metering/conformance work. They are not yet selectable dashboard worker routes. Hermes free routes can be configured now; do not treat installing a claw binary as an accepted RCD integration.</li>
      <li>Optionally add a Codex, Claude Code or Grok Build membership through that agent’s native sign-in for work that needs more capacity. Use only memberships you own and routes you approve. Free routes may throttle, time out or become unavailable; memberships also have usage limits.</li>
    </ol>
    <p v-if="platform === 'pi'">RCD ships with free-only dispatch. Before using membership workers, the operator must review Billing &amp; rates and explicitly change the installation’s dispatch policy to allow approved subscription routes. Installing or signing in to a CLI does not change that policy.</p>
    <p><strong>BYOK is API billing:</strong> OpenRouter forwards your provider API key; it does not pass ChatGPT/Claude subscription allowances through. Google BYOK uses Google API billing too. Eligible Google plan credits may offset costs after you claim/link them; they do not turn OpenRouter into Gemini app subscription access. Review provider billing, OpenRouter fees and fallback settings before enabling BYOK.</p>
    <p class="small"><a href="https://openrouter.ai/openrouter/free" target="_blank" rel="noopener noreferrer">Free router</a> · <a href="https://openrouter.ai/docs/guides/overview/auth/byok" target="_blank" rel="noopener noreferrer">BYOK billing</a> · <a href="https://developers.google.com/profile/help/benefits" target="_blank" rel="noopener noreferrer">Google credit eligibility</a>. No accounts, keys, paid fallbacks or route permissions are created automatically.</p>
  </aside>
</template>
<style scoped>
.recommended-mix { overflow-wrap: anywhere; }
.recommended-mix h3 { margin-top: 0; }
.recommended-mix li { margin-bottom: .6rem; }
</style>
