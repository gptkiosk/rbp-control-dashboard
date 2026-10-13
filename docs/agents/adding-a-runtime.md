# Adding a runtime

This page walks through adding an agent runtime behind `rcd.adapter.v1`. It assumes you have read the
[adapter contract](adapter-contract.md) and [timeout, cancel, retry and approval](lifecycle-semantics.md).

## Before you start

- **Read the Pi eligibility rules** in [section 10 of the design](../port/adapter-contract.md#10-requirements-for-zeroclaw-and-picoclaw-s2_zeroclaw-s2_picoclaw).
  A runtime that cannot pin its model, enforce a budget or report resources is not eligible for the Pi benchmark.
- **Do not wire a new runtime into the dispatcher** until the operator has approved it. Runtime selection is a
  human gate (`S2_decide_runtime`). See [runtime evaluation](runtime-evaluation.md).
- **Keep the adapter inside the story scope.** Put the code under `integrations/<runtime>/` with a README that
  lists its gaps against the contract, as `integrations/zeroclaw/README.md` does.

## Eligibility requirements for Pi runtimes

An adapter may enter the benchmark only if it passes the conformance suite and declares:

| Requirement | Why |
| --- | --- |
| `pins_model: true`, `disables_native_fallback: true`, `reports_model != never` | Otherwise every run fails `MODEL_NOT_ENFORCEABLE` under `require_model_report`. |
| OpenRouter budget enforced by `runtime` or `adapter` | Paid routes must carry a numeric cap, and the cap must stop spending before the provider charges it. |
| `resource_measurement: cgroup` (preferred) or `psutil_tree` | Pi memory must be measured, not guessed. |
| `enforces_mode` set honestly | If the runtime cannot sandbox read versus edit, declare `false`. MCD then shows an advisory warning. |
| Workspace honoured as given | Never relocate work into the runtime's home. Refuse with `WORKSPACE_REJECTED`. |

## Worked example: a skeleton adapter

The example below is illustrative. `ExampleRuntimeAdapter` is not a real runtime in this repo. It shows the shape
an adapter needs and the points where the contract applies. The real references are
`integrations/zeroclaw/adapter.py` and `integrations/picoclaw/adapter.py`, and the synthetic reference is
`tests/adapter_conformance/fake_adapter.py`.

```python
# integrations/example/adapter.py
from __future__ import annotations

from typing import Any, AsyncIterator

from adapter_contract import (AdapterError, AgentAdapter, CancelRequest, Capabilities, Decision,
                              Event, Heartbeat, RecoveredRun, RunResult, RunSpec, SCHEMA_VERSION,
                              spec_digest)


class ExampleRuntimeAdapter(AgentAdapter):
    name = "example"

    def __init__(self, state_dir) -> None:
        self.state_dir = state_dir            # per-run state lives here, mode 0700
        self.runs: dict[str, dict[str, Any]] = {}

    # 1. Declare limits honestly. MCD trusts these before it hands over a story.
    def capabilities(self) -> Capabilities:
        return {"schema_version": SCHEMA_VERSION, "adapter": self.name, "runtime_version": None,
                "pins_model": True, "reports_model": "at_end", "disables_native_fallback": True,
                "enforces_mode": False, "structured_output": "none", "streams_events": True,
                "tool_events": False, "session": "none", "suspend_modes": [],
                "reports_cost": False, "enforces_budget": "none", "resource_measurement": "not_measured"}

    # 2. Start: check the route, replay by key, and refuse before any process runs.
    async def start(self, spec: RunSpec) -> dict[str, Any]:
        key = spec["idempotency_key"]
        digest = spec_digest(spec)
        prior = self.runs.get(key)
        if prior:
            if prior["digest"] != digest:
                raise AdapterError("IDEMPOTENCY_CONFLICT", "same key, different spec")
            return {"run_id": spec["run_id"], "status": prior["status"], "replayed": True}

        assigned = spec["model_policy"]["assigned"]
        if not self._can_pin(assigned["model"]):
            # Preflight refusals are recorded on the run, not raised.
            self.runs[key] = {"digest": digest, "status": "failed", "error": "MODEL_NOT_ENFORCEABLE"}
            return {"run_id": spec["run_id"], "status": "failed", "replayed": False}

        # Persist state before spawning, so a crash cannot lose the key.
        self.runs[key] = {"digest": digest, "status": "running", "seq": 0, "spec": spec}
        self._spawn(key, spec)                 # own process group; SIGTERM then SIGKILL on cancel
        return {"run_id": spec["run_id"], "status": "running", "replayed": False}

    # 3. Events: strictly increasing, persisted seq, so a consumer can resume after a restart.
    async def events(self, run_id: str, after_seq: int = 0) -> AsyncIterator[Event]:
        for event in self._log_for(run_id):
            if event["seq"] > after_seq:
                yield event

    # 4. Result: refuse while the run is still live. Stable once terminal.
    async def result(self, run_id: str) -> RunResult:
        run = self._find(run_id)
        if run["status"] not in ("succeeded", "failed", "timed_out", "cancelled"):
            raise AdapterError("INVALID_TRANSITION", "run is not terminal")
        return self._result_for(run)

    # 5. Cancel: idempotent by request_id. A terminal run is returned unchanged.
    async def cancel(self, request: CancelRequest) -> dict[str, Any]:
        run = self._find(request["run_id"])
        if run["status"] in ("succeeded", "failed", "timed_out", "cancelled"):
            return {"run_id": run["run_id"], "status": run["status"], "replayed": True}
        self._terminate(run, grace_s=4.0)     # SIGTERM, then SIGKILL after the grace period
        return {"run_id": run["run_id"], "status": "cancelled", "replayed": False}

    # 6. Resume: only checkpoint suspension can resume. A live prompt is refused.
    async def resume(self, decision: Decision) -> dict[str, Any]:
        raise AdapterError("RUNTIME_INCOMPATIBLE", "this runtime cannot suspend at a checkpoint")

    # 7. Heartbeat: report whether the process is alive. Read only.
    async def heartbeat(self, run_id: str) -> Heartbeat:
        run = self._find(run_id)
        return {"run_id": run_id, "alive": run.get("pid") is not None, "pid": run.get("pid"),
                "status": run["status"]}

    # 8. Recover: never relaunch. Report what is left.
    async def recover(self) -> list[RecoveredRun]:
        return [{"run_id": r["run_id"], "outcome": "interrupted"}
                for r in self.runs.values() if r["status"] == "running"]
```

The helper methods (`_can_pin`, `_spawn`, `_log_for`, `_find`, `_result_for`, `_terminate`) are left out.
Each one must follow the contract. `_terminate` must act on the process group only. `recover` must mark orphaned
runs `interrupted` and must not start them again.

## Steps

1. **Implement the Protocol** in `integrations/<runtime>/adapter.py`, using the skeleton above. The contract
   module is imported as `adapter_contract`, so run tests with `PYTHONPATH=apps/api:.`, as
   `tests/picoclaw` does.
2. **Declare capabilities honestly.** Set `reports_model`, `enforces_budget` and `resource_measurement` to what
   the runtime really does, and set `"not_reported"` or `"not_measured"` where it does not.
3. **Build a conformance driver.** The factory is named by `RCD_CONFORMANCE_FACTORY`. It receives `DriverConfig`
   and returns an object with `adapter`, `configure(run_id, scenario, failure, reported_model)` and
   `receipts(run_id)`. `integrations/zeroclaw/conformance.py` is a working example. Receipts must come from the
   provider boundary, not from the runtime's own report. See `tests/adapter_conformance/README.md`.
4. **Run the suite offline first:**

   ```sh
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/adapter_conformance
   ```

   The default factory is synthetic and needs no network.
5. **Run the suite live only with explicit operator approval.** Set the `RCD_CONFORMANCE_*` variables and use an
   approved free-only route with a cap. Do not place keys in the repo.
6. **Document the gaps** in the runtime's README, following the ZeroClaw table of gaps. Each gap needs an effect
   and a status.
7. **Wire into the dispatcher only after approval.** The dispatcher builds its adapters in
   `apps/api/dispatcher.py:88`, from `LegacyAgentAdapter`. ZeroClaw and PicoClaw are not registered there today.
   Registering an adapter changes what runs for a project, so it is a separate, reviewed change.

## Checklist

- [ ] Every operation is idempotent on its key, and a same-key, different-digest request raises `IDEMPOTENCY_CONFLICT`.
- [ ] Paid routes are refused unless a numeric cap is given, and the cap is enforced before each provider request.
- [ ] `allow_runtime_fallback` is ignored. The adapter runs only the assigned route.
- [ ] Raw stderr and secrets never appear in `Error.message`, events or result files.
- [ ] `recover()` never relaunches a run.
- [ ] Live approvals are refused with `RUNTIME_INCOMPATIBLE`, unless the runtime supports checkpoints.
- [ ] Conformance results are attached as evidence. They are proposed evidence, pending operator acceptance.
