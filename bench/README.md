# RCD runtime benchmark (S2_benchmark)

Measures ZeroClaw and PicoClaw (and anything else with a conformance `Driver`) on a Raspberry Pi.
Measurement only: no runtime or adapter code is changed.

## One command

```sh
bench/run.sh                                   # synthetic self-test: no network, no spend
cp bench/config.example.json bench/config.json # fill in approved OpenRouter models
export OPENROUTER_API_KEY=...                  # consumed by the runtime drivers, never written to results
export RCD_ZEROCLAW_FREE_MODELS=/path/free-models.json  # fresh zero-price snapshot (ZeroClaw driver)
bench/run.sh --live --free-only                # real runs, ':free' models only, $0 paid spend (project policy)
bench/run.sh --live --cost-cap-usd 2.00        # only if a paid cap is ever approved by the operator
```

Run it on **each** supported Pi (Pi 4 4 GB, Pi 4 8 GB, Pi 5, ...). The hardware target is read from
`/proc/device-tree/model` (override with `--target`). `bench/results/REPORT.md` is rebuilt from every
`bench/results/*/results.json`, so copying result directories from several Pis into one place gives one
report with one table per hardware target. Unit self-tests: `python -m pytest bench/tests` (needs the
`tests/adapter_conformance/requirements.txt` packages).

## What a cell is

A cell is one `(runtime, LLM model)` pair. Each cell runs the **same 20 stories** (`rcdbench/cell.py:STORIES`),
in a fresh worker process, using the same `Probe`/`Driver` seam and the same synthetic tools as the
conformance suite:

| Stories | Workload | Checked |
| --- | --- | --- |
| 1-5 | structured result | RunResult schema valid, `{"ok":true,"value":str}` |
| 6-9 | tool call (`echo`) | returned tool value appears in output |
| 10-13 | `memory_write` / `memory_read` x2 | value written by an earlier story is read back |
| 14-15 | `artifact_write` | file contains `one artifact` |
| 16-17 | approval checkpoint, then resume | no repeated pre-gate write, `continued from checkpoint` |
| 18 | never-ending run, 3 s timeout | status `timed_out`; overshoot beyond 3 s |
| 19 | never-ending run, cancelled after metered usage | `cancelled`; cancel ack and cancel-to-terminal latency |
| 20 | provider reports a model other than the assigned one | adapter must **not** succeed |

## Metrics and how each is obtained

- **Peak / steady RSS**: a sampler thread walks `/proc` every 100 ms, summing `VmRSS` over all descendants of the
  worker (the runtime processes; the Python harness itself is excluded). Peak = max of sampled RSS and live `VmHWM`.
  Steady = median over samples where a runtime process existed. Per-story and per-cell values are reported.
- **cgroup `memory.peak`**: each cell worker runs in `systemd-run --user --scope` so its cgroup belongs to that cell;
  `memory.peak` is read at the end (bytes, includes page cache and the harness's own baseline of
  `harness_baseline_rss_kb`). Without systemd the worker reads its own cgroup and the value is shared; `cgroup.peak_reset`
  records whether the kernel (>= 6.12) allowed resetting it. Missing files give `n/a`, never an estimate.
- **CPU**: per story, `getrusage` self + reaped children delta; reported as % of story wall time. Cell total from
  cgroup `cpu.stat usage_usec` when available.
- **Startup time**: monotonic seconds from the `start()` call to the first event showing status `running`.
- **Structured-result success**: fraction of stories 1-17 whose `RunResult` validates against the schema and whose
  output has the expected content.
- **Model-pin violations**: counted from **independent provider receipts** (served model != assigned model), a
  succeeded result with `matches_assignment != true`, or story 20 succeeding.
- **Timeout latency**: seconds past the 3 s limit until the terminal result. **Cancel latency**: `cancel()` ack time,
  and `cancel()` to terminal result.
- **Cost**: sum of `cost_usd` from provider receipts (OpenRouter response metadata), not from the adapter's claim.
- **Backend memory**: `apps/api/serve.py` is started on a free loopback port (never 8800) with a temp data dir,
  collector and dispatcher disabled, and only that spawned PID is signalled. *Idle* = median RSS over 10 s after
  health is up; *loaded* = RSS while 8 threads issue requests for 15 s (`/healthz`, `/api/metrics/current`,
  `/api/projects`, `/`). Unauthenticated 401s still exercise the request path. Run `rcd` backend and runtime cells
  sequentially, so backend memory is not mixed into runtime RSS.

All tables report `median / p95` (linear-interpolated percentile) over the stories in the cell; with N=20 the p95 is
interpolated between the two slowest stories, so treat it as indicative.

## Cost controls

- **Free-only (`--live --free-only`, current project policy):** paid spend is $0. A model not ending in `:free` is
  refused before dispatch (cell status `refused`). RunSpecs carry `billing: free` and `max_cost_usd: 0`, the runtime
  driver's own catalog admission (price snapshot) still applies, and a cell stops with `paid_spend_detected` skips
  at the first non-zero cost receipt. The run exits 3 if any spend is recorded. `--free-only` cannot be combined with
  `--cost-cap-usd`; no positive allowance is invented.
- Paid mode: `--live` is refused without a finite positive `--cost-cap-usd`. The total is split evenly per cell, and a cell
  never gets more than the remaining budget. The conformance `Budget` gives each run 1/64 of the cell cap as
  `RunSpec.budget.max_cost_usd`; remaining stories are skipped (and shown as skipped) once 95 % of the cell cap is spent.
- The driver must enforce each run's cap **before** provider requests (see `tests/adapter_conformance/README.md`).
  The harness only detects overshoot afterwards (non-zero exit if total spend exceeds the cap).
- Fallback is never invoked automatically; the fallback route is only passed as informational policy.

## Status of live runs

No live results are included. The ZeroClaw adapter and its conformance driver now exist
(`integrations/zeroclaw/conformance.py`) but have not been run against a real provider (needs a free-model snapshot
and an OpenRouter key). PicoClaw has no live driver module (`integrations/picoclaw/conformance.py` is missing) and its
adapter fails closed for paid runs, so it records `unavailable` until a metering proxy and driver are written. A cell whose
factory cannot be imported is recorded as `unavailable` with the reason, never given invented numbers. Results
from the built-in `fake` runtime are labelled `synthetic` and only demonstrate the harness.
