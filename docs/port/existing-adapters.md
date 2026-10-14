# Existing agent compatibility adapters (S2_existing_adapters)

The dispatcher now uses `AgentAdapter.start`, `events`, `result`, `cancel` and
`recover` for execution. `LegacyAgentAdapter` supplies one instance for each
existing AgentSpec (Claude, Codex, Hermes, OpenClaw). Its builders and parsers
remain unchanged, including the Hermes interpreter/shim guard. `subagents.py`
and `hermes_runtime.py` need no changes.

The dispatcher still owns claims, board ordering, dependencies, approvals,
workspace serialization, chat slots, Run/RunEvent persistence, project finish
handling and retention. No project planning code, API schemas, endpoints, model
assignments or fallback routes changed. The legacy outcome bridge retains the
original stage/error strings, parser metadata and measured duration instead of
substituting contract error wording into existing API responses.

An additional runtime supplies its AgentSpec and an AgentAdapter through the
optional `Dispatcher(..., adapters={agent_id: adapter})` injection seam. It uses
the same claim/finish workflow. The synthetic bridge test verifies that recovery
runs before start and terminal contract results map into existing Run fields.
There is no new route enabled by default and no Pi runtime implemented here.

## Execution and compatibility boundaries

- Commands built inside the original claim transaction pass unchanged to the
  legacy adapter. New contract metadata does not rebuild a claimed command.
- Process groups, closed stdin, PATH, 16 MiB reader limit, parser finishing,
  timeout, SIGTERM/5-second/SIGKILL handling, quota error wording and legacy
  Hermes/OpenClaw model-mismatch checks retain their prior behavior.
- Concurrent identical starts replay once within one adapter lifetime; changed
  specifications or start keys conflict. Starts must reference an already
  claimed running Run row with the same route and workspace.
- Numbered contract status/log events use private `run-N.adapter.jsonl` sidecars,
  avoiding an in-memory duplicate of whole logs. Contract log events truncate at
  65,536 characters; original readable/raw logs remain unchanged. Event files
  are removed by the existing run-log cleanup paths. Retention forgets adapter
  receipts when removing old Run rows.
- Result snapshots are copied for callers. Contract error messages are generic;
  existing detailed errors stay in the original logs and compatibility outcome.
- Resource usage remains not measured. Unknown model/cost/usage stays unknown.
  Codex still does not report its served model. Hermes/OpenClaw modes remain
  advisory. Only the Hermes shim is claimed to disable native fallback. Claude
  has its existing CLI budget flag, with the existing subscription exception.
- In-run approval suspension/resumption is unsupported (`suspend_modes=[]`).
  `resume` rejects with INVALID_TRANSITION. Existing operator approvals and
  continuation runs stay in MCD; no checkpoint support was invented.
- Startup/shutdown still mark running rows interrupted through Dispatcher.
  Adapter recovery reports those interrupted rows and never relaunches work.
  Durable start replay, event reattachment, sequence reconciliation and approval
  checkpoints across process restarts remain S3 work. Recovery views do not
  constitute the complete durable recovery guarantees of the target contract.

These wrappers expose the Protocol and capability-aware compatibility checks.
They do **not** meet every Pi runtime eligibility criterion. In particular, the
strict provider-provenance, budget-admission, correlated tool, shared-memory and
approval-checkpoint probes cannot certify current CLI limitations. The fake
adapter continues to run every original evaluation probe. The separate mocked
wrapper cases verify the supported compatibility surface honestly.

## Checks and proposed evidence

All checks used synthetic data and disposable databases, with `Path.home()`
redirected to a temporary directory in-process. Collector and dispatcher
background tasks were disabled. Installed dependency environments were read
from `mcd-release-candidate`, without installing or changing them; the MCP
site-packages supplied the missing jsonschema dependency for the API check.
No server, native agent, provider, alert, credential or outbound integration ran.

- Focused dispatch/chat/bridge and combined conformance: **96 passed**.
- Combined conformance comprises **36 original fake/harness cases** and **36
  mocked wrapper cases** (nine cases for each runtime). Include wrappers with
  `--legacy-adapters`; default collection preserves the fake suite's independence
  from API dependencies. See `tests/adapter_conformance/README.md`.
- Final full API plus combined conformance: **443 passed, 1 skipped** (the Linux-only
  collector case on macOS). See the sibling verification receipt
  `verification/S2_existing_adapters-python.xml`. The ambient host process census
  was mocked to an empty iterator for this run because this sandbox denies
  psutil's macOS process enumeration. Individual process unit tests retain their
  own fixtures. This is an environmental workaround, not a collector fix.
- The earlier unmodified host-census run: **432 passed, 1 skipped, 1 failed**.
  Failure: `test_collector.py::test_record_merges_macmon_and_extras`, with
  `PermissionError` from psutil/sysctl. This predates the final nine added cases.
- MCP: **13 passed**. Frontend type check: **passed**.
- Frontend tests: **186 passed, 1 failed; 37 files passed, 2 files failed**.
  Existing Pi UI failures: `PiView.spec.ts` cannot import uPlot because matchMedia
  is absent; `router.spec.ts` expects `router.resolve('/mac#ts-title').name` to
  equal `pi`, but gets undefined. No frontend file was changed in this story.

The all-existing-tests acceptance criterion remains unproven without an
unrestricted host-census run and resolution of the prior Pi UI test failures.
This handoff is proposed evidence, subject to operator acceptance.

## Next-story guidance

Implement ZeroClaw/PicoClaw behind the injection seam and supply provider-boundary
conformance drivers. Do not claim Pi eligibility from these mocked compatibility
results. S3 should add durable adapter state and approval/cancel semantics while
retaining MCD ownership of route changes, acceptance and dependency scheduling.
Resolve the prior UI failures in their own story, and rerun the collector test
where host process enumeration is permitted. No commit, push, merge, publication,
preview, LaunchAgent or live-MCD service action was performed.
