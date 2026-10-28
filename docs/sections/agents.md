# Agents

## Purpose

Open **Agents** (`/agents`) for the fleet's top-level status and a selected agent's detailed activity, subagents, sessions, observed processes, model usage and cost coverage. Overview provides the compact live summary; Agents provides the drill-down.

## Screenshots

Pending capture: `agents-list.png` (agent explorer), `agents-subagent-select.png` (sub-agent selector) and `agents-billing-rates-dialog.png` (billing and rates). No RCD capture exists yet.

## Controls

1. Select Claude Code, Codex, Hermes or OpenClaw in the fleet.
2. Choose a named subagent or session in **Sub-agent / session**, or leave **All sub-agents & sessions** selected. OpenClaw's configured names appear alongside observed sessions.
3. Select 24 hours, 7 days or the current month. Inspect input/output tokens, cache usage, sessions, model rows and source coverage for the selected scope.
4. Inspect the observed process details and last activity. A process can remain alive while no model turn is active; recent telemetry is not proof of an active inference request.
5. Open **Billing & rates** (Settings → AI & models → Accounts) to configure each agent's billing mode, monthly subscription amount and model rates, then save. This changes MCD's accounting preferences; it does not purchase a subscription or reconfigure provider billing.

The default accounting uses a $20 monthly subscription for Claude Code and Codex, and API billing for Hermes/OpenClaw. Each subscription fee is counted once per agent, not per subagent. Subscription savings compare the captured calendar-month API equivalent with the full monthly fee. Negative savings mean the captured equivalent is below that fee. Missing prices or source coverage make the result partial.

Native usage comes from Claude/OpenClaw/Codex session records and Hermes session counters. MCD task/chat runs supplement those sources; matching native sessions supersede MCD records to avoid double counting. Unknown costs stay unpriced. Hermes counters describe a session's lifetime: sessions spanning a period boundary are excluded from that period's totals and remain available in lifetime drill-down.

OpenRouter actual spending is shown separately as a **key-wide** meter. A shared key's usage can include both agents and other callers; it cannot be split reliably by agent/model/subagent from that endpoint. Identical keys produce one meter. Do not add it to native cost estimates or subscription savings. BYOK readings are shown separately and are not a Google invoice.

## Settings involved

- Agent availability depends on installed executables; usage collection depends on the collector and readable native metadata.
- Billing preferences and custom rates are saved by MCD. Source-reported costs remain separate from recalculated estimates.
- Named targets and model suggestions come from current native Hermes/OpenClaw configuration. MCD passes explicit approved overrides for assigned runs; an unassigned run follows the native default policy.
- OpenRouter meter credentials are read from private host configuration or explicit meter overrides. Configure secrets privately; never place them in published docs or screenshots.
- Captured month comparisons use America/Los_Angeles; OpenRouter meter windows use UTC calendar periods. Rolling 24-hour/7-day selections are different windows.

## Troubleshooting

- **Installed but idle:** inspect last activity and current MCD work. An installed binary or gateway process does not mean a model is working.
- **Usage missing:** check source coverage and collection status. Initial indexing of large historical logs can take several minutes; missing/unpriced records must not be interpreted as free usage.
- **Cost looks duplicated:** compare scopes. Key-wide actual spending and captured API equivalents are separate measures, not amounts to sum.
- **Meter stale:** retain the last reading as historical evidence; check its freshness indicator and private key configuration. A rotated key must not inherit the old key's figures.
- **Model not independently reported:** keep the requested model visible without treating it as verified. Codex run output does not report its actual model; native turn-context telemetry may supply additional evidence.
- **Route no longer available:** review the model/target in Projects against current native configuration before resubmission. Do not replace an approved route with an unapproved paid model.

## Related pages

- [Overview](overview.md): compact live summaries.
- [Tasks](tasks.md): current runs, evidence and approvals.
- [Chat](chat.md): direct conversations.
- [Projects](projects.md): assignments and bounded model switching.
- [Settings](../configuration/settings.md) and [environment configuration](../configuration/environment.md).
