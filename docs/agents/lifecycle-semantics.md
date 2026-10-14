# Timeout, cancel, retry and approval

This page describes how a run behaves when it runs too long, is stopped, fails, pauses for a human, or the
service restarts. It reflects the dispatcher and legacy adapter code as it stands, and it names the places where
the code is still known to fall short of the contract. The contract's design is in
[`adapter-contract.md`](adapter-contract.md) and [`docs/port/adapter-contract.md`](../port/adapter-contract.md).

## Summary

| Situation | What happens | Automatic retry? |
| --- | --- | --- |
| Wall-clock limit reached | Run ends `timed_out` (`TIMEOUT`). Partial output is quarantined. | Only if the card allows retries. |
| Idle limit reached | Run ends as a timeout, reported as idle. | Same as above. |
| Operator cancel | Process group is stopped. Run ends `cancelled` (`CANCELLED`). | Never. |
| Transient error (for example `PROVIDER_RATE_LIMITED`) | Run ends `failed`. | Only if the card allows retries and the code is retryable. |
| Quota or rate limit on a route | MCD may move the story to the next approved route. | Route switch, not a retry. |
| Service stopped or restarted mid-run | Run ends `failed` (`INTERRUPTED`) and is requeued with the same key. | Up to 3 interruptions, then the card fails. |
| Human approval requested | Run waits in `awaiting_approval` and does not hold a process. | No. Resumes on the same run after a decision. |
| Human rejects | Run ends `cancelled` (`DECISION_REJECTED`). Card fails. | Never. |

## Timeout

- **Wall clock.** Each card has `timeout_s`. The default is `settings.default_timeout_s`, which is 1800 s. The
  allowed range is 30 s to 6 h. The clock runs from `start`. It pauses while the run is `awaiting_approval`, and
  the remaining time is restored on resume.
- **Idle.** Each card may set `idle_timeout_s` (1 s to 6 h). When it is `NULL`, only the wall clock applies. The
  legacy path records the last output time. If the gap reaches the idle limit, the run ends as an idle timeout.
- **Dispatcher backstop (design).** The contract also specifies `timeout_s + kill_grace_s + 10 s`, after which the
  dispatcher cancels with `reason=lost`. This backstop is not confirmed in the code. Treat it as design only.
- **Provider timeouts** are reported as `PROVIDER_TIMEOUT` (state `timed_out`), not `TIMEOUT`. This distinction keeps
  operator-visible messages accurate.
- **Measured.** A 1 s limit ended at 1.011 s in the synthetic conformance run and at 1.012 s in the ZeroClaw
  rehearsal, both on a non-Pi host. Timeout is not measured on Pi hardware.

## Cancel

- An operator cancel on a `running` run is recorded in the run checkpoint. The dispatcher then signals the
  run's process group with SIGTERM. After the grace period it sends SIGKILL.
- **Grace period.** The contract says `kill_grace_s` defaults to 5 s. The legacy adapter sets `KILL_GRACE_S = 4.0`
  (`apps/api/legacy_adapters.py:38`). The 4.0 s value is what runs today. Reconcile the two before the grace
  period is documented as a fixed number.
- **Queued runs** are cancelled without spawning a process.
- **Awaiting-approval runs** are not cancelled with `/cancel`. Reject the decision instead. `/cancel` only acts on
  `running` runs.
- **Idempotent.** A cancel request is keyed by `request_id`. A repeat cancel on a terminal run returns the run
  unchanged with `replayed=true`.
- **Cancel wins** over a concurrent terminal status if the cancel was observed first.
- **Known gap.** The S3 review found that the cancel flag is saved in the checkpoint but not read back after a
  service restart. Until that is confirmed fixed, do not rely on a cancel surviving a restart. See *Open items*.
- **Usage after cancel.** Tokens already billed by the provider stay on the run. Provider usage that arrives after
  cancellation is only observed for a short window, so late charges may be missed. The conformance suite watches
  for 300 ms, which is not a guarantee.

## Retry

Retries are controlled per card.

| Field | Range | Default | Meaning |
| --- | --- | --- | --- |
| `max_attempts` | 1 to 10 | 1 | Total attempts for one story. `1` means no automatic retry. |
| `retry_backoff_s` | 0 to 3600 | 0 | Base delay. The wait before attempt *n+1* is `retry_backoff_s × 2^(n−1)`. |

- **Which failures retry.** The dispatcher's `_retryable` rule decides:
  - `timeout` always counts as retryable.
  - `cancelled` never retries.
  - Any other failure retries only if its error code is marked retryable in `adapter_contract.ERRORS`.
  - A retry happens only while `attempt < max_attempts`.
- **Same execution key.** An automatic retry keeps the execution key and the session lineage (`work_key`). It is
  a new run with a new `run_id` and a new attempt number.
- **Interruptions.** An interruption (service stopped or restarted) requeues the same execution with the same
  key. This happens at most `MAX_INTERRUPTIONS = 3` times (`apps/api/dispatcher.py:49`). After that the card fails.
- **Explicit operator retry.** After a terminal failure, an operator retry starts a new execution with a new key.
  This is how an operator selects a different approved route.
- **Quarantine.** Partial output from any non-success run is kept for diagnosis, but it is marked unpublishable.
  It cannot be accepted or handed on.
- **Routes, not retries, handle quota.** Quota and rate-limit errors can move the story to the next *approved*
  route. Adapters never choose the route themselves. A route switch is recorded as a new run.
- **Budget.** `BUDGET_EXCEEDED` is never retried automatically. Raising a cap is a human decision.

**Open defect.** Retrying a run that timed out, or one that was interrupted and then retried after a restart, has
been reported to fail with `IDEMPOTENCY_CONFLICT` because the spec digest differs. The S3 code review rated this
High (finding H1). The durable-runs notes say the same-key path is limited on Pi runtimes. Do not treat automatic
retry as working end-to-end until that finding is closed and tested.

## Approval and human decisions

- **When a pause is allowed.** A run may wait for a human only if its adapter declares `checkpoint` suspension,
  its process has exited (`alive: false`, `pid: null`), and the request carries a durable checkpoint reference.
  If any of these fails, the run is cancelled with `RUNTIME_INCOMPATIBLE`. This rule means a live prompt, such as
  ZeroClaw's `[Y]es/[N]o` tool prompt, never holds RAM while it waits. Budget-increase requests are refused with
  `BUDGET_EXCEEDED`.
- **While waiting.** The run stays `awaiting_approval` with no end time and no PID. Its card moves to `review`.
  The card cannot be requeued, approved or deleted until a decision is made (HTTP 409). Pruning skips the run.
  Overlapping work on the same directory is not started.
- **A pause is not a result.** It does not create a handoff, a retry, an output or a publication.
- **Decision endpoint.** `POST /api/runs/{id}/decision` takes `approval_id`, `decision_id`, `verdict`
  (`approve`, `answer` or `reject`), and optionally `answer_text`, `option_id` and `approved_output_sha256`.
  - Extra fields, such as `model`, are rejected with HTTP 422.
  - Agent grants are refused with HTTP 403. The server sets the actor and timestamp.
  - A stale `approval_id`, an option that was not offered, or an outdated output hash returns HTTP 409.
  - An exact retry returns `replayed: true`.
  - A different decision for an approval that is already decided returns HTTP 409 `DECISION_CONFLICT`.
- **Resume without repeating work.** The decision is saved before `resume()` is called. Resume reuses the same run
  row, execution key and attempt number. No new `start`, prompt, model choice or row is created. Steps before the
  checkpoint are not repeated. The adapter's journal of completed tool calls prevents a tool from running twice.
- **Restart.** A saved decision that has not been applied is applied on the next dispatcher tick. A run that
  paused while the service was down resumes from the runtime's checkpoint.
- **Reject.** The run ends `cancelled` with `DECISION_REJECTED`, and the card fails. No work after the checkpoint
  runs. Any partial output is quarantined. A run that later reports success is refused (`RESULT_INVALID`).
- **A decision that cannot be applied** (route no longer approved, cap exceeded, invalid acknowledgement) does not
  stop the dispatcher. The checkpoint is cancelled, the run and card fail with the error code, and the decision is
  kept for audit but never replayed.
- **Approval timeout.** `approval_timeout_s` is optional. For human gates it is `null`, meaning the run waits
  indefinitely. When it is set, expiry ends the run as `APPROVAL_TIMEOUT`.

**Open defects in approval.**

- A restart after a human decision was recorded can requeue the run as an ordinary interruption, without checking
  the decision. The S3 review rated this High (finding H4). A rejected story could then run again.
- Security review finding H1: an agent process on the same host can reach the control API on loopback and call the
  decision endpoint, because sign-in is off by default. The `403` for agent grants does not stop a process that sends
  no grant. Decisions must be treated as untrusted until the API requires sign-in and agents run as a separate user.

## Open items at a glance

These are the open items the handoffs and reviews record. Confirm each is closed before relying on it.

| Item | Source | Status recorded |
| --- | --- | --- |
| Retry after timeout fails with `IDEMPOTENCY_CONFLICT` | Code review H1; human-gates handoff | Open |
| Cancel flag not read back after restart | Code review H3 | Open in review; the S3 timeout handoff reports it as durable |
| Restart after a decision re-runs work | Code review H4 | Open |
| Agents can call the control API on loopback | Security review H1 | Open |
| `KILL_GRACE_S` 4.0 s in code vs 5 s in contract | This review | Reconcile |
| Pi timeout and cancel conformance on hardware | S3 timeout handoff | Not run |

Items marked open here are as recorded in the handoffs and reviews at the time they were written. The repo has no
`.git` history, so re-check them against current code before acting.
