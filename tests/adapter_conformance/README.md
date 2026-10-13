# Adapter conformance

This suite exercises `rcd.adapter.v1` without importing API settings, the dispatcher,
collector, database, credentials or outbound integrations. The default factory is a
synthetic `AgentAdapter` and a separate fake provider transport. No network is used.
Output is proposed evidence for operator acceptance.

From the repository root, with Python 3.11+ (3.12 recommended):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r tests/adapter_conformance/requirements.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/adapter_conformance
```

`jsonschema` is required, never skipped. Async probes use the standard library
`asyncio.Runner`; pytest-asyncio is unnecessary. All runtime files are disposable pytest
workspaces. No server is started. A missing dependency is a collection failure.
Use `--junitxml=/path/to/evidence.xml` for machine-readable operator evidence.

## Mocked legacy wrappers

After provisioning the API dependencies, include the Claude/Codex/Hermes/OpenClaw
compatibility cases with:

```sh
python -m pip install -r apps/api/requirements.in -r tests/adapter_conformance/requirements.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/adapter_conformance --legacy-adapters
```

This runs the unchanged 36 fake/harness cases plus 36 mocked wrapper cases. Mocked
cases use migrated disposable SQLite databases, real CLI builders/parsers and a
synthetic subprocess boundary. They do not invoke native agents or providers.
Without `--legacy-adapters`, those application-dependent cases are not collected.

Legacy wrappers expose the same Protocol but retain existing capability gaps. They
are tested for wire schemas, parsed metadata, exact command flags and workspace,
concurrent start replay/conflicts, event replay, stable results, timeout, process-group
cancellation, existing model-mismatch policy, explicit unsupported controls,
interruption reporting and retention. They are **not** passed through the stricter
Pi eligibility fixture by inventing served models, cost enforcement, correlated tool
receipts or approval checkpoints. See `docs/port/existing-adapters.md` for boundaries.

## Evaluation criteria

Every acceptance case has a `criterion(name)` marker. Parameter expansion yields
21 adapter cases; 15 additional local harness checks verify the probes themselves.

| Named criterion | Case(s) in `test_conformance.py` |
| --- | --- |
| `structured_results` | Contract RunResult, requested output schema, context digest, terminal stability, event ordering/state transitions |
| `reliable_tool_use` | Correlated tool call/result, external execution journal, returned value used in final output |
| `assigned_model` | Assigned route compared to independent provider response metadata and usage; injected mismatched served model must fail before artifacts |
| `approved_fallback_routes` | 5 provider/policy errors × approved/unapproved route; no native switch; only synthetic dispatcher starts an approved fallback after quota/rate-limit failure |
| `unapproved_model_refusal` | Unknown model refused with zero inference/side effects, even if named in informational fallback routes |
| `shared_context_and_handoffs` | Story 101 writes external memory; dependent story 102 reads that value through tools |
| `bounded_timeout` | Never-ending workload terminates at 1 second ±10%, measured with monotonic wall clock; no later token growth |
| `cancellation_without_more_tokens` | Cancel after actual token usage; bounded acknowledgement, stopped heartbeat, stable result/provider receipts/artifacts, repeated cancel |
| `idempotent_retry` | Five concurrent starts and a completed replay share one run and one artifact write; changed spec conflicts |
| `approval_checkpoint_resume` | External pre-gate artifact, real checkpoint reference, pause longer than timeout with no usage, same-session continuation, segment increment, no repeated pre-gate write, replay/conflict decisions |
| `harness_integrity` | Deliberately broken schema, provenance, tool execution, artifact uniqueness, cancel, fallback and checkpoint behavior must be rejected; aggregate budget reservations; live configuration fails closed |

## Live driver integration (explicit opt-in)

A production adapter implements the unchanged `apps/api/adapter_contract.py` Protocol.
A separate test driver implements `Driver` in `harness.py`; see `FakeDriver` for a
working factory. This seam is necessary because the production contract does not
provide provider fault injection, tool registration or raw provider receipts.
It is test instrumentation, not a second production adapter contract.

The factory receives `DriverConfig` and returns an object with:

- `adapter`: the actual adapter under evaluation, implementing all Protocol operations.
- `configure(run_id, scenario, failure, reported_model)`: configure that run's synthetic
  workload and provider-boundary failure/metadata injection. Do not synthesize an
  adapter result, enforce its routing for it, or perform its memory/artifact operations.
- `receipts(run_id)`: a fresh, redacted list of provider responses, collected independently
  of adapter output. Each receipt includes `source='provider_response'`, nonempty
  `response_id`, `provider`, served `model`, per-response `usage.input_tokens` and
  `usage.output_tokens`, and `cost_usd`. Stream increments must be accounted once.
  Never derive the served model from the requested route or CLI flags. Unknown model,
  usage or cost does not meet these evaluation criteria.
- `async close()`: stop only that driver's runs and provider connections, even after
  assertion failure. Cleanup has a three-second bound. Do not touch another service.

Attach the supplied `Services` methods as runtime tools (or bridge equivalent runtime
calls through them); they provide external memory and side-effect journals. Tests assert
those journals, not an adapter's claims. Tool names are `echo`, `memory_write`,
`memory_read`, `artifact_write`. `configure` must present each scenario to the runtime:

| Scenario | Required workload |
| --- | --- |
| `structured` | Return `{"ok":true,"value":"<string>"}` |
| `tool` | Call echo with `value=run_id`; use its returned value in structured output |
| `memory_write` | Write memory key `handoff` with `value=run_id` |
| `memory_read` | Read `handoff`; use its returned value in structured output |
| `artifact` | Tool writes `artifact.txt` containing `one artifact`; report that file |
| `long_running` | Stream metered inference until externally timed out/cancelled; never finish voluntarily |
| `approval` | Tool writes `before.txt`, checkpoints, requests human approval; only after resume tool writes `after.txt` and returns value `continued from checkpoint` |

For injected `failure`, return the named provider/policy error before metered inference,
not a prompt asking the model to claim an error. For `reported_model`, change the
provider response metadata, preserving the requested model. The model-mismatch test
must then fail through the adapter's own policy enforcement. Allowlist exactly the
configured primary/fallback routes for the test scope; never route the unknown test
model to an upstream provider. Keep tool receipts correlated with Event call IDs.
Use only disposable workspaces and synthetic memory. Disable alerts/integrations and
set collector/dispatcher to false if the driver imports application infrastructure.

An operator who has approved live execution can supply:

```sh
export RCD_CONFORMANCE_LIVE=1
export RCD_CONFORMANCE_FACTORY='your_package.conformance:create_driver'
export RCD_CONFORMANCE_AGENT='your-runtime'
export RCD_CONFORMANCE_MODEL='operator-approved-primary-model'
export RCD_CONFORMANCE_FALLBACK_AGENT='your-runtime'
export RCD_CONFORMANCE_FALLBACK_MODEL='operator-approved-fallback-model'
export RCD_CONFORMANCE_COST_CAP_USD='0.10'
export MAC_CONTROL_COLLECTOR_ENABLED=false
export MAC_CONTROL_DISPATCHER_ENABLED=false
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/adapter_conformance
```

All six settings are mandatory. A malformed/zero/nonfinite cap fails before importing
provider code. Fake mode ignores live factory variables. Live execution disallows xdist:
the shared session budget requires a single worker. Each new run reserves 1/64 of the
whole suite cap, including fallback attempts; replayed starts reserve nothing extra.
The live adapter must enforce this `RunSpec.budget.max_cost_usd` cap at the provider
boundary **before** requests, including retries, streaming and resume. Reservation alone
cannot stop upstream billing. The factory must refuse to initialize if it cannot enforce
the cap (with conservative token-price admission or a provider hard limit).
Capabilities must report budget enforcement; reported result costs are checked against
run caps and independently collected provider costs. These checks detect a breach but are not a substitute for request admission.
No live factory or provider credentials are shipped in this story.

Fallback follows the accepted contract: adapters always keep native fallback disabled.
The tests emulate MCD authorization with a new run ID/key and stable work key. They do
not implement or certify MCD's production dispatcher policy. Same-key retry means
re-delivery of a start request, not a new attempt after terminal failure.

## Limits and follow-on work

Fake success establishes the harness baseline, not runtime/Pi interoperability. Runtime
stories must supply drivers and run the identical probes. Provider fault injection may
use a local gateway; use an unused port and never stop live MCD on 8800. Timeout accuracy
is intentionally strict: busy hosts may fail and should retain elapsed-time evidence.
Cancellation observes independent usage for 300ms after acknowledgement; deployment
checks should additionally reconcile delayed provider billing and process descendants.
Approval tests checkpoint continuity within one adapter lifetime; durable cross-process
restart recovery belongs to S3_durable_runs. Memory tools demonstrate visibility between
ordered stories; production dependency scheduling/acceptance belongs to S3_handoffs_memory.
