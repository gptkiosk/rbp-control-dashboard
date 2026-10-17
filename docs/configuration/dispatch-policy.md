# Pre-dispatch pricing and budget policy (SEC-013)

## Spending & limits are off by default

RCD ships with no dollar limits of its own (it still starts free-only, see below). A paid route spends against your own provider
account or key, and RCD says so on the run instead of stopping it. Set a credit
limit with your provider as well (for example a key limit on your OpenRouter key).

Turn limits on in one place: **Agents, then Billing & rates, then Spending &
limits**. They are stored in the app and apply to every project and chat:

| Limit | Default | Effect when on |
| --- | --- | --- |
| Require a reviewed price before a run starts | off | A route with no reviewed class fails at once with `PRICE_UNKNOWN`. |
| Cap per run (USD) | none | A run whose budget is above the cap, or has none, is refused (`BUDGET_EXCEEDED`). Claude also gets `--max-budget-usd`. |
| Only start paid runs on agents with a built-in dollar limit | off | Paid Codex, Hermes and OpenClaw routes are refused; only Claude can enforce a dollar limit itself. |

`MAC_CONTROL_DISPATCH_MAX_BUDGET_USD` and `MAC_CONTROL_DEFAULT_BUDGET_USD` now
default to `0` (none). An explicit host cap in the environment is used as the
per-run cap until you save one in the panel. `MAC_CONTROL_DISPATCH_FREE_ONLY`
is separate and still refuses every non-free route when set.

The rest of this page describes what each rule does once it is turned on.

Task and chat launches pass the same `dispatch_gate.admit` policy immediately
before the dispatcher spawns a process (MCD) or calls adapter.start (RCD).
Claude, Codex, Hermes and OpenClaw all use this boundary. Admission or denial is
recorded in RunEvent; a denial ends the run as failed without a runner PID.
Recovery that only follows an existing runner does not start new work.

Configure reviewed routes using `MAC_CONTROL_DISPATCH_ROUTE_CLASSES`, a JSON
object keyed by exact `agent|target|model`. Use an empty target for the adapter's
default target. Values are `free`, `subscription` or `paid`. An explicit model is
required; a `:free` suffix, billing estimate, zero observed cost or CLI exit code
does not establish its price. Missing or invalid classifications fail closed.

Example synthetic configuration (replace with operator-reviewed real routes):

```sh
MAC_CONTROL_DISPATCH_ROUTE_CLASSES='{"openclaw|synthetic-worker|synthetic-model":"free"}'
MAC_CONTROL_DISPATCH_FREE_ONLY=true
MAC_CONTROL_DISPATCH_MAX_BUDGET_USD=0
MAC_CONTROL_DEFAULT_BUDGET_USD=0
```

Exact configured classes take precedence. An explicitly persisted Claude/Codex
subscription account mode can classify its native route as subscription; the
billing screen's built-in defaults cannot. An approved project's Go Free record
can classify only its exact pinned OpenClaw model and target as free. Chat turns
do not inherit project records. No fallback route is selected by the gate.

The claim freezes target, pricing class and task budget (chat uses the default
budget). Launch rechecks current classification, free-only policy and host cap;
a changed/revoked class or missing old snapshot is refused. Caps must be finite,
nonnegative numbers and at most `MAC_CONTROL_DISPATCH_MAX_BUDGET_USD`. Free-only
also refuses subscription routes. All four legacy commands must pin the admitted
model. Paid routes additionally require a positive runtime dollar boundary:
only Claude's existing `--max-budget-usd` boundary is admitted. Paid Codex,
Hermes and OpenClaw are refused even when a dollar budget is configured.

This is a per-run admission cap, not an account-wide spend reservation. Route
classes are operator-owned declarations; they must reflect actual provider and
runtime configuration. Synthetic tests demonstrate prevention of process starts,
not current provider pricing, CLI conformance or live billing enforcement.

RCD defaults are free-only with a $0 default and host cap.
