# ZeroClaw adapter (`rcd.adapter.v1`, OpenRouter, free-only)

Implements `apps/api/adapter_contract.py::AgentAdapter` for ZeroClaw **0.8.5** (aarch64 Linux). The contract is
unchanged. Status: implemented and tested offline and on the Lima Ubuntu 24.04 aarch64 VM against the real
binary; **not yet run live** against OpenRouter and **not run on physical Pi hardware** (see "Remaining").

## How it works

```
MCD dispatcher -> ZeroClawAdapter -> `zeroclaw agent -m ...` (own process group, private config dir)
                                         |  provider "custom" -> http://127.0.0.1:<port>/v1   (per-run bearer token)
                                         v
                                   ProviderProxy  -- holds OPENROUTER_API_KEY, admits, meters --> OpenRouter
```

* `adapter.py` - the adapter: one process per run, durable JSON state, events, result, cancel, resume, heartbeat, recover.
* `proxy.py` - loopback provider boundary. Per request it checks: run token, run open, request cap, model equals the
  assigned model, model still verified zero-priced; forces `stream:false`, strips `models`/`route`, sets OpenRouter
  `provider.max_price` to 0 (second, upstream guard). It records independent receipts (response id, **served** model,
  provider, tokens, cost) and withholds the response on served-model mismatch or non-zero cost. Closing a run aborts
  in-flight upstream connections.
* `admission.py` - fail-closed free-only catalog (exact id, every price field zero, snapshot <= 24 h old, otherwise refuse).
* `runtime_config.py` - renders a minimal per-run `config.toml` (single provider, no `fallback`/`fallback_models`/
  `model_routes`, `native_tools = true`, `workspace_only`, tool allow/auto-approve lists, readonly level for `mode: read`).
* `conformance.py`, `mcp_bridge.py`, `callid.py` - test instrumentation for the live conformance driver (not production).
* `install-zeroclaw.sh` - pinned, SHA-256-verified install of the release archive.

## Why a proxy

ZeroClaw's `openrouter` provider type ignores `uri` and has no env-var key, so it can neither be metered nor kept
off disk. The real key lives only in the proxy process environment; the per-run config contains only a run token and is
deleted when the run ends. This also provides the SEC-013 pre-request guard and receipts that do not come from the
runtime's own report of itself.

## Install and configure on a Pi (64-bit Raspberry Pi OS)

```sh
integrations/zeroclaw/install-zeroclaw.sh                  # -> ~/.local/share/rcd/zeroclaw/zeroclaw
cp integrations/zeroclaw/free-models.example.json /var/lib/rcd/free-models.json   # replace with a real snapshot
```

Build the snapshot from the public model list (no key needed) with `snapshot_from_openrouter_models()`
(`admission.py`), then review it: the operator, not the adapter, chooses which free models are acceptable. The
adapter only wires up:

```python
proxy = ProviderProxy(FreeModelCatalog.load(Path("/var/lib/rcd/free-models.json")))   # reads OPENROUTER_API_KEY per request
proxy.start()
adapter = ZeroClawAdapter(ZeroClawConfig(state_dir=Path("/var/lib/rcd/zeroclaw"), proxy=proxy, catalog=..., 
                                         executable=".../zeroclaw", use_systemd_scope=True))
```

`use_systemd_scope=True` runs each run in `systemd-run --user --scope` (cgroup memory/CPU measurement, `MemoryMax` from
`limits.memory_limit_bytes`). Without it, resources are sampled with psutil if present.

## Contract mapping

| Contract item | ZeroClaw mapping |
| --- | --- |
| Model pinned per run | per-run config + `--model`; proxy refuses any other model; no fallback config rendered |
| Served model / usage / cost | proxy receipts from OpenRouter responses (`model`, `provider`, `usage`, `usage.cost`) |
| Tools | MCD names -> `file_read, glob_search, content_search, file_write, file_edit, shell, web_fetch, web_search_tool`; unknown names -> `TOOL_DENIED` before start |
| `mode: read` | `risk_profile.level = readonly` (runtime-enforced) |
| Events | `runtime-trace.jsonl` tailed (`tool_call`/`tool_result`), plus `model`, `usage`, `artifact` events; call ids are content-addressed |
| Timeout | wall clock from `start()`, paused while `awaiting_approval`; SIGTERM, `kill_grace_s`, SIGKILL to the process group |
| Cancel | closes proxy run (no new requests, in-flight aborted), kills process group; idempotent by `request_id` |
| Approval | ZeroClaw's own `[Y]es/[N]o` tool prompt on stderr; `resume` answers on stdin. `resume_mode: "live"` |
| Idempotency | `idempotency_key` + spec digest; concurrent starts share one process |
| Recovery | `recover()` kills an orphan whose cmdline still matches the run dir, marks `failed/INTERRUPTED`, never relaunches |

## Gap list against the contract

| # | Gap | Effect | Status |
| --- | --- | --- | --- |
| G1 | No checkpoint/resume mode. Approvals are live: the process waits on stdin | `approval_checkpoint_resume` conformance case **cannot pass** (requires `resume_mode: checkpoint`, a session id and state ref). A paused approval does not survive adapter/host restart: `recover()` reports `INTERRUPTED` | Unpassable by design; live approval/rejection/timeout covered by `test_zeroclaw_runtime.py` |
| G2 | `session: none`: one-shot `-m` has no resumable session (`--session-state-file` is interactive-only) | `session.mode = resume` -> `RUNTIME_INCOMPATIBLE`; `session_id` always null | Documented |
| G3 | Approval answers limited to approve/reject (`answer` -> `INVALID_TRANSITION`) | no free-text answers via this path | Documented |
| G4 | Prompt passed in argv (limit 100 kB; visible to local users via `ps`) | larger prompts -> `INVALID_RUN_SPEC` | Documented; acceptable on a single-user Pi |
| G5 | `custom` provider type must set `native_tools = true`; otherwise 0.8.5 drops the tool exchange from the second request | handled in renderer, regression-tested | Fixed |
| G6 | Usage of a request abandoned in flight (cancel/timeout) is unobservable | $0 under free-only policy; a paid policy would need ledger reconciliation | Documented |
| G7 | Served-model equality is exact string match; OpenRouter may report a different alias form for `:free` routes | would fail runs as `MODEL_MISMATCH` (fail-closed) | **Unverified live** |
| G8 | Free models often lack tool support (OpenRouter returns an error when no endpoint supports tools) | such runs fail `PROVIDER_ERROR`; model choice is an operator concern | **Unverified live** |
| G9 | `ZeroClaw` repeated-identical-tool-call loop guard ends a run as `AGENT_ERROR` | affects looping workloads only | Observed offline |
| G10 | Artifacts come from a before/after file scan (skips `.git`, `node_modules`, `.venv`; > 20 000 files -> none reported) | not a git-aware diff | Documented |
| G11 | `reports_model` is `at_end`; cost is `reported` only when OpenRouter returns `usage.cost`, else `estimated` from the zero-price catalog | no positive estimate is ever made | By design |
| G12 | Pi hardware limits (`TasksMax`, `MemoryMax`) verified only on the aarch64 VM | physical-Pi numbers not measured | Pending |

## Verification (Lima `pi4-test`, Ubuntu 24.04.5 aarch64, ZeroClaw 0.8.5, Python 3.12)

* `tests/zeroclaw`: 48 passed (admission, config rendering, proxy, preflight, and the real binary against a loopback
  OpenRouter stand-in: structured result, tool use, approve/reject/approval-timeout, timeout ~1.01 s for 1 s, cancel,
  served-model mismatch, provider error mapping, idempotent concurrent start, restart recovery).
* Together with existing suites: `tests/zeroclaw tests/picoclaw bench/tests tests/adapter_conformance`: 92 passed.
* **Rehearsal** of the *unchanged* `tests/adapter_conformance/test_conformance.py` against the real binary, the real
  driver and a *scripted* provider (`tests/zeroclaw/rehearsal.py`): 20 of 21 passed; the failing case is G1. Timeout
  measured 1.012 s. This proves plumbing only. The provider is a script, not an LLM, so it says nothing about how well a
  free model follows the workloads. Do not cite it as live conformance.
* Idle one-shot ZeroClaw RSS about 33 MB (VM, `/usr/bin/time`); not a Pi measurement.

## Remaining before the acceptance criterion ("runs live within the approved cap") can be met

1. **Free-only mode in the harness.** `tests/adapter_conformance/conftest.py` requires `RCD_CONFORMANCE_COST_CAP_USD > 0`
   and writes `billing: "api"`. This adapter accepts that only because it refuses every non-zero-priced model and the
   proxy aborts on any non-zero cost, so actual spend stays $0 - but the harness should gain an explicit free-only
   mode (cap `0`, `billing: "free"`). That file is outside this story's scope and was not changed.
2. **A real, current free-model snapshot** chosen by the operator for the primary and fallback routes (both must be
   zero-priced, tool-capable and distinct), written to `RCD_ZEROCLAW_FREE_MODELS`.
3. **A key bound to the proxy environment** (`OPENROUTER_API_KEY`), supplied by the operator; never copied into the repo.
4. Then run (single worker):

```sh
export RCD_CONFORMANCE_LIVE=1 RCD_CONFORMANCE_FACTORY=integrations.zeroclaw.conformance:create_driver \
  RCD_CONFORMANCE_AGENT=zeroclaw RCD_CONFORMANCE_MODEL=<free-a> RCD_CONFORMANCE_FALLBACK_AGENT=zeroclaw \
  RCD_CONFORMANCE_FALLBACK_MODEL=<free-b> RCD_CONFORMANCE_COST_CAP_USD=<per harness> \
  RCD_ZEROCLAW_FREE_MODELS=/var/lib/rcd/free-models.json RCD_ZEROCLAW_BIN=<path> \
  MAC_CONTROL_COLLECTOR_ENABLED=false MAC_CONTROL_DISPATCHER_ENABLED=false
python -m pytest -q tests/adapter_conformance --junitxml=zeroclaw-live.xml
```

   Expect the harness' `running_with_usage` to need the first model response within 2 s, which free models may miss.
5. Repeat on a physical Pi 4/5 for memory and timing figures (S2_benchmark).
