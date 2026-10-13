# Agent adapter contract (`rcd.adapter.v1`)

Status: **design, proposed** (story S2_adapter_contract). No runtime implementation is included.

| Artifact | Path |
|---|---|
| This document | `docs/port/adapter-contract.md` |
| Python interface, state machine, error taxonomy | `apps/api/adapter_contract.py` |
| JSON Schema (draft 2020-12, one bundle with `$defs`) | `apps/api/adapter_schemas/adapter-contract.schema.json` |
| Sample payloads (valid and deliberately invalid) | `apps/api/adapter_schemas/examples.json` |
| Contract self-tests | `apps/api/tests/test_adapter_contract.py` |

The dispatcher calls one `AgentAdapter` per runtime. Today the four MCD agents (Claude, Codex, Hermes, OpenClaw) are hard-wired through `agents.REGISTRY` and `Dispatcher._run_process`. On the Pi, ZeroClaw and PicoClaw must be evaluated *behind the same interface*. This contract is that interface. It was derived from the dispatch paths that exist today (see [Mapping](#8-mapping-the-existing-dispatch-paths)), so wrapping them (S2_existing_adapters) is mechanical, not a redesign.

## 1. Principles

1. **MCD decides, adapters report.** An adapter runs exactly the route it was given. It never switches models, never queues work, never accepts its own handoff and never widens permissions. Fallback across routes, retries, dependency order and acceptance stay in MCD (`projects.on_finish`, `projects.advance`, `accept_story`).
2. **The run is the unit of work, the story is the unit of idempotency.** A run has a `run_id` and an `idempotency_key` (`mcd:run:<id>`). Retries and fallbacks are *new runs* that share a `work_key` (`mcd:story:<card_id>`).
3. **Output is proposed evidence.** `succeeded` means the process finished cleanly with a result. It does not mean the work was accepted. MCD's completion guards (`project_outputs.incomplete_error`) and operator acceptance still apply.
4. **Unknown means unknown.** Fields a runtime cannot report are `null` and labelled `not_reported` / `not_measured`, never guessed. This matches `RunMeta` today.
5. **Language-neutral wire format.** ZeroClaw/PicoClaw adapters may be thin Python wrappers around a CLI or a native binary speaking JSON. The JSON Schema is normative and the Python TypedDicts mirror it.

## 2. Operations

```python
class AgentAdapter(Protocol):
    name: str
    def capabilities(self) -> Capabilities
    async def start(self, spec: RunSpec) -> Ack
    def events(self, run_id: str, after_seq: int = 0) -> AsyncIterator[Event]
    async def result(self, run_id: str) -> RunResult
    async def cancel(self, request: CancelRequest) -> Ack
    async def resume(self, decision: Decision) -> Ack
    async def heartbeat(self, run_id: str) -> Heartbeat
    async def recover(self) -> list[RecoveredRun]
```

| Operation | Called by the dispatcher when | Idempotent on | Returns / raises |
|---|---|---|---|
| `capabilities()` | Registry load, and before every `start` (preflight) | n/a (pure) | `Capabilities` |
| `start(spec)` | `_claim` has committed the Run row (`stage=running`) | `idempotency_key` + `spec_digest` | `Ack{status: queued\|running}`. Replay → same Ack with `replayed=true`. Same key with a different digest → `IDEMPOTENCY_CONFLICT` |
| `events(run_id, after_seq)` | Right after `start`, and again after a dispatcher restart | `(run_id, seq)`; at-least-once | Async iterator. It ends at a terminal status or `awaiting_approval` |
| `result(run_id)` | After the event stream ends | n/a (read). Stable once terminal | `RunResult`. Raises `INVALID_TRANSITION` while queued/running |
| `cancel(request)` | Operator cancel, shutdown, lost heartbeat | `request_id` | `Ack`. A terminal run is returned unchanged with `replayed=true` |
| `resume(decision)` | Operator answers an approval | `decision_id`; one decision per `approval_id` | `Ack{status: running\|cancelled}`. A conflicting decision → `DECISION_CONFLICT` |
| `heartbeat(run_id)` | Every `limits.heartbeat_interval_s` for non-terminal runs | n/a (read) | `Heartbeat`, or `UNKNOWN_RUN` |
| `recover()` | Once at dispatcher start, before any `start` | n/a | One `RecoveredRun` per non-terminal run the adapter knows |

`start` reports preflight refusals (missing binary, model not enforceable, workspace rejected) as a terminal `failed` run with a preflight error. It does not raise them, so they are recorded on the Run and shown on the card. This matches today's "could not start" path. Only a malformed spec raises (`INVALID_RUN_SPEC`).

## 3. Status state machine

```
              start()                 approval_requested
   (none) ──► queued ──► running ─────────────────────► awaiting_approval
                │  │       │  ▲                              │   │   │
                │  │       │  └──── resume(approve|answer) ──┘   │   │
                │  │       │                                     │   │
                │  │       ├──► succeeded                        │   │
                │  │       ├──► failed      ◄── checkpoint lost ─┘   │
                │  │       ├──► timed_out   ◄── approval_timeout_s ──┤
                │  └───────┴──► cancelled   ◄── cancel / reject ─────┘
                └──► failed (preflight)
```

Machine-readable form: `adapter_contract.TRANSITIONS` and `can_transition()`.

| From | Allowed to | Trigger |
|---|---|---|
| (none) | `queued` | `start` accepted and durably recorded |
| `queued` | `running` | Process spawned / runtime accepted the request |
| `queued` | `failed` | Preflight error (nothing ran) |
| `queued` | `cancelled` | `cancel` before spawn |
| `running` | `awaiting_approval` | Runtime asked for a decision (`approval_requested` event) |
| `running` | `succeeded` | Clean exit with a result, no error, model check passed |
| `running` | `failed` | Agent/provider/policy error, or an interrupted restart |
| `running` | `timed_out` | `limits.timeout_s` exceeded (MCD) or a provider timeout (runtime) |
| `running` | `cancelled` | `cancel` |
| `awaiting_approval` | `running` | `resume` with `approve` or `answer` (same run_id, `segment+1`) |
| `awaiting_approval` | `cancelled` | `resume` with `reject` (`DECISION_REJECTED`), or `cancel` |
| `awaiting_approval` | `timed_out` | `limits.approval_timeout_s` (optional; `null` = wait indefinitely, the default for human gates) |
| `awaiting_approval` | `failed` | The checkpoint cannot be resumed (session expired/missing) |
| terminal | none | Terminal states are final. A retry is a new run |

Rules:

- `awaiting_approval → succeeded` is impossible. An approval never completes work by itself; the agent must run again.
- **Cancel wins.** If a cancel is observed before the terminal status is persisted, the outcome is `cancelled`. This matches `handle.cancel_requested` precedence in `_run_process`.
- **The timeout clock pauses in `awaiting_approval`.** `deadline_at` is recomputed on resume from the time remaining.
- Every transition is emitted as a `status` event *before* it is visible through `heartbeat`/`result`.
- **Legacy stages.** `adapter_contract.LEGACY_STAGE` maps today's `Run.stage` values. `timeout` becomes `timed_out`. `interrupted` becomes `failed` + `INTERRUPTED`. The UI keeps its wording.

Card columns (`queued/running/review/done/failed`) are **not** part of this machine. They remain MCD's board state and are derived from run results by `_finish`/`on_finish` exactly as today.

## 4. Messages

All messages carry `schema_version: "rcd.adapter.v1"`. Field-level rules live in the schema. This section explains the decisions behind them.

### 4.1 RunSpec (`start`)

| Field | Source today | Purpose |
|---|---|---|
| `run_id`, `idempotency_key`, `work_key`, `attempt` | `Run.id` from `_claim`; uuid5 seed `mcd:story:<card_id>` | Idempotency (see §6) |
| `origin` | `ProjectTask`, `Card`, `ChatThread`/`ChatMessage` | Story key, revision, manifest hash, acceptance. Audit only; never authority |
| `prompt` | `projects.claim_context` (card body + `MCD SHARED PROJECT CONTEXT`) | Delivered verbatim. Never logged (`agents.redact`) |
| `context.digest`, `memory_refs`, `artifact_refs` | `projects.context` payload (`accepted_memory`, `accepted_artifacts`, `accepted_outputs`) | **Shared context.** The prompt already embeds the window. The refs let the runtime mount or verify the same memory and let MCD prove which context a run saw (`RunResult.context_digest`) |
| `model_policy.assigned` | `card.agent`, `card.model`, `card.agent_target` | The one route to run |
| `model_policy.approved_fallback_routes` | `projects.approved_story_routes` | Informational. Adapters must never use them; MCD alone moves to the next route |
| `model_policy.allow_runtime_fallback` | Hermes shim zeroes `get_fallback_chain` | Always `false` (schema `const`) |
| `model_policy.require_model_report` | Model-mismatch check in `_run_process` (Hermes/OpenClaw) | If the runtime cannot report the served model, refuse before inference |
| `workspace.path`, `mode`, `expected_branch` | `card.working_dir`, `card.mode`, manifest `workspaces[...].branch` | cwd and sandbox. Adapters must refuse (`WORKSPACE_REJECTED`) rather than relocate work. This is the run #35 OpenClaw lesson (memory #115) |
| `workspace.denied_tools` / `allowed_tools` | `build_claude` `--disallowedTools`, output-only `--tools Read,Glob,Grep` | Tool policy |
| `limits.timeout_s`, `kill_grace_s` | `card.timeout_s`, `KILL_GRACE_S=5` | Timeout/cancel |
| `limits.max_transient_retries` | Claude `api_retry` events | Same-model, in-run retries only |
| `limits.heartbeat_interval_s`, `approval_timeout_s`, `memory_limit_bytes` | new | Liveness, gate expiry, Pi cgroup cap |
| `budget.billing`, `max_cost_usd`, `max_output_tokens` | `card.budget_usd`, `settings.default_budget_usd`, `card.subscription_billing` | Paid routes (`api`, `openrouter`, `byok`) **must** carry a numeric cap (schema-enforced). Subscription may be `null`, as Claude omits `--max-budget-usd` today |
| `session.mode` / `session_id` | `spec.preassigned_session`, `card.resume_session`, `thread.session_id` | `new`, `preassigned` (OpenClaw-style) or `resume` |
| `output.format`, `json_schema` | `project_outputs.Output` for continuations | `handoff_text`, or `json` validated against the given schema |

### 4.2 Event (`events`)

Envelope: `{run_id, seq, segment, ts, type, data}`. `seq` is per run, strictly increasing, gap-free and persisted, so it survives an adapter restart. Consumers dedupe on `(run_id, seq)` and resume with `events(run_id, after_seq=last_seen)`.

| `type` | `data` | Replaces today |
|---|---|---|
| `status` | `{from, to, reason}` | `RunEvent(kind="stage")` |
| `log` | `{stream: agent\|stdout\|stderr\|adapter, text, truncated}` (redacted, ≤64 KiB) | Parser `feed()` lines to `run-<id>.log` |
| `tool_call` / `tool_result` | `{call_id, name, summary}` / `{call_id, ok, denied, summary}` | `tool: <name>`, `$ <command>` log lines |
| `model` | `{requested, reported, provider, session_id}` | `system/init`, `thread.started`, OpenClaw `agentMeta` |
| `usage` | `{cumulative: Usage, cost: Cost}` | `result`/`turn.completed` usage |
| `retry` | `{attempt, reason, delay_s, same_model: true}` | Claude `api_retry` |
| `approval_requested` | `ApprovalRequest` | Post-hoc `project_outputs.needs_approval` |
| `decision_applied` | `{decision_id, approval_id, verdict}` | `continue_output` memory record |
| `artifact` | `Artifact` | Workspace snapshot / `project_outputs.save` |
| `resource`, `heartbeat` | `{resources, status}` | new |
| `error` | `Error` | `parser.meta.error` |

Runtimes that only print one document at exit (OpenClaw today, `streams_events=false`) emit `status`, then nothing, then the decoded events at exit. That is still conformant; the UI shows "no live output".

### 4.3 RunResult (`result`)

Available in `awaiting_approval` or a terminal status. Key fields:

- `model.{requested, reported, provider, route, matches_assignment}`. `matches_assignment=null` when the runtime did not report a model.
- `usage` (tokens, requests, tool calls) and `cost{usd, source: reported|estimated|not_reported, billing, limit_usd}`.
- `resources{measured_by, peak_rss_bytes, cpu_user_s, cpu_system_s, wall_s, processes}`.
- `artifacts[]`. Files changed in the workspace and MCD-saved outputs, each with `sha256` where computed.
- `result_text`. The handoff, the same content as `Run.result_text`.
- `structured_output`. Parsed JSON when `output.format=json`, already validated against `output.json_schema`. Otherwise `null`. Invalid JSON gives `RESULT_INVALID`.
- `approval`. Required when `awaiting_approval`.
- `error`. `null` iff `succeeded`/`awaiting_approval`; required otherwise (schema-enforced).
- `context_digest` echoes `RunSpec.context.digest`. `last_seq` lets MCD confirm it has every event.

Mapping onto `Run` columns is 1:1 for `stage, exit_code, error, ended_at, duration_s, model_reported, provider, session_id, *_tokens, cost_usd, result_text`, so `_record_run` does not change shape.

### 4.4 Decision (`resume`)

`{decision_id, approval_id, verdict: approve|reject|answer, option_id?, answer_text?, approved_output_sha256?, actor, decided_at}`. Rules:

- `approved_output_sha256` must equal the `proposed_output.sha256` that was shown. If it doesn't match, the decision is refused. This is the same guard `accept_story` applies with `output_sha256`.
- `additionalProperties: false`. A decision **cannot** carry a model, route, workspace, mode, budget or tool change. Those require a new plan revision or an explicit operator retry route in MCD.
- `decision_id` is applied at most once. A replay returns the original Ack. A different decision for an `approval_id` that has already been decided raises `DECISION_CONFLICT`.

### 4.5 Heartbeat, CancelRequest, RecoveredRun, Capabilities

See the schema. Notes:

- **`Heartbeat.alive=false` is normal in checkpoint-mode `awaiting_approval`.** No process is waiting; the session or checkpoint is.
- **`CancelRequest.reason`** is one of `operator`, `shutdown`, `lost` or `superseded`.
- **`Capabilities` is how MCD knows an adapter's limits** before trusting it with a story. The four current agents' values are in `examples.json`.

## 5. Guarantees by evaluation criterion

The S2 evaluation criteria from the brief, and where the contract makes each one testable:

| Criterion | Contract mechanism | Failure surfaces as |
|---|---|---|
| **Reliable tool use and structured results** | `tool_call`/`tool_result` events (`capabilities.tool_events`). `output.format=json` + `json_schema`, returned as validated `structured_output`. `RunResult` schema with artifacts/status/usage/cost | `RESULT_MISSING`, `RESULT_INVALID`, `RESULT_INCOMPLETE`, `TOOL_DENIED` |
| **Respect assigned models and approved fallbacks** | `model_policy.assigned` is the only route. `allow_runtime_fallback: false`. `require_model_report`. `model` event + `matches_assignment`. Only `PROVIDER_RATE_LIMITED`/`PROVIDER_QUOTA_EXHAUSTED` are `fallback_eligible`, and MCD picks the next route from `approved_story_routes` | `MODEL_NOT_ALLOWED`, `MODEL_NOT_ENFORCEABLE`, `MODEL_MISMATCH` |
| **Shared context and clean handoffs** | Verbatim `prompt` with `MCD SHARED PROJECT CONTEXT`. `context.memory_refs`/`artifact_refs`. `context_digest` echo. `work_key` keeps one session lineage per story. `result_text` = handoff | Digest mismatch → MCD rejects the result |
| **Timeout, cancellation, retry, approval** | §3 state machine. `limits.timeout_s` (paused while awaiting). Process-group SIGTERM → `kill_grace_s` → SIGKILL. Bounded same-model `max_transient_retries` with `retry` events. `approval_requested` → `resume(decision)` | `TIMEOUT`, `PROVIDER_TIMEOUT`, `CANCELLED`, `DECISION_REJECTED`, `APPROVAL_TIMEOUT` |
| **Resource use on the Pi** | `Resources` in `resource`/`heartbeat` events and the result. `capabilities.resource_measurement`. `limits.memory_limit_bytes` | `measured_by: not_measured` is visible, not hidden |
| **Cost caps (OpenRouter)** | `budget` (numeric cap required for paid billing). Cumulative `usage` events with `cost.limit_usd`. `enforces_budget: runtime\|adapter\|none` | `BUDGET_EXCEEDED` |
| **Restart recovery without duplicate work** | `recover()`. Persisted `seq` + state. `start` idempotency. `awaiting_approval` survives restarts in checkpoint mode | `INTERRUPTED`, `LOST` |

## 6. Idempotency

| Key | Format | Scope | Guarantees |
|---|---|---|---|
| `idempotency_key` | `mcd:run:<run_id>` | One start attempt | `start` replays never spawn a second process. Different `spec_digest` → `IDEMPOTENCY_CONFLICT` |
| `work_key` | `mcd:story:<card_id>` (chat: `mcd:thread:<t>:message:<m>`) | All attempts/routes of one story | Seeds `preassigned_session()` = `uuid5(NAMESPACE_URL, "mcd:story:<id>")`, unchanged from `_claim`. Lets a retry resume the same session instead of restarting |
| `request_id` | `mcd:cancel:<run_id>:<n>` | One cancel | Repeat cancels are no-ops |
| `decision_id` | `mcd:decision:<run_id>:<n>` | One decision | Applied at most once. Conflicting decisions are refused |
| `(run_id, seq)` | event identity | One event | At-least-once delivery, dedupe by consumer |

`spec_digest` covers the fields that define the work (`run_id, work_key, attempt, model_policy, workspace, limits, budget, session, output`, plus a sha256 of the prompt). `origin` and `context` refs are audit data and are excluded. Because `_claim` writes the Run row inside `BEGIN IMMEDIATE` *before* `start` is called, a crash between the commit and `start` leaves a `running` row that the adapter does not know. `recover()` + `UNKNOWN_RUN` resolves that row to `INTERRUPTED`; it never resolves it to a silent re-run.

**What "without duplicate work" means here.** The contract guarantees that no run is started twice and no decision is applied twice. It cannot guarantee that an agent re-running a story after an interruption won't redo file edits. That is handled the way MCD handles it today: the retry is a new run, carries the checkpoint memory ("Partial work is unverified. Read the current workspace diff...") and resumes the same session via `work_key` where the runtime supports it. S3_durable_runs owns the storage details.

## 7. Timeout, cancellation, retry, approval, heartbeat, recovery

- **Timeout.** The adapter enforces `timeout_s`. The dispatcher also enforces `timeout_s + kill_grace_s + 10 s` as a backstop and then cancels with `reason=lost`. A provider/gateway timeout reported by the runtime (OpenClaw `status: timeout`, `GatewayClientRequestError ... timed out`) is `timed_out` + `PROVIDER_TIMEOUT`. MCD's own limit is `timed_out` + `TIMEOUT`. Both keep the existing "review partial work before retrying" wording.
- **Cancellation** sends SIGTERM to the process group (`start_new_session=True`), waits `kill_grace_s` (default 5), then SIGKILL. That is `Dispatcher._kill` today. A queued run is cancelled without spawning. A live-suspended run is killed. A checkpoint-suspended run just discards its checkpoint.
- **Retry.**
  - **In-run:** same request, same model, at most `max_transient_retries`, each emitting a `retry` event. It is never a model change.
  - **Cross-run:** MCD only. It auto-switches only for `fallback_eligible` errors and only to an untried route in `approved_fallback_routes`; this is `on_finish` today. Every other failure needs an explicit operator retry.
  - **Bounds:** S3_timeout_cancel sets the numeric caps.
- **Approval.** Two suspension modes are declared in `capabilities.suspend_modes`:
  - `live`: the process blocks on a permission or decision prompt; `resume` unblocks it.
  - `checkpoint`: the process exits after emitting `approval_requested` with a `session_id`; `resume` relaunches with `session.mode=resume` *under the same run_id* (`segment+1`). Claude plan-mode output approval is checkpoint mode. Today's dispatcher creates a separate continuation Run (`output_continuations[...].source_run_id`). S2_existing_adapters can map that as a segment, or keep both rows linked. Either way the decision is recorded once.
  - Human-gate stories (`assignee: human`) never reach an adapter.
- **Heartbeat.** The dispatcher polls every `heartbeat_interval_s` (default 15 s). After 4 missed intervals (≥60 s) with no events or heartbeats, it cancels with `reason=lost` and records `failed` + `LOST`.
- **Recovery.** Each adapter persists per-run state (spec digest, status, `seq`, pid/pgid, session id, approval checkpoint) in its own `state_dir` under the RCD data dir, mode 0700. `recover()` returns one of these outcomes:
  - `reattached`: the process is still alive and the adapter can follow it, for example a runtime with a daemon or a log file it can tail.
  - `awaiting_approval`: the checkpoint is intact.
  - `finished_while_down`: the result was persisted, so MCD records it.
  - `interrupted`: the process group was killed and the run becomes `failed` + `INTERRUPTED`.

  This replaces `Dispatcher.recover`'s blanket "running → interrupted" with a per-run answer, and approvals now survive restarts. `recover()` never relaunches.

## 8. Mapping the existing dispatch paths

Each row shows how today's code expresses the contract operation. **Gap** marks behaviour S2_existing_adapters must add or that remains a known limitation of that runtime.

| Contract | Claude (`build_claude`/`ClaudeParser`) | Codex (`build_codex`/`CodexParser`) | Hermes (`build_hermes` + `hermes_runtime.command` + `integrations/hermes/mcd-run.py`) | OpenClaw (`build_openclaw`/`OpenClawParser`) |
|---|---|---|---|---|
| `start`: spawn | `claude -p <prompt> --output-format stream-json --verbose` | `codex exec --json --skip-git-repo-check -C <dir>` | `hermes chat -q <prompt> --oneshot --format stream-json --in <dir>` launched through the MCD shim interpreter | `openclaw agent --agent <target> -m <prompt> --json` |
| idempotency | Run row before spawn. **Gap:** no replay check | same | same | same. `--session-id uuid5(mcd:story:<id>)` already uses `work_key` |
| `model_policy.assigned` | `--model` | `-m`, otherwise the `~/.codex/config.toml` default | `-m`. The shim pins it | `--model` |
| no runtime fallback | Claude CLI has none | none | Shim sets `get_fallback_chain → []` when pinned | **Gap:** OpenClaw gateway fallback is not disabled; only detected after the fact |
| model report / mismatch | `system/init.model` (at start) | **Not reported** (`reports_model: never`) | Shim injects `model`/`provider` into the `result` event | `result.meta.agentMeta.model` (at end) |
| mismatch → `MODEL_MISMATCH` | **Gap:** not checked today | Not possible | Checked in `_run_process` | Checked in `_run_process` |
| `workspace.mode` | `--permission-mode plan` (read) / `acceptEdits` (edit) | `-s read-only` / `workspace-write`. On resume, `-c sandbox_mode=` | Advisory only (`enforces_mode=False`) | Advisory only. Uses the gateway agent's own workspace (**gap**: run #35 rejection) |
| `denied_tools` / `allowed_tools` | `--disallowedTools git push/merge, gh pr merge`; output-only: `--tools Read,Glob,Grep`, empty MCP config | Sandbox only | Hermes tool policy | Gateway tool policy |
| `budget` | `--max-budget-usd` unless subscription | **Gap:** none | `--run-budget <timeout_s>` (time budget only) | **Gap:** none at CLI. OpenRouter key limit only |
| `session` | `--resume <id>`; `session_id` from `system/init` | `exec resume <id>`; `thread.started.thread_id` | `--resume <id>`; init `session_id` | Preassigned `--session-id` |
| `events` | JSONL stream: `system/init`, `assistant` text/`tool_use`, `api_retry`, `result` | JSONL: `thread.started`, `item.completed` (`agent_message`, `command_execution`), `turn.completed`, `turn.failed`/`error` | JSONL: `system/init`, `text`, `result` | Single JSON document at exit (`streams_events=false`) |
| `result` usage/cost | `result.usage` (+cache), `total_cost_usd` | `turn.completed.usage`. No cost | `result.tokens.{input,output}`. No cost | `agentMeta.usage.{input,output}`. No cost. **Gap:** query `openrouter_costs` for the key |
| structured output | `result.result` text. JSON for continuations via `project_outputs.parse` | `agent_message` text | `result.text` | `payloads[].text` |
| `cancel` | `_kill`: killpg SIGTERM → 5 s → SIGKILL, `cancel_requested` precedence | same | same | same. The gateway may continue upstream (noted in parser text) |
| timeout | `asyncio.wait_for(timeout_s)` → `timeout` | same | same, plus `--run-budget` | same, plus `--timeout`. `status: timeout` / gateway stderr → `PROVIDER_TIMEOUT` |
| `awaiting_approval` | Post-hoc: `project_outputs.needs_approval` on plan-mode text → checkpoint mode; resume via `--resume` continuation | **Gap:** none | **Gap:** none | **Gap:** none |
| quota → fallback | stderr regex `usage limit\|rate limit\|429...` → `PROVIDER_RATE_LIMITED`/`QUOTA_EXHAUSTED` → `on_finish` route switch | same | same | same |
| `heartbeat` | **Gap:** implicit (task alive). Add pgid liveness + psutil RSS | same | same | same |
| `recover` | `Dispatcher.recover`: all running → `interrupted` | same | same | same |
| resources | **Gap:** not measured. `subagents.running_processes` classifies processes but records no RSS | same | same | same |
| capabilities | `REGISTRY` fields: `enforces_mode`, `preassigned_session`, `default_model`, `available()` | same | `role=manager` | `agent_target` |

Error mapping from today's strings:

| Today (`Run.error` / parser) | Contract code |
|---|---|
| `could not start <agent>: FileNotFoundError/PermissionError` | `RUNTIME_UNAVAILABLE` |
| `MCD requires a Python Hermes launcher...`, shim exit 2 "could not enforce the Hermes model policy" | `RUNTIME_INCOMPATIBLE` / `MODEL_NOT_ENFORCEABLE` |
| `Agent reported a different model than the MCD assignment...` | `MODEL_MISMATCH` |
| `MCD stopped the run after its N s time limit...` | `TIMEOUT` |
| `OpenClaw provider timed out...` / `OpenClaw timed out <phase>...` | `PROVIDER_TIMEOUT` |
| `OpenClaw gateway rejected the run without returning JSON` | `PROVIDER_ERROR` |
| `no JSON result from openclaw` | `RESULT_MISSING` |
| Claude `is_error`, Codex `turn.failed`, Hermes non-zero `exit_code`, `exit code N` | `AGENT_ERROR` |
| `... (CLI reported a quota or rate limit)` | `PROVIDER_RATE_LIMITED` (or `PROVIDER_QUOTA_EXHAUSTED` when the text says quota/usage limit) |
| `cancelled by operator` | `CANCELLED` |
| `interrupted: service started/stopped...` | `INTERRUPTED` |
| `project_outputs.incomplete_error(...)` | `RESULT_INCOMPLETE` (applied by MCD, not the adapter) |
| `project_outputs.parse` failure on a continuation | `RESULT_INVALID` |
| `Story branch changed...` (in `claim_context`) | `WORKSPACE_REJECTED` (MCD preflight) |

Chat turns (`_claim_turn`) use the same operations with `origin.kind=chat_turn`, `timeout_s=900` and `work_key=mcd:thread:<t>:message:<m>`.

## 9. Error taxonomy

Canonical table: `adapter_contract.ERRORS`. Columns: the status the error implies, whether an explicit operator retry on the *same* route may help, whether MCD may switch to the next *approved* route automatically, and whether a human must look.

| Code | Category | Status | Retry same route | Auto-fallback | Human |
|---|---|---|---|---|---|
| `INVALID_RUN_SPEC` | preflight | failed | no | no | yes |
| `RUNTIME_UNAVAILABLE` | preflight | failed | yes | no | yes |
| `RUNTIME_INCOMPATIBLE` | preflight | failed | no | no | yes |
| `MODEL_NOT_ALLOWED` | preflight | failed | no | no | yes |
| `MODEL_NOT_ENFORCEABLE` | preflight | failed | no | no | yes |
| `WORKSPACE_REJECTED` | preflight | failed | no | no | yes |
| `PROVIDER_RATE_LIMITED` | provider | failed | yes | **yes** | no |
| `PROVIDER_QUOTA_EXHAUSTED` | provider | failed | yes | **yes** | no |
| `PROVIDER_AUTH` | provider | failed | no | no | yes |
| `PROVIDER_TIMEOUT` | provider | timed_out | yes | no | yes |
| `PROVIDER_ERROR` | provider | failed | yes | no | yes |
| `MODEL_MISMATCH` | policy | failed | no | no | yes |
| `BUDGET_EXCEEDED` | policy | failed | no | no | yes |
| `TOOL_DENIED` | policy | failed | no | no | yes |
| `SANDBOX_VIOLATION` | policy | failed | no | no | yes |
| `AGENT_ERROR` | agent | failed | yes | no | yes |
| `RESULT_MISSING` | agent | failed | yes | no | yes |
| `RESULT_INVALID` | agent | failed | yes | no | yes |
| `RESULT_INCOMPLETE` | agent | failed | yes | no | yes |
| `TIMEOUT` | lifecycle | timed_out | yes | no | yes |
| `CANCELLED` | lifecycle | cancelled | yes | no | no |
| `DECISION_REJECTED` | lifecycle | cancelled | no | no | no |
| `APPROVAL_TIMEOUT` | lifecycle | timed_out | yes | no | yes |
| `INTERRUPTED` | lifecycle | failed | yes | no | yes |
| `LOST` | lifecycle | failed | yes | no | yes |
| `IDEMPOTENCY_CONFLICT` | control | (call refused) | no | no | yes |
| `CONCURRENCY_CONFLICT` | control | (call refused; card stays queued) | yes | no | no |
| `UNKNOWN_RUN` | control | (call refused) | no | no | no |
| `INVALID_TRANSITION` | control | (call refused) | no | no | no |
| `DECISION_CONFLICT` | control | (call refused) | no | no | yes |
| `ADAPTER_INTERNAL` | internal | failed | yes | no | yes |

Two choices in this table need explaining:

- **Auto-fallback is restricted to quota and rate limits.** That is exactly today's `on_finish` behaviour and the operator's stated policy.
- **`BUDGET_EXCEEDED` is never auto-retried.** Raising a cap is an explicit human decision, either as a `budget_increase` approval or as a plan change.

Messages are operator-facing and redacted. Raw stderr is never copied into `Error.message`, as the existing parsers already insist.

## 10. Requirements for ZeroClaw and PicoClaw (S2_zeroclaw, S2_picoclaw)

An adapter is **eligible for the S2 benchmark** only if it passes the conformance suite (S2_conformance) and declares:

- `pins_model: true`, `disables_native_fallback: true` and `reports_model != never`. Otherwise every run fails `MODEL_NOT_ENFORCEABLE` under `require_model_report`.
- An OpenRouter budget enforced by `runtime` or `adapter`. The adapter can track `usage.cost` from OpenRouter generation stats and stop at `max_cost_usd`.
- `resource_measurement: cgroup`. Recommended: run each Pi run in a transient systemd scope (`systemd-run --user --scope -p MemoryMax=<memory_limit_bytes>`), then read `memory.peak` and `cpu.stat`. psutil is the fallback.
- `enforces_mode`. If the runtime cannot sandbox read vs edit, declare `false`; MCD will show the same "advisory" warning it shows for Hermes and OpenClaw today.
- The workspace is honoured as given. An adapter must never relocate into the runtime's home.

## 11. Out of scope / handed to later stories

- **Implementations** of any adapter, dispatcher refactor, DB migration for persisted `seq`/segments: S2_existing_adapters, S3_durable_runs.
- **Retry counts, backoff and the Pi timeout defaults:** S3_timeout_cancel.
- **Approval UI and decision storage:** S3_human_gates.
- **Cost-cap values and routing enforcement:** S3_routing, using the operator caps from S0_decide_scope.
- **Streaming transport to the browser:** S3_live_status. The event schema is designed to be forwarded as-is over SSE.
