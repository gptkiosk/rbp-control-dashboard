# Adapter contract (`rcd.adapter.v1`)

This page summarises the contract for people who write or operate runtimes. The normative design is
[`docs/port/adapter-contract.md`](../port/adapter-contract.md). The Python interface is
`apps/api/adapter_contract.py`, and the JSON Schema is in `apps/api/adapter_schemas/`.

## Principles

1. **MCD decides, adapters report.** An adapter runs exactly the route it is given. It never switches models,
   queues work, accepts its own handoff or widens permissions. Fallback, retries, dependency order and
   acceptance stay in MCD.
2. **The run is the unit of work; the story is the unit of idempotency.** Each attempt has a `run_id` and an
   idempotency key `mcd:run:<run_id>`. Retries and fallbacks are new runs that share the story's `work_key`
   `mcd:story:<card_id>`.
3. **Output is proposed evidence.** `succeeded` means the process finished cleanly with a result. It does not
   mean the work was accepted.
4. **Unknown means unknown.** A field the runtime cannot report is `null`, labelled `not_reported` or
   `not_measured`. It is never guessed.
5. **Language-neutral wire format.** The JSON Schema is normative. An adapter may be a thin Python wrapper
   around a CLI or a native binary.

## Interface

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

| Operation | Called when | Idempotent on | Returns or raises |
| --- | --- | --- | --- |
| `capabilities()` | Registry load, and before every `start` | n/a | `Capabilities` |
| `start(spec)` | After the Run row is committed as `running` | `idempotency_key` + `spec_digest` | `Ack`. Same key and digest gives `replayed=true`. Same key, different digest raises `IDEMPOTENCY_CONFLICT`. |
| `events(run_id, after_seq)` | Right after `start`, and after a dispatcher restart | `(run_id, seq)`; at least once | Async iterator that ends at a terminal status or `awaiting_approval` |
| `result(run_id)` | After the event stream ends | Read; stable once terminal | `RunResult`. Raises `INVALID_TRANSITION` while queued or running. |
| `cancel(request)` | Operator cancel, shutdown, lost heartbeat | `request_id` | `Ack`. A terminal run is returned unchanged with `replayed=true`. |
| `resume(decision)` | Operator answers an approval | `decision_id`; one decision per `approval_id` | `Ack` (`running` or `cancelled`). A conflicting decision raises `DECISION_CONFLICT`. |
| `heartbeat(run_id)` | Periodically for non-terminal runs | Read | `Heartbeat`, or `UNKNOWN_RUN` |
| `recover()` | Once at dispatcher start, before any `start` | n/a | One `RecoveredRun` per non-terminal run the adapter knows |

`start` reports preflight refusals (missing binary, model not enforceable, workspace rejected) as a terminal
`failed` run with an error. It does not raise them. Only a malformed spec raises `INVALID_RUN_SPEC`.

## Status states

```
(none) -> queued -> running -> succeeded | failed | timed_out | cancelled
                     |  ^
                     v  |  resume(approve | answer)
                  awaiting_approval -> cancelled (reject, cancel) | timed_out | failed
```

- `awaiting_approval` never goes directly to `succeeded`. The agent must run again.
- Cancel wins when it is observed before a terminal status is saved.
- Terminal states are final. A retry is a new run.
- Every transition is emitted as a `status` event before it is visible through `heartbeat` or `result`.
- Card columns (`queued`, `running`, `review`, `done`, `failed`) are MCD's board state. They are derived from the
  run result and are not part of this state machine.

The canonical table is `adapter_contract.TRANSITIONS` and `can_transition()`.

## Messages

Every message carries `schema_version: "rcd.adapter.v1"`. The fields that matter most:

- **`RunSpec`** carries the run and work keys, `origin` (audit only), the verbatim `prompt`, shared context
  references (`memory_refs`, `artifact_refs`, `context.digest`), `model_policy`, `workspace`, `limits`, `budget`,
  `session` and `output`.
  - `model_policy.assigned` is the one route to run.
  - `model_policy.approved_fallback_routes` is informational only. Adapters must never use it.
  - `model_policy.allow_runtime_fallback` is always `false`.
  - Paid routes must carry a numeric `budget.max_cost_usd`. The schema enforces this.
- **`Event`** is `{run_id, seq, segment, ts, type, data}`. `seq` is per run, strictly increasing and persisted.
  Types are `status`, `log`, `tool_call`, `tool_result`, `model`, `usage`, `retry`, `approval_requested`,
  `decision_applied`, `artifact`, `resource`, `heartbeat` and `error`.
- **`RunResult`** holds `model` (requested, reported, `matches_assignment`), `usage`, `cost` (with `source`),
  `resources`, `artifacts`, `result_text`, `structured_output`, `approval`, `error` and `context_digest`.
  `error` is `null` only for `succeeded` or `awaiting_approval`.
- **`Decision`** is `{decision_id, approval_id, verdict: approve|reject|answer, option_id?, answer_text?,
  approved_output_sha256?, actor, decided_at}`. It has `additionalProperties: false`, so a decision cannot change
  the model, route, workspace, mode, budget or tools. Those need a new plan revision or an explicit operator retry.
- **`Capabilities`** declares the runtime's limits. Pi eligibility requirements are in
  [adding a runtime](adding-a-runtime.md#eligibility-requirements-for-pi-runtimes).

## Error codes

The full table is `adapter_contract.ERRORS`. Each code gives a status, a category, whether an explicit operator
retry on the same route may help (`retryable`), whether MCD may move to the next approved route automatically
(`fallback_eligible`), and whether a human must look (`requires_human`).

| Code | Status | Retryable | Auto-fallback |
| --- | --- | --- | --- |
| `RUNTIME_UNAVAILABLE` | failed (preflight) | yes | no |
| `MODEL_NOT_ENFORCEABLE` | failed (preflight) | no | no |
| `MODEL_MISMATCH` | failed | no | no |
| `PROVIDER_RATE_LIMITED`, `PROVIDER_QUOTA_EXHAUSTED` | failed | yes | **yes** |
| `PROVIDER_TIMEOUT` | timed_out | yes | no |
| `BUDGET_EXCEEDED` | failed | no | no |
| `TIMEOUT`, `APPROVAL_TIMEOUT` | timed_out | yes | no |
| `CANCELLED` | cancelled | yes | no |
| `DECISION_REJECTED` | cancelled | no | no |
| `INTERRUPTED`, `LOST` | failed | yes | no |
| `IDEMPOTENCY_CONFLICT`, `UNKNOWN_RUN`, `INVALID_TRANSITION` | call refused | no | no |

Two choices matter. Automatic fallback is limited to quota and rate-limit errors, which matches the operator's
policy. `BUDGET_EXCEEDED` is never retried automatically, because raising a cap is a human decision.

Messages are redacted. Raw stderr is never copied into `Error.message`.

## Where the contract is enforced today

- The dispatcher (`apps/api/dispatcher.py`) applies the status transitions, the retry rule and the approval gate.
  See [timeout, cancel, retry and approval](lifecycle-semantics.md).
- The legacy adapters for Claude, Codex, Hermes and OpenClaw (`apps/api/legacy_adapters.py`) implement the
  operations for the existing agents. Their gaps are listed in `docs/port/existing-adapters.md`.
- `tests/adapter_conformance/` runs the behavioural checks against any adapter.
