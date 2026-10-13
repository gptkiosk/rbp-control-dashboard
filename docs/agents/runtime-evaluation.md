# Runtime evaluation: ZeroClaw versus PicoClaw

**Status: no runtime is selected.** The choice is a human gate, `S2_decide_runtime`, and no decision record
exists in the repository yet. No benchmark results have been committed (`bench/results/` does not exist).
This page records the evidence that does exist, what it shows, and what is still missing. It is not a
decision.

## Criteria

The operator's brief sets five criteria. Each row below records what the repo shows for each runtime.

1. Reliable tool use and structured results
2. Respect for assigned models and approved fallback routes
3. Shared context and clean handoffs between agents
4. Clear timeout, cancellation, retry and approval behaviour
5. Actual memory consumption on the Pi

## Evidence

### ZeroClaw (`integrations/zeroclaw/`, runtime 0.8.5, aarch64)

| Criterion | What the code and tests show | What is not yet shown |
| --- | --- | --- |
| 1. Tool use | Tool events are reported (`tool_events: true`). Unknown tool names are refused with `TOOL_DENIED` before start. Tool calls are read from the runtime trace. | A free model that reliably uses tools (G8). A loop guard ends repetitive runs as `AGENT_ERROR` (G9, observed offline). |
| 2. Models and fallback | `pins_model`, `disables_native_fallback` and free-only admission are implemented. A local proxy holds the key, refuses any model other than the assigned one, and withholds a response whose served model differs. | Exact served-model matching against live OpenRouter aliases (G7). No live run has been made. |
| 3. Shared context | Each run gets its own process and config. Memory and artifacts are passed in the prompt. | `session: none`. A resumed session across runs is refused with `RUNTIME_INCOMPATIBLE` (G2). Cross-run continuity depends on the prompt alone. |
| 4. Timeout, cancel, retry, approval | Wall-clock timeout, process-group cancel, idempotent start and restart recovery (marked `INTERRUPTED`) are covered by tests. Timeout measured at about 1.01 s for a 1 s limit. Approve, reject and approval timeout are covered. | Approval is live only (G1). It cannot survive a restart and fails the checkpoint conformance case by design. Free-text `answer` is not supported (G3). |
| 5. Memory | About 33 MB RSS for an idle one-shot run, measured on a Lima aarch64 VM. The cgroup scope path (`systemd-run --scope`, `MemoryMax`) is written. | **No Pi measurement exists.** The Pi limits (G12) are unverified. |

Test results as recorded by its README, not re-run for this page: `tests/zeroclaw` 48 passed on the Lima
Ubuntu 24.04 aarch64 VM. A rehearsal of the conformance suite against the real binary and a scripted provider
passed 20 of 21 cases. The one failure is G1, the checkpoint approval case, which cannot pass by design. The
rehearsal proves plumbing only. It does not show how a real model behaves.

### PicoClaw (`integrations/picoclaw/`)

| Criterion | What the code and tests show | What is not yet shown |
| --- | --- | --- |
| 1. Tool use | `tool_events: false`. No correlated tool receipts. | Any tool-use evidence. Not eligible for the synthetic tool workloads. |
| 2. Models and fallback | `pins_model: true`, `reports_model: never`, native fallback removed from the generated config. Paid runs fail `BUDGET_EXCEEDED` before a process starts. | The served model cannot be confirmed from the CLI output. A provider/tool proxy is required and does not exist yet. |
| 3. Shared context | One-shot runs with a preassigned session. | No reattachment and no same-key retry (durable-runs handoff). |
| 4. Timeout, cancel, retry, approval | Process group, SIGTERM then SIGKILL, and a private home per run. | Recovery terminates instead of reattaching and does not reconstruct the in-memory result. `suspend_modes` is empty, so approval is refused. |
| 5. Memory | `resource_measurement: not_measured`. | No measurement of any kind. |

**Key blocker.** The S3 routing handoff records that PicoClaw rejects all unmetered runs, including those
labelled free, before the process starts. The project's policy is free-only spend. So PicoClaw cannot run any
story under the current policy. Its README states that it is not live-conformance eligible yet.

Tests: `tests/picoclaw/test_adapter.py` exists. It was not re-run for this page.

## What the evidence shows

- **ZeroClaw is the only candidate that meets the Pi budget and model-pinning requirements today.** It has a
  provider boundary, free-only admission and cost receipts. PicoClaw has none of these and cannot run a story.
- **ZeroClaw still has real gaps.** It has no checkpoint approval, no cross-run session continuity, and no live
  OpenRouter run. None of its numbers have been measured on a Pi.
- **Neither runtime has Pi evidence.** No timing, memory or reliability figure from a Raspberry Pi is in the repo.

On this evidence ZeroClaw is the better candidate for a pilot. The choice of runtime still belongs to the operator.
It should be recorded as a decision, not inferred from this page.

## What is needed to decide

1. **Live, free-only conformance** for each candidate, against an operator-approved free model snapshot and
   with the key held by the provider proxy. The conformance README and ZeroClaw README give the commands. A
   PicoClaw live path requires the provider proxy described in its README.
2. **Pi benchmark runs** on each supported Pi with `bench/run.sh --live --free-only`. The report gives median and
   p95 for wall time, CPU, peak RSS and timeout overshoot, per hardware target. The bench README has the details.
3. **A recorded decision** with the operator's name, the date, the criteria and the evidence used.

Until these are done, the Pi runtime is not selected and no measured Pi memory figure can be quoted.
