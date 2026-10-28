# Recommended agent mix

Start with an [OpenRouter account](https://openrouter.ai/) and Hermes as coordinator. Run `hermes setup` personally and configure `openrouter/free` or a reviewed zero-priced model. Keep paid fallback disabled for free-only work. The dashboard spending key is separate from the credentials used by a native agent, unless you [share it with Hermes and OpenClaw](saved-openrouter-key.md) in Profile.

For Mac workers use OpenClaw. For Raspberry Pi, ZeroClaw or PicoClaw are the intended lightweight choices, but their dashboard integration remains experimental and is not yet a selectable supported worker route. Use the integration guides for current limits; an installed binary alone does not establish dispatch readiness.

OpenRouter's [free router](https://openrouter.ai/openrouter/free) has no token charge. Availability, rate limits and timeouts can interrupt development. A mixed setup with Hermes coordinating free workers and an eligible native membership CLI can improve access during free-provider congestion. No account promises unlimited use.

## Native memberships are separate from API billing

For subscription access, sign in through each CLI's native account flow. Buy only memberships for agents you choose. Free-only setup does not require all three accounts. Facts checked 2026-10-13:

- [Codex](https://learn.chatgpt.com/docs/pricing): ChatGPT Plus is $20/month and includes Codex CLI access. Other eligible plans exist. Free desktop availability does not establish free CLI entitlement. API-key access is billed separately.
- [Claude Code](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan): Pro is $20/month, or $200 annually; Max and eligible organization plans also offer access. Console/API billing is separate. An ANTHROPIC_API_KEY can select API billing instead of membership access.
- [Grok Build](https://docs.x.ai/build/overview): xAI documents SuperGrok or X Premium Plus access. Legacy SuperGrok pricing is $30/month; [new subscription tiers](https://docs.x.ai/x-subscription/pricing) vary. Verify the current CLI entitlement before purchase. There is no universal $20 minimum across these products. Dashboard Grok runs require subscription billing because its API dollar cap is not enforced.

[OpenRouter BYOK](https://openrouter.ai/docs/guides/overview/auth/byok) uses provider API keys and provider billing, with OpenRouter's applicable fees. It does not pass through ChatGPT or Claude membership quotas. API rates and workload can make it more expensive than a suitable membership.

Google AI memberships can include [developer Cloud credits](https://developers.google.com/profile/help/benefits) that may offset eligible API usage after claiming benefits and linking the correct billing account. [Gemini API billing](https://ai.google.dev/gemini-api/docs/billing) remains separate from Gemini app quotas. BYOK does not transfer app subscription quotas; eligibility, credits and any remaining charges must be checked in the provider billing account.

Which routes may run is set in Settings → AI & models ([route policy](route-policy.md)); the Memberships preset allows membership and free routes. A membership route also needs its account saved as Subscription in Billing & rates. Exact reviewed route classes, model pins, approvals and API budget checks still apply. Installing a CLI or buying a membership never changes this policy. MCD and RCD installation settings are separate.
