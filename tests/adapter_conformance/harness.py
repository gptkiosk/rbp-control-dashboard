"""Test-driver seam; production adapters only implement AgentAdapter.

Drivers inject faults at the provider boundary and expose independent, redacted receipts.
They must not implement the behavior being tested on behalf of the adapter.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
import importlib.util
import math
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("adapter_contract", ROOT / "apps/api/adapter_contract.py")
# Keep the canonical module identity so live adapters raise the same AdapterError class.
# dataclasses needs registration before execution; no API settings/conftest import.
import sys
if _spec.name in sys.modules:
    ac = sys.modules[_spec.name]
else:
    ac = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = ac
    _spec.loader.exec_module(ac)

OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["ok", "value"],
    "properties": {"ok": {"const": True}, "value": {"type": "string"}},
}


def validate(kind, payload):
    Draft202012Validator(ac.schema_for(kind)).validate(payload)


@dataclass
class Budget:
    """Conservative per-run reservation. Never reuse a reservation for a new run.

    Live adapters must enforce each allocated run cap BEFORE provider requests. Allocated
    caps summed over all tests cannot exceed the operator-supplied session cap.
    """
    cap: Decimal
    reserved: Decimal = Decimal("0")
    keys: dict = field(default_factory=dict)

    def allocate(self, key):
        if key not in self.keys:
            amount = self.cap / Decimal(64)
            if self.reserved + amount > self.cap:
                raise RuntimeError("Conformance session cost reservation exhausted")
            self.keys[key] = amount
            self.reserved += amount
        amount = float(self.keys[key])
        if Decimal.from_float(amount) > self.keys[key]:
            amount = math.nextafter(amount, 0.0)
        return amount


class Services:
    """External synthetic tools and memory, with side-effect journals for assertions."""
    def __init__(self, workspace):
        self.workspace = workspace
        self.memory = {}
        self.calls = []
        self.writes = []

    def tool(self, run_id, call_id, name, arguments):
        if name == "echo":
            result = arguments["value"]
        elif name == "memory_write":
            self.memory[arguments["key"]] = arguments["value"]
            result = arguments["value"]
        elif name == "memory_read":
            result = self.memory[arguments["key"]]
        elif name == "artifact_write":
            path = self.workspace / arguments["path"]
            path.resolve().relative_to(self.workspace.resolve())
            path.write_text(arguments["value"])
            self.writes.append((run_id, arguments["path"], arguments["value"]))
            result = arguments["path"]
        else:
            raise ValueError(name)
        self.calls.append({"run_id": run_id, "call_id": call_id, "name": name,
                           "arguments": deepcopy(arguments), "result": result})
        return result


@dataclass
class DriverConfig:
    workspace: Path
    services: Services
    primary: dict
    fallback: dict
    budget: Budget
    live: bool = False


class Driver(Protocol):
    """Factory(config) -> driver. All receipts come from transport, not RunSpec echoing.

    configure: install controlled provider failure, metadata override or scenario workload.
    receipts: fresh independent provider response metadata + billed token counters by run.
    close: stop only this driver's runs/transports; mandatory even after assertion failure.
    """
    adapter: ac.AgentAdapter
    def configure(self, run_id: str, *, scenario: str = "structured",
                  failure: str | None = None, reported_model: str | None = None) -> None: ...
    def receipts(self, run_id: str) -> list[dict[str, Any]]: ...
    async def close(self) -> None: ...


class Probe:
    def __init__(self, driver, config):
        self.driver, self.config = driver, config
        self.adapter = driver.adapter
        self.counter = 0

    def spec(self, scenario="structured", *, route=None, fallbacks=None, timeout=5,
             failure=None, reported_model=None, story=None):
        self.counter += 1
        run_id = f"probe-{self.config.workspace.name}-{self.counter}"
        prompt = f"Conformance workload {scenario}. Use the supplied synthetic tools."
        value = {
            "schema_version": ac.SCHEMA_VERSION, "run_id": run_id,
            "idempotency_key": ac.run_key(run_id), "work_key": ac.work_key(story or self.counter),
            "attempt": 1, "origin": {"kind": "story", "story_key": f"probe_{self.counter}"},
            "prompt": prompt, "context": {"digest": ac.digest(prompt)},
            "model_policy": {"assigned": deepcopy(route or self.config.primary),
                             "approved_fallback_routes": deepcopy(fallbacks or []),
                             "allow_runtime_fallback": False, "require_model_report": True},
            "workspace": {"path": str(self.config.workspace), "mode": "edit",
                          "allowed_tools": ["echo", "memory_read", "memory_write", "artifact_write"]},
            "limits": {"timeout_s": timeout, "kill_grace_s": 0.05, "max_transient_retries": 0},
            "budget": {"billing": "api" if self.config.live else "free",
                       "max_cost_usd": self.config.budget.allocate(run_id), "max_output_tokens": 128},
            "session": {"mode": "new"}, "output": {"format": "json", "json_schema": OUTPUT_SCHEMA},
        }
        validate("RunSpec", value)
        self.driver.configure(run_id, scenario=scenario, failure=failure, reported_model=reported_model)
        return value

    async def finish(self, spec, *, start=True, after_seq=0):
        if start:
            await self.adapter.start(spec)
        events = []
        async def collect():
            async for event in self.adapter.events(spec["run_id"], after_seq):
                validate("Event", event)
                assert event["run_id"] == spec["run_id"]
                events.append(event)
        await asyncio.wait_for(collect(), spec["limits"]["timeout_s"] + 3)
        # At-least-once deliveries are legal; conflicting duplicate payloads aren't.
        unique = {}
        for event in events:
            assert event["seq"] > after_seq
            if event["seq"] in unique:
                assert unique[event["seq"]] == event
            unique[event["seq"]] = event
        events = list(unique.values())
        assert [e["seq"] for e in events] == list(range(after_seq + 1, after_seq + len(events) + 1))
        result = await self.adapter.result(spec["run_id"])
        validate("RunResult", result)
        assert result["run_id"] == spec["run_id"]
        assert result["idempotency_key"] == spec["idempotency_key"]
        assert result["last_seq"] == (events[-1]["seq"] if events else after_seq)
        assert result["cost"]["usd"] is not None, "Conformance requires cost evidence"
        assert result["cost"]["usd"] <= spec["budget"]["max_cost_usd"]
        receipts = self.driver.receipts(spec["run_id"])
        assert len({r["response_id"] for r in receipts}) == len(receipts), "Duplicate response accounting"
        for key in ("input_tokens", "output_tokens"):
            assert result["usage"][key] == sum(r["usage"][key] for r in receipts)
        assert all(math.isfinite(r["cost_usd"]) and r["cost_usd"] >= 0 for r in receipts)
        assert math.isclose(result["cost"]["usd"], sum(r["cost_usd"] for r in receipts),
                            rel_tol=1e-9, abs_tol=1e-12), "Provider/result cost mismatch"
        return result, events

    async def running_with_usage(self, spec):
        await self.adapter.start(spec)
        async def wait():
            while True:
                heartbeat = await self.adapter.heartbeat(spec["run_id"])
                validate("Heartbeat", heartbeat)
                receipts = self.driver.receipts(spec["run_id"])
                if heartbeat["status"] == "running" and token_count(receipts) > 0:
                    return
                assert heartbeat["status"] in {"queued", "running"}, "Workload ended before cancellation"
                await asyncio.sleep(0.01)
        await asyncio.wait_for(wait(), 2)


def token_count(receipts):
    return sum(r["usage"]["input_tokens"] + r["usage"]["output_tokens"] for r in receipts)


def assert_provider_model(probe, spec, result):
    receipts = probe.driver.receipts(spec["run_id"])
    assert receipts, "Need provider response metadata, not just requested model"
    assigned = spec["model_policy"]["assigned"]["model"]
    for receipt in receipts:
        assert receipt["source"] == "provider_response"
        assert receipt["response_id"]
        assert receipt["model"] == assigned
        assert receipt["provider"]
    assert result["model"]["reported"] == assigned
    assert result["model"]["provider"] == receipts[-1]["provider"]
    assert result["model"]["route"] == spec["model_policy"]["assigned"]
    assert result["model"]["matches_assignment"] is True
