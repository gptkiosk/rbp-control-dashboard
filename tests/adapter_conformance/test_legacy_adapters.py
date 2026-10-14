"""Mocked compatibility conformance. Exercises real wrappers/builders/parsers.

Legacy CLI capability gaps are asserted, never filled by the synthetic provider
used in the stronger fake/Pi evaluation probes. No native CLI or network runs.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import signal
import sys
from types import SimpleNamespace

import pytest

from .harness import ROOT, ac, validate

sys.path.insert(0, str(ROOT / "apps/api"))
from agents import REGISTRY
from db import make_engine, make_session_factory
from legacy_adapters import LegacyAgentAdapter, claimed_spec
from migrate import upgrade_to_head
from models import Run

pytestmark = pytest.mark.criterion("legacy_compatibility")


@pytest.fixture(params=list(REGISTRY))
def wrapped(request, tmp_path, monkeypatch):
    name = request.param
    engine = make_engine(tmp_path / "mock.db")
    upgrade_to_head(engine)
    sessions = make_session_factory(engine)
    settings = SimpleNamespace(runs_dir=tmp_path / "runs", default_budget_usd=1.0,
                               **{s.binary_setting: f"/mock/{s.id}" for s in REGISTRY.values()})
    settings.runs_dir.mkdir()
    with sessions.begin() as db:
        row = Run(agent=name, stage="running", model_requested="synthetic/model",
                  working_dir=str(tmp_path), started_at=1, command="[]", log_path="")
        db.add(row)
        db.flush()
        rid = str(row.id)
        card = SimpleNamespace(mode="read", timeout_s=1, agent_target="synthetic-target")
        spec = claimed_spec(row, card, "synthetic prompt", 1.0)
    adapter = LegacyAgentAdapter(REGISTRY[name], sessions, settings, {})
    calls = []
    processes = []
    scenario = {"mode": "success"}

    async def spawn(*argv, **kwargs):
        calls.append((argv, kwargs))
        if scenario["mode"] == "missing":
            raise FileNotFoundError("synthetic launcher missing")
        model = "different/model" if scenario["mode"] == "mismatch" else "synthetic/model"
        if name == "claude":
            lines = [dict(type="system", subtype="init", model=model, session_id="session"),
                     dict(type="result", result="OK", is_error=False, total_cost_usd=0.1,
                          usage=dict(input_tokens=12, output_tokens=3))]
        elif name == "codex":
            lines = [dict(type="thread.started", thread_id="session"),
                     dict(type="item.completed", item=dict(type="agent_message", text="OK")),
                     dict(type="turn.completed", usage=dict(input_tokens=12, output_tokens=3))]
        elif name == "hermes":
            lines = [dict(type="system", subtype="init", model=model, session_id="session"),
                     dict(type="result", text="OK", exit_code=0, tokens=dict(input=12, output=3))]
        else:
            lines = [dict(status="ok", result=dict(payloads=[dict(text="OK")],
                     meta=dict(agentMeta=dict(model=model, provider="synthetic", sessionId="session",
                                              usage=dict(input=12, output=3)))))]
        out, err = asyncio.StreamReader(), asyncio.StreamReader()
        if scenario["mode"] != "long":
            out.feed_data(("\n".join(map(json.dumps, lines))+"\n").encode())
            out.feed_eof()
            err.feed_eof()
        done = asyncio.Event()
        proc = SimpleNamespace(stdout=out, stderr=err, pid=123456789, returncode=None)
        async def wait():
            if scenario["mode"] != "long":
                proc.returncode = 0
            else:
                await done.wait()
            return proc.returncode
        proc.wait = wait
        proc.done = done
        processes.append(proc)
        return proc

    def killpg(pid, sig):
        assert pid == processes[-1].pid
        assert sig == signal.SIGTERM
        proc = processes[-1]
        proc.returncode = -int(sig)
        proc.stdout.feed_eof()
        proc.stderr.feed_eof()
        proc.done.set()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr("legacy_adapters.os.killpg", killpg)
    # The shim itself has separate regression coverage; no installed Hermes is read.
    monkeypatch.setattr("hermes_runtime.command", lambda argv: ["/mock/shim", *argv[1:]])
    yield adapter, spec, calls, scenario
    engine.dispose()


async def completed(adapter, spec):
    ack = await adapter.start(spec)
    evs = [ev async for ev in adapter.events(spec["run_id"])]
    result = await adapter.result(spec["run_id"])
    validate("RunSpec", spec)
    validate("Capabilities", adapter.capabilities())
    for ev in evs:
        validate("Event", ev)
    validate("RunResult", result)
    validate("Heartbeat", await adapter.heartbeat(spec["run_id"]))
    return ack, evs, result


def test_mocked_success_parses_real_wire_format(wrapped):
    adapter, spec, calls, _ = wrapped
    async def check():
        assert isinstance(adapter, ac.AgentAdapter)
        ack, events, result = await completed(adapter, spec)
        assert ack == dict(run_id=spec["run_id"], status="running", replayed=False)
        assert result["status"] == "succeeded"
        assert result["result_text"] == "OK"
        assert result["usage"]["input_tokens"] == 12
        assert result["usage"]["output_tokens"] == 3
        assert result["context_digest"] == ac.digest(spec["prompt"])
        assert result["model"]["reported"] == (None if adapter.name == "codex" else "synthetic/model")
        assert result["session"]["session_id"] == "session"
        assert [e["seq"] for e in events] == list(range(1, len(events)+1))
        replay = [e async for e in adapter.events(spec["run_id"], after_seq=1)]
        assert replay == events[1:]
        result["model"]["reported"] = "mutation"
        assert (await adapter.result(spec["run_id"]))["model"]["reported"] != "mutation"
        assert len(calls) == 1
        argv, kwargs = calls[0]
        assert "synthetic/model" in argv
        assert kwargs["cwd"] == spec["workspace"]["path"]
        assert kwargs["start_new_session"] is True
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        assert kwargs["limit"] == 16 * 1024 * 1024
        if adapter.name == "hermes":
            assert argv[0] == "/mock/shim"
        if adapter.name == "openclaw":
            assert "--deliver" not in argv and "synthetic-target" in argv
    asyncio.run(check())


def test_concurrent_replay_and_conflicting_start(wrapped):
    adapter, spec, calls, _ = wrapped
    async def check():
        acks = await asyncio.gather(*(adapter.start(spec) for _ in range(5)))
        assert sum(not ack["replayed"] for ack in acks) == 1
        await adapter.wait(spec["run_id"])
        assert (await adapter.start(spec))["replayed"]
        changed = copy.deepcopy(spec)
        changed["prompt"] += " changed"
        with pytest.raises(ac.AdapterError) as exc:
            await adapter.start(changed)
        assert exc.value.code == "IDEMPOTENCY_CONFLICT"
        assert len(calls) == 1
    asyncio.run(check())


def test_missing_launcher_is_terminal_not_an_automatic_fallback(wrapped):
    adapter, spec, calls, scenario = wrapped
    scenario["mode"] = "missing"
    async def check():
        _, _, result = await completed(adapter, spec)
        assert result["status"] == "failed"
        assert result["error"]["code"] == "RUNTIME_UNAVAILABLE"
        assert not result["error"]["fallback_eligible"]
        assert len(calls) == 1
    asyncio.run(check())


def test_legacy_model_mismatch_policy_is_preserved(wrapped):
    adapter, spec, _, scenario = wrapped
    scenario["mode"] = "mismatch"
    async def check():
        _, _, result = await completed(adapter, spec)
        # Existing MCD only rejects a reported mismatch for Hermes/OpenClaw.
        if adapter.name in {"hermes", "openclaw"}:
            assert result["status"] == "failed"
            assert result["error"]["code"] == "MODEL_MISMATCH"
        else:
            assert result["status"] == "succeeded"
    asyncio.run(check())


def test_timeout_uses_existing_process_group_policy(wrapped):
    adapter, spec, _, scenario = wrapped
    scenario["mode"] = "long"
    async def check():
        _, _, result = await completed(adapter, spec)
        assert result["status"] == "timed_out"
        assert result["error"]["code"] == "TIMEOUT"
        assert not (await adapter.heartbeat(spec["run_id"]))["alive"]
    asyncio.run(check())


def test_cancel_and_terminal_result_are_idempotent(wrapped):
    adapter, spec, calls, scenario = wrapped
    scenario["mode"] = "long"
    async def check():
        await adapter.start(spec)
        with pytest.raises(ac.AdapterError) as exc:
            await adapter.result(spec["run_id"])
        assert exc.value.code == "INVALID_TRANSITION"
        while not calls:
            await asyncio.sleep(0)
        request = dict(schema_version=ac.SCHEMA_VERSION, run_id=spec["run_id"],
                       request_id="cancel:1", reason="operator", actor="test")
        assert not (await adapter.cancel(request))["replayed"]
        await adapter.wait(spec["run_id"])
        result = await adapter.result(spec["run_id"])
        validate("RunResult", result)
        assert result["status"] == "cancelled"
        assert (await adapter.cancel(request))["replayed"]
        assert result == await adapter.result(spec["run_id"])
    asyncio.run(check())


def test_capability_gaps_and_unsupported_controls_are_explicit(wrapped):
    adapter, spec, _, _ = wrapped
    caps = adapter.capabilities()
    assert caps["suspend_modes"] == []
    assert caps["structured_output"] == "none"
    assert caps["resource_measurement"] == "not_measured"
    assert caps["reports_model"] == ("never" if adapter.name == "codex" else
                                     "at_end" if adapter.name == "openclaw" else "at_start")
    assert caps["enforces_mode"] == (adapter.name in {"claude", "codex"})
    async def check():
        await completed(adapter, spec)
        with pytest.raises(ac.AdapterError) as exc:
            await adapter.resume({"run_id": spec["run_id"]})
        assert exc.value.code == "INVALID_TRANSITION"
        with pytest.raises(ac.AdapterError) as exc:
            await adapter.heartbeat("unknown")
        assert exc.value.code == "UNKNOWN_RUN"
        assert await adapter.recover() == []
    asyncio.run(check())


def test_recovery_reports_existing_interruption_without_relaunch(wrapped):
    adapter, spec, calls, _ = wrapped
    with adapter.sessions.begin() as db:
        db.get(Run, int(spec["run_id"])).stage = "interrupted"
    recovered = asyncio.run(adapter.recover())
    assert len(recovered) == 1
    validate("RecoveredRun", recovered[0])
    assert recovered[0]["outcome"] == "interrupted"
    assert recovered[0]["status"] == "failed"
    assert calls == []


def test_disk_events_bound_memory_and_retention_forgets_receipts(wrapped):
    adapter, spec, _, _ = wrapped
    async def check():
        await completed(adapter, spec)
        state = adapter._state(spec["run_id"])
        assert "events" not in state
        assert state["spec"]["prompt"] == ""
        assert state["event_path"].stat().st_mode & 0o777 == 0o600
        from dispatcher import remove_run_logs
        log = adapter.runs_dir / f'run-{spec["run_id"]}.log'
        remove_run_logs([str(log)])
        assert not state["event_path"].exists()
        adapter.forget([spec["run_id"]])
        with pytest.raises(ac.AdapterError) as exc:
            await adapter.heartbeat(spec["run_id"])
        assert exc.value.code == "UNKNOWN_RUN"
    asyncio.run(check())
