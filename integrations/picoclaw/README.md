# PicoClaw adapter

`PicoClawAdapter` is an `rcd.adapter.v1` implementation for the documented
PicoClaw CLI surface: `picoclaw agent -m ... --session ... --model ...`.

Each RCD run gets a `0700` private PicoClaw home and a generated `config.json`.
That configuration contains exactly one OpenRouter model alias, an explicit
workspace, no gateway/channel/cron configuration, and no secret. The OpenRouter
key is inherited only as `OPENROUTER_API_KEY`; it is not copied to configuration,
state, event, or result files. Native fallback is absent from the generated config.
The adapter launches its own process group and uses SIGTERM then SIGKILL according
to the contract's `kill_grace_s` limit.

## Eligibility status

This is intentionally **not live-conformance eligible yet**. Current PicoClaw
one-shot CLI output cannot independently establish the served provider model,
usage/cost, external tool-call receipts, or a durable approval checkpoint. Its
capabilities therefore accurately report `reports_model=never`, `reports_cost=false`,
`tool_events=false`, `suspend_modes=[]`, and `enforces_budget=none`. Any paid/API
RunSpec fails before a child process starts, with `BUDGET_EXCEEDED`. This prevents
unbounded OpenRouter billing rather than relying on a prompt or requested model.

The Pi comparison must add a pinned PicoClaw version plus a local provider/tool
proxy that (1) admits every request against the run cap before forwarding, (2)
records independent OpenRouter response/model/usage/cost receipts, and (3) exposes
the four synthetic conformance tools with correlated calls. Only then may
the adapter can be extended to advertise budget enforcement and the live factory
can be wired into `RCD_CONFORMANCE_FACTORY`.

## Checks

```sh
PYTHONPATH=apps/api:. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/picoclaw
```

No credentials, PicoClaw binary, OpenRouter request, Pi target, preview server, or
port 8800 is required for those checks.
