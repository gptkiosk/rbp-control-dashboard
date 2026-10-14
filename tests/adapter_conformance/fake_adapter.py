"""Synthetic AgentAdapter with a separate provider receipt ledger; no network/config access."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import time

from .harness import ac, validate


class FakeProvider:
    def __init__(self):
        self.ledger = {}

    def response(self, run_id, model):
        receipts = self.ledger.setdefault(run_id, [])
        receipt = {"source": "provider_response", "response_id": f"fake-response-{run_id}-{len(receipts)}",
                   "model": model, "provider": "synthetic", "usage": {"input_tokens": 1, "output_tokens": 1},
                   "cost_usd": 0.0}
        receipts.append(receipt)
        return deepcopy(receipt)

    def receipts(self, run_id):
        return deepcopy(self.ledger.get(run_id, []))


class FakeAdapter:
    name = "fake"

    def __init__(self, config, provider, scenarios):
        self.config, self.provider, self.scenarios = config, provider, scenarios
        self.runs, self.keys = {}, {}

    def capabilities(self):
        return {"schema_version": ac.SCHEMA_VERSION, "adapter": self.name, "runtime_version": "1",
                "pins_model": True, "reports_model": "at_end", "disables_native_fallback": True,
                "enforces_mode": True, "structured_output": "native_schema", "streams_events": True,
                "tool_events": True, "session": "preassigned", "suspend_modes": ["checkpoint"],
                "reports_cost": True, "enforces_budget": "adapter", "resource_measurement": "not_measured"}

    def _run(self, run_id):
        if run_id not in self.runs:
            raise ac.AdapterError("UNKNOWN_RUN", "Unknown synthetic run")
        return self.runs[run_id]

    def _event(self, run, kind, data):
        event = {"schema_version": ac.SCHEMA_VERSION, "run_id": run["spec"]["run_id"],
                 "seq": len(run["events"]) + 1, "segment": run["segment"], "ts": int(time.time()),
                 "type": kind, "data": deepcopy(data)}
        validate("Event", event)
        run["events"].append(event)
        run["changed"].set()

    def _status(self, run, status):
        previous = run["status"]
        assert ac.can_transition(ac.RunStatus(previous) if previous else None, ac.RunStatus(status))
        run["status"] = status
        self._event(run, "status", {"from": previous, "to": status})

    def _end(self, run, status, code=None):
        if code:
            run["error"] = ac.error(code, "Synthetic conformance outcome")
            self._event(run, "error", run["error"])
        run["ended"] = int(time.time())
        self._status(run, status)

    async def start(self, spec):
        validate("RunSpec", spec)
        key = spec["idempotency_key"]
        if key in self.keys:
            run = self.keys[key]
            if ac.spec_digest(run["spec"]) != ac.spec_digest(spec):
                raise ac.AdapterError("IDEMPOTENCY_CONFLICT", "Changed specification")
            return {"run_id": spec["run_id"], "status": run["status"], "replayed": True}
        if spec["run_id"] in self.runs:
            raise ac.AdapterError("IDEMPOTENCY_CONFLICT", "Run id already exists")
        run = {"spec": deepcopy(spec), "status": None, "events": [], "changed": asyncio.Event(),
               "segment": 1, "started": int(time.time()), "clock": time.monotonic(), "ended": None,
               "error": None, "reported": None, "artifacts": [], "output": None, "task": None,
               "decisions": {}, "approval": None}
        self.keys[key] = self.runs[spec["run_id"]] = run
        self._status(run, "queued")
        allowed = [self.config.primary, self.config.fallback]
        if spec["model_policy"]["assigned"] not in allowed:
            self._end(run, "failed", "MODEL_NOT_ALLOWED")
        else:
            self._status(run, "running")
            run["task"] = asyncio.create_task(self._work(run))
        return {"run_id": spec["run_id"], "status": run["status"], "replayed": False}

    def _inference(self, run):
        spec = run["spec"]
        scenario = self.scenarios[spec["run_id"]]
        model = scenario["reported_model"] or spec["model_policy"]["assigned"]["model"]
        receipt = self.provider.response(spec["run_id"], model)
        run["reported"] = receipt["model"]
        self._event(run, "model", {"requested": spec["model_policy"]["assigned"]["model"],
                                   "reported": receipt["model"], "provider": receipt["provider"]})
        self._event(run, "usage", {"cumulative": self._usage(run)})
        if receipt["model"] != spec["model_policy"]["assigned"]["model"]:
            self._end(run, "failed", "MODEL_MISMATCH")
            return False
        return True

    def _tool(self, run, name, arguments):
        call_id = f'{run["spec"]["run_id"]}:tool:{len(run["events"])}'
        self._event(run, "tool_call", {"call_id": call_id, "name": name})
        result = self.config.services.tool(run["spec"]["run_id"], call_id, name, arguments)
        self._event(run, "tool_result", {"call_id": call_id, "ok": True, "summary": str(result)})
        return result

    def _artifact(self, run, path, value):
        self._tool(run, "artifact_write", {"path": path, "value": value})
        artifact = {"kind": "file", "path": path, "change": "created", "sha256": ac.digest(value)}
        run["artifacts"].append(artifact)
        self._event(run, "artifact", artifact)

    async def _work(self, run, resumed=False):
        try:
            spec = run["spec"]
            scenario = self.scenarios[spec["run_id"]]
            if scenario["failure"]:
                self._end(run, "failed", scenario["failure"])
                return
            if not self._inference(run):
                return
            value = "synthetic-result"
            if scenario["scenario"] == "long_running":
                deadline = run["clock"] + spec["limits"]["timeout_s"]
                while time.monotonic() < deadline:
                    await asyncio.sleep(min(0.025, max(0, deadline - time.monotonic())))
                    if time.monotonic() < deadline:
                        self._inference(run)
                self._end(run, "timed_out", "TIMEOUT")
                return
            if scenario["scenario"] == "tool":
                value = self._tool(run, "echo", {"value": spec["run_id"]})
            elif scenario["scenario"] == "memory_write":
                value = self._tool(run, "memory_write", {"key": "handoff", "value": spec["run_id"]})
            elif scenario["scenario"] == "memory_read":
                value = self._tool(run, "memory_read", {"key": "handoff"})
            elif scenario["scenario"] == "artifact":
                self._artifact(run, "artifact.txt", "one artifact")
            elif scenario["scenario"] == "approval":
                checkpoint = self.config.workspace / f'{spec["run_id"]}.checkpoint'
                if not resumed:
                    self._artifact(run, "before.txt", "completed before approval")
                    checkpoint.write_text("after")
                    run["approval"] = {"approval_id": f'{spec["run_id"]}:gate', "kind": "human_decision",
                                       "question": "Continue synthetic work?", "resume_mode": "checkpoint",
                                       "checkpoint": {"session_id": spec["run_id"], "state_ref": str(checkpoint)},
                                       "requested_at": int(time.time())}
                    self._event(run, "approval_requested", run["approval"])
                    self._status(run, "awaiting_approval")
                    return
                assert checkpoint.read_text() == "after"
                self._artifact(run, "after.txt", "continued from checkpoint")
                value = "continued from checkpoint"
            run["output"] = {"ok": True, "value": value}
            self._end(run, "succeeded")
        except asyncio.CancelledError:
            raise

    def _usage(self, run):
        receipts = self.provider.receipts(run["spec"]["run_id"])
        return {key: sum(r["usage"][key] for r in receipts) for key in ("input_tokens", "output_tokens")}

    async def events(self, run_id, after_seq=0):
        run = self._run(run_id)
        cursor = after_seq
        while True:
            run["changed"].clear()
            for event in run["events"][cursor:]:
                cursor = event["seq"]
                yield deepcopy(event)
            if run["status"] not in {"queued", "running"}:
                return
            await run["changed"].wait()

    async def result(self, run_id):
        run = self._run(run_id)
        if run["status"] in {"queued", "running"}:
            raise ac.AdapterError("INVALID_TRANSITION", "Result not yet available")
        spec = run["spec"]
        result = {"schema_version": ac.SCHEMA_VERSION, "run_id": run_id,
                  "idempotency_key": spec["idempotency_key"], "status": run["status"],
                  "started_at": run["started"], "ended_at": run["ended"],
                  "model": {"requested": spec["model_policy"]["assigned"]["model"], "reported": run["reported"],
                            "provider": "synthetic" if run["reported"] else None,
                            "route": spec["model_policy"]["assigned"],
                            "matches_assignment": run["reported"] == spec["model_policy"]["assigned"]["model"]},
                  "session": {"session_id": run_id, "resumable": True}, "usage": self._usage(run),
                  "cost": {"usd": 0, "source": "reported", "billing": "free"},
                  "resources": {"measured_by": "not_measured"}, "artifacts": run["artifacts"],
                  "result_text": "Synthetic evidence", "structured_output": run["output"], "error": run["error"],
                  "context_digest": spec["context"]["digest"], "last_seq": len(run["events"])}
        if run["status"] == "awaiting_approval":
            result["approval"] = run["approval"]
        return deepcopy(result)

    async def cancel(self, request):
        validate("CancelRequest", request)
        run = self._run(request["run_id"])
        replayed = run["status"] in {str(s) for s in ac.TERMINAL}
        if not replayed:
            if run["task"]:
                run["task"].cancel()
                await asyncio.gather(run["task"], return_exceptions=True)
            self._end(run, "cancelled", "CANCELLED")
        return {"run_id": request["run_id"], "status": run["status"], "replayed": replayed}

    async def resume(self, decision):
        validate("Decision", decision)
        run = self._run(decision["run_id"])
        if decision["decision_id"] in run["decisions"]:
            previous, ack = run["decisions"][decision["decision_id"]]
            if previous != decision:
                raise ac.AdapterError("DECISION_CONFLICT", "Changed decision")
            return {**ack, "replayed": True}
        if run["decisions"] or not run["approval"] or decision["approval_id"] != run["approval"]["approval_id"]:
            raise ac.AdapterError("DECISION_CONFLICT", "Approval already decided or not found")
        if run["status"] != "awaiting_approval":
            raise ac.AdapterError("INVALID_TRANSITION", "Not awaiting approval")
        run["segment"] += 1
        self._event(run, "decision_applied", {k: decision[k] for k in ("decision_id", "approval_id", "verdict")})
        if decision["verdict"] == "reject":
            self._end(run, "cancelled", "DECISION_REJECTED")
        else:
            self._status(run, "running")
            run["task"] = asyncio.create_task(self._work(run, resumed=True))
        ack = {"run_id": decision["run_id"], "status": run["status"], "replayed": False}
        run["decisions"][decision["decision_id"]] = (deepcopy(decision), ack)
        return ack

    async def heartbeat(self, run_id):
        run = self._run(run_id)
        return {"schema_version": ac.SCHEMA_VERSION, "run_id": run_id, "status": run["status"],
                "alive": run["status"] == "running", "last_seq": len(run["events"]),
                "ts": int(time.time()), "resources": {"measured_by": "not_measured"}}

    async def recover(self):
        return [{"run_id": r["spec"]["run_id"], "idempotency_key": r["spec"]["idempotency_key"],
                 "outcome": "awaiting_approval" if r["status"] == "awaiting_approval" else
                            "reattached" if r["status"] == "running" else "finished_while_down",
                 "status": r["status"], "last_seq": len(r["events"])} for r in self.runs.values()]


class FakeDriver:
    def __init__(self, config):
        self.provider, self.scenarios = FakeProvider(), {}
        self.adapter = FakeAdapter(config, self.provider, self.scenarios)

    def configure(self, run_id, *, scenario="structured", failure=None, reported_model=None):
        self.scenarios[run_id] = {"scenario": scenario, "failure": failure, "reported_model": reported_model}

    def receipts(self, run_id):
        return self.provider.receipts(run_id)

    async def close(self):
        tasks = [r["task"] for r in self.adapter.runs.values() if r["task"]]
        for task in tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result
