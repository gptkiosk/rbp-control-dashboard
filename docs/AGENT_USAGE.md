# Agent explorer and billing

The Agents page provides fleet tiles, a selected-agent explorer, configured OpenClaw targets,
CLI session/sub-agent selectors, process details, model usage and recent activity. The New Chat
and New Task forms use the same OpenClaw catalog, with a manual-ID fallback when it is unavailable.

`GET /api/agents/usage?period=month&agent=openclaw&target=mm-main` supplies the explorer.
Periods are `24h`, `7d`, and `month`. Sub-agent filtering affects the detail totals and activity;
fleet totals and the selector inventory remain available. CLI targets use unique session IDs,
with nicknames when reported. OpenClaw targets use configured agent IDs.

## Collection and accounting

- OpenClaw: native assistant usage records under `~/.openclaw/agents/*/sessions/*.jsonl`.
  Input, output, cache read/write and source-estimated API costs are captured per response.
  Delivery mirrors are excluded from model usage.
- Claude Code: `~/.claude/projects/**/*.jsonl`, including sidechain/sub-agent logs. Message IDs
  deduplicate streaming chunks; cache reads and both 5-minute and 1-hour writes are separate.
- Codex: `~/.codex/sessions/**/*.jsonl` and archived sessions. Canonical response usage records
  supersede cumulative compatibility token events. Models come from turn context, not guessed
  from the current default. Parent IDs and reported agent nicknames are retained.
- Hermes: read-only explicit metadata columns from `~/.hermes/state.db` session_model_usage.
  These are **session lifetime counters**, not dated response records. A counter is included in
  period totals only if its first_seen and last_seen lie inside that period; overlapping older
  sessions remain available in their lifetime drill-down. Unknown/included costs are unpriced
  without an API-equivalent rate, rather than treated as a zero-cost model.
- MCD task/chat runs supplement native telemetry. A native session supersedes matching MCD runs
  to prevent double counting. Current work and failed runs also remain in the MCD work panel.

The collector indexes historical files in bounded batches (64 MiB per source per pass) and then
reads only appended lines, every 15 seconds. Initial indexing of multi-gigabyte local logs can
take several minutes. Durable SQLite cursors and canonical IDs survive restarts. Source state
and unpriced counts are visible. No transcript body, prompt, command argument, API credential,
provider URL or account identifier is stored in usage records or returned by the usage API.
Source transcript files are never modified.

## Costs and subscriptions

`GET /api/billing` reads preferences; guarded `PATCH /api/billing` persists them in SQLite.
Default billing: Claude Code and Codex each use a $20/month subscription; Hermes and OpenClaw
use API billing. All four modes and monthly amounts can be changed. Fees are counted once per
agent, never once per sub-agent. No purchasing or provider-account changes occur.

Savings = captured calendar-month API equivalent − full monthly subscription fee. The calendar
month uses America/Los_Angeles. Negative savings mean below break-even. Missing prices make the
comparison partial; missing source data and older Hermes counters can also limit coverage.

Reported API-equivalent cost takes precedence; otherwise token categories are priced using a
verified default or exact-model custom rate in USD per million tokens. Rates were checked on
2026-10-09 against [OpenAI pricing](https://developers.openai.com/api/docs/pricing),
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol),
[GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) and
[Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing).
Published GPT-6 and Claude Haiku 5.5 context tiers are applied per request. Older models without
verified tiers have an input limit; requests above it stay unpriced. Custom rates apply uniformly
up to their configured limit. Unknown model IDs stay unpriced. Missing cache breakdowns use
uncached input for an estimate. These are API equivalents, not invoices: standard estimates
exclude paid tools, taxes, and speed/residency surcharges. Price changes can be configured in
Billing & rates; they recalculate estimates, while source-reported costs remain intact.

## Verification

Overview includes a compact Agents section, separate from Mac resource tiles. MCD work polls
every 5 seconds and native usage every 15 seconds (paused while the browser tab is hidden).
Cards show running MCD turns, last captured activity, observed processes, 24-hour API equivalents
and up to three related sub-agents/sessions. Agent and session links open the detailed explorer.
"Recent activity" means a captured update within the last minute, not proof of a running model
turn. Failed refreshes retain the last received data with a warning. Source freshness and
unpriced records remain visible; process presence alone does not make an agent active.

API tests cover cache category arithmetic, long-context thresholds, streaming/replay deduplication,
restart-safe incremental collection, unfinished JSONL tails, source privacy, native/MCD overlap,
calendar-month subscription comparisons, target filters, Hermes lifetime boundaries and preferences.
Web tests cover named target submission, explorer selection, guarded billing saves and Overview
polling, stale-state recovery, activity expiry and sub-agent drill-down links.
Live verification checks desktop and 390 px layouts, configured OpenClaw selection and billing
controls without sending model prompts.

## OpenRouter actual spending

Overview and Agents show OpenRouter-reported **key-wide** spending separately from captured
model/session API equivalents. A background read-only `GET https://openrouter.ai/api/v1/key`
refreshes once per minute (six-second timeout, fixed HTTPS host, no redirects or proxy inheritance).
The dashboard reports `usage_daily`, `usage_weekly`, `usage_monthly`, and lifetime `usage` as
OpenRouter credits used in USD. Windows are UTC calendar day/week/month, with Monday starting
weeks; these differ from the captured rolling 24h/7d and Los Angeles monthly filters.
`byok_usage*` is shown separately as external BYOK usage, never silently added to credits or
presented as a provider invoice. Limit/remaining amounts are shown only when reported.

Default key discovery reads Hermes `~/.hermes/.env` and OpenClaw `~/.openclaw/.env`, with
OpenClaw's explicit `models.providers.openrouter.apiKey` taking precedence. The literal
`OPENROUTER_API_KEY` and its `$`/`${}`/`env:` reference forms resolve to that agent's env file.
For injected keys, secret references, or a different profile, put the literal appropriate key
in `~/.mac-control/.env` under `MAC_CONTROL_OPENROUTER_HERMES_KEY` or
`MAC_CONTROL_OPENROUTER_OPENCLAW_KEY`. This is a meter override only; it does not change agent
credentials. Automatic discovery covers the default provider key, not every possible profile.

Identical keys produce one meter/request with both agent names. Spending can include other
apps using the key, and cannot be split into Hermes/OpenClaw/model/sub-agent charges from this
endpoint. Separate dedicated agent keys allow separate meters. Key totals remain independent
of explorer filters and are never added to native usage, estimates or subscription savings.

Only numerical amounts and connection/freshness metadata enter the API payload. Credentials,
key labels/fragments, response error bodies and raw provider responses are not persisted or
returned. Failed refreshes retain last successful values with a stale label; rotated keys
never inherit the prior key's numbers. No transcript data is sent to OpenRouter and no model
calls are made. Meter values live in memory and refresh after a service restart.

Sources verified 2026-10-09:
- [Current-key API](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key)
- [Limits and UTC usage windows](https://openrouter.ai/docs/api-reference/limits)
- [Usage accounting and per-generation costs](https://openrouter.ai/docs/cookbook/administration/usage-accounting)

## OpenClaw timeouts and exit codes

An exit code of `0` describes the CLI process. OpenClaw can exit normally while its
JSON result reports `status: timeout`; MCD records **Timed out**, keeps usage and partial
output, and explains whether the provider, queue or response finalization timed out.
The Exit code field explains why a normal CLI exit does not mean the agent succeeded.
Provider silence and MCD's total run limit have distinct error messages.
If OpenClaw exits with `GatewayClientRequestError: FailoverError: LLM request timed out`
and no JSON, MCD still records a provider timeout; it does not hide the cause behind a
JSON parsing error or invent model/usage values. Other gateway failures remain Failed.

MCD passes each task's timeout to `openclaw agent --timeout`; chats use their 15-minute
run limit. OpenClaw also has a provider idle/request watchdog, which defaults to two
minutes in the installed version. For this Mac's OpenRouter free models, the operator
authorized `models.providers.openrouter.timeoutSeconds = 600` (ten minutes). The gateway
applies that field through hot reload. Shorter task limits still take precedence, and
upstream providers can impose their own limits. This adjustment reduces premature local
timeouts; it cannot guarantee that a stalled provider will recover.
Run #6 confirmed a different failure: the gateway used a 600,000 ms provider timeout,
but the native assistant event reported `Upstream idle timeout exceeded` after about
two minutes. A local timeout increase cannot override that upstream limit.

On another installation, configure that native field as needed; it is not a secret or
an embedded application default. Model assignments, fallback approval and spending caps
are unchanged. Timeout failures require reviewing partial work and explicitly retrying;
MCD does not automatically retry or switch to a paid model for a timeout.
