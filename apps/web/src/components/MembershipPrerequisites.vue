<script setup lang="ts">
const checked = '2026-10-13'
</script>
<template>
  <aside class="membership notice-warn" aria-label="Membership billing prerequisites">
    <h3>Before using membership billing</h3>
    <p>Codex, Claude Code and Grok Build need their own eligible paid membership for the subscription route described here. Installing a CLI does not purchase a membership, sign it in or verify its entitlement. Sign in on this host with the account that owns the plan, then review Billing &amp; rates.</p>
    <ul>
      <li><strong>Codex CLI:</strong> ChatGPT Plus is $20/month US; Pro and eligible organizational plans also provide access. Free/Go desktop access does not establish CLI entitlement. <a href="https://learn.chatgpt.com/docs/pricing" target="_blank" rel="noopener noreferrer">OpenAI plans</a>.</li>
      <li><strong>Claude Code:</strong> Claude Pro is $20/month US when billed monthly ($200/year annually); Max and eligible organizational seats also provide access. <a href="https://claude.com/pricing" target="_blank" rel="noopener noreferrer">Anthropic plans</a>.</li>
      <li><strong>Grok Build:</strong> use an eligible paid coding membership. SuperGrok and X Premium Plus are documented eligible plans; legacy SuperGrok is listed at $30/month. New X Subscription tiers have different prices—confirm Build CLI entitlement with xAI before subscribing. <a href="https://x.ai/news/grok-build-cli" target="_blank" rel="noopener noreferrer">CLI eligibility</a> · <a href="https://docs.x.ai/x-subscription/pricing" target="_blank" rel="noopener noreferrer">Current plans</a>.</li>
    </ul>
    <p>API keys and API/Console billing are separate usage charges; a membership does not cover them. An Anthropic API key can override Claude subscription sign-in. Included usage has limits; extra credits/top-ups may cost more. Membership is a billing option, not unlimited use or guaranteed savings. This dashboard cannot verify your native account’s entitlement. Grok API dispatch is refused here.</p>
    <p class="small muted">Prices checked {{ checked }}; US list prices before tax, subject to change. You only need memberships for agents you choose to use.</p>
  </aside>
</template>
<style scoped>
.membership h3 { margin-top: 0; }
.membership li { margin-bottom: .6rem; }
.membership { overflow-wrap: anywhere; }
</style>
