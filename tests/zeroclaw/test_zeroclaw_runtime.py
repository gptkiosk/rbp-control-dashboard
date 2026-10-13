"""The adapter driving the real ``zeroclaw`` binary against a loopback OpenRouter stand-in.

Skipped without a binary. These prove the adapter/runtime/proxy plumbing on this host; they are not
live-provider conformance and say nothing about free-model quality.
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest

from adapter_contract import SCHEMA_VERSION
from zc_support import FREE, make_spec, tool_message

pytestmark = pytest.mark.usefixtures("need_runtime")


def decision(spec, approval, verdict="approve", decision_id="d1"):
    return {"schema_version": SCHEMA_VERSION, "run_id": spec["run_id"], "decision_id": decision_id,
            "approval_id": approval["approval_id"], "verdict": verdict, "actor": "test", "decided_at": int(time.time())}


async def drain(adapter, spec, after=0):
    return [e async for e in adapter.events(spec["run_id"], after)]


def test_structured_success_with_independent_usage_model_and_cost(make_adapter, workspace, proxy, upstream, tmp_path):
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace)
        await adapter.start(spec)
        events = await drain(adapter, spec)
        return adapter, spec, events, await adapter.result(spec["run_id"])
    adapter, spec, events, result = asyncio.run(go())
    assert result["status"] == "succeeded" and result["structured_output"] == {"ok": True, "value": "x"}
    assert result["model"] == {"requested": FREE, "reported": FREE, "provider": "StubProvider",
                               "route": spec["model_policy"]["assigned"], "matches_assignment": True}
    receipts = proxy.receipts("zc-1")
    assert result["usage"]["input_tokens"] == sum(r["usage"]["input_tokens"] for r in receipts)
    assert result["cost"] == {"usd": 0.0, "source": "reported", "billing": "free", "limit_usd": 0.01}
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert {"status", "model", "usage"} <= {e["type"] for e in events}
    assert result["resources"]["measured_by"] in {"psutil_tree", "not_measured"}
    # Only the proxy token is ever on disk, and the per-run directory is removed afterwards.
    assert not (tmp_path / "state" / "zc-1.d").exists()
    assert "test-key-not-a-secret" not in (tmp_path / "state" / "zc-1.json").read_text()
    assert upstream.requests[0]["model"] == FREE


def test_runtime_never_receives_native_fallback_or_second_model(make_adapter, workspace, upstream):
    spec = make_spec(workspace, fallbacks=[{"agent": "zeroclaw", "model": "vendor/other:free"}])
    async def go():
        adapter = make_adapter()
        await adapter.start(spec)
        await drain(adapter, spec)
    asyncio.run(go())
    assert {r["model"] for r in upstream.requests} == {FREE}


def test_allowed_tool_runs_without_prompt_and_is_reported_as_events(make_adapter, workspace, upstream):
    upstream.script = [tool_message("file_write", path="out.txt", content="one artifact")]
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace, tools=["Write"])
        await adapter.start(spec)
        return await drain(adapter, spec), await adapter.result(spec["run_id"])
    events, result = asyncio.run(go())
    assert result["status"] == "succeeded" and (workspace / "out.txt").read_text() == "one artifact"
    call, = [e for e in events if e["type"] == "tool_call"]
    outcome, = [e for e in events if e["type"] == "tool_result"]
    assert call["data"]["name"] == "file_write" and outcome["data"] == {"call_id": call["data"]["call_id"], "ok": True,
                                                                        "summary": "file_write ok"}
    assert "one artifact" not in str(events)  # arguments are summarised by key, never copied
    assert result["usage"]["tool_calls"] == 1 and result["usage"]["requests"] == 2


def test_ungranted_tool_pauses_for_approval_and_resumes_the_same_run_once(make_adapter, workspace, upstream):
    upstream.script = [tool_message("file_write", path="after.txt", content="continued")]
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace, timeout=3)
        await adapter.start(spec)
        first = await drain(adapter, spec)
        paused = await adapter.result(spec["run_id"])
        approval = paused["approval"]
        await asyncio.sleep(1.2)  # a pause longer than the run could be idle must not consume its timeout
        ack = await adapter.resume(decision(spec, approval))
        replay = await adapter.resume(decision(spec, approval))
        conflict = None
        try:
            await adapter.resume(decision(spec, approval, "reject", "d2"))
        except Exception as exc:
            conflict = exc.code
        second = await drain(adapter, spec, first[-1]["seq"])
        return first, paused, ack, replay, conflict, second, await adapter.result(spec["run_id"])
    first, paused, ack, replay, conflict, second, result = asyncio.run(go())
    assert paused["status"] == "awaiting_approval" and paused["approval"]["resume_mode"] == "live"
    assert not (workspace / "after.txt").exists() or result["status"] == "succeeded"
    assert ack["replayed"] is False and replay["replayed"] is True and conflict == "DECISION_CONFLICT"
    assert result["status"] == "succeeded" and (workspace / "after.txt").read_text() == "continued"
    applied = next(i for i, e in enumerate(second) if e["type"] == "decision_applied")
    assert {e["segment"] for e in second[applied:]} == {2} and first[-1]["seq"] + 1 == second[0]["seq"]
    assert all(e["segment"] == 1 for e in second[:applied])  # late trace events of the paused segment
    assert sum(e["type"] == "approval_requested" for e in first + second) == 1


def test_rejected_approval_cancels_and_the_tool_never_runs(make_adapter, workspace, upstream):
    upstream.script = [tool_message("file_write", path="no.txt", content="nope")]
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace)
        await adapter.start(spec)
        await drain(adapter, spec)
        approval = (await adapter.result(spec["run_id"]))["approval"]
        await adapter.resume(decision(spec, approval, "reject"))
        return await adapter.result(spec["run_id"])
    result = asyncio.run(go())
    assert (result["status"], result["error"]["code"]) == ("cancelled", "DECISION_REJECTED")
    assert not (workspace / "no.txt").exists()


def test_unanswered_approval_times_out_without_running_the_tool(make_adapter, workspace, upstream):
    upstream.script = [tool_message("file_write", path="late.txt", content="late")]
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace, approval_timeout_s=1)
        await adapter.start(spec)
        await drain(adapter, spec)
        for _ in range(60):
            if (await adapter.result(spec["run_id"]))["status"] != "awaiting_approval":
                break
            await asyncio.sleep(0.1)
        return await adapter.result(spec["run_id"])
    result = asyncio.run(go())
    assert (result["status"], result["error"]["code"]) == ("timed_out", "APPROVAL_TIMEOUT")
    assert not (workspace / "late.txt").exists()


def test_timeout_kills_the_process_group_on_time_and_stops_inference(make_adapter, workspace, upstream, proxy):
    upstream.delay = 30
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace, timeout=1)
        started = time.monotonic()
        await adapter.start(spec)
        await drain(adapter, spec)
        elapsed = time.monotonic() - started
        pid = (await adapter.heartbeat(spec["run_id"]))["pid"]
        return elapsed, pid, await adapter.result(spec["run_id"])
    elapsed, pid, result = asyncio.run(go())
    assert (result["status"], result["error"]["code"]) == ("timed_out", "TIMEOUT")
    assert 1.0 <= elapsed < 2.2, elapsed
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert len(upstream.requests) == 1


def test_cancel_is_idempotent_stops_tokens_and_leaves_no_process(make_adapter, workspace, upstream, proxy):
    upstream.delay = 30
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace)
        await adapter.start(spec)
        for _ in range(100):
            if upstream.requests:
                break
            await asyncio.sleep(0.05)
        pid = (await adapter.heartbeat(spec["run_id"]))["pid"]
        request = {"schema_version": SCHEMA_VERSION, "run_id": spec["run_id"], "request_id": "c1", "reason": "operator",
                   "actor": "test"}
        first = await adapter.cancel(request)
        again = await adapter.cancel(request)
        return pid, first, again, await adapter.result(spec["run_id"]), await adapter.heartbeat(spec["run_id"])
    pid, first, again, result, beat = asyncio.run(go())
    assert first["replayed"] is False and again["replayed"] is True
    assert (result["status"], result["error"]["code"]) == ("cancelled", "CANCELLED") and beat["alive"] is False
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert proxy.flags("zc-1") == set() and len(upstream.requests) == 1


def test_wrong_served_model_fails_before_any_artifact(make_adapter, workspace, upstream):
    upstream.served_model = "someone/else"
    upstream.script = [tool_message("file_write", path="bad.txt", content="bad")]
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace, tools=["Write"])
        await adapter.start(spec)
        await drain(adapter, spec)
        return await adapter.result(spec["run_id"])
    result = asyncio.run(go())
    assert (result["status"], result["error"]["code"]) == ("failed", "MODEL_MISMATCH")
    assert result["model"]["reported"] == "someone/else" and result["model"]["matches_assignment"] is False
    assert not (workspace / "bad.txt").exists()


@pytest.mark.parametrize("status,code", [(429, "PROVIDER_RATE_LIMITED"), (402, "PROVIDER_QUOTA_EXHAUSTED"),
                                         (401, "PROVIDER_AUTH"), (503, "PROVIDER_ERROR")])
def test_provider_errors_map_to_contract_codes_without_switching_models(make_adapter, workspace, upstream, proxy,
                                                                          status, code):
    upstream.status = status
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace)
        await adapter.start(spec)
        await drain(adapter, spec)
        return await adapter.result(spec["run_id"])
    result = asyncio.run(go())
    assert result["status"] == "failed" and result["error"]["code"] == code
    assert {r["model"] for r in upstream.requests} == {FREE}


def test_concurrent_identical_starts_share_one_run_and_one_inference(make_adapter, workspace, upstream):
    async def go():
        adapter, spec = make_adapter(), make_spec(workspace)
        acks = await asyncio.gather(*(adapter.start(spec) for _ in range(5)))
        await drain(adapter, spec)
        changed = dict(spec, prompt="different")
        conflict = None
        try:
            await adapter.start(changed)
        except Exception as exc:
            conflict = exc.code
        return acks, conflict
    acks, conflict = asyncio.run(go())
    assert sorted(a["replayed"] for a in acks) == [False, True, True, True, True]
    assert conflict == "IDEMPOTENCY_CONFLICT" and len(upstream.requests) == 1


def test_restart_recovery_kills_orphan_marks_interrupted_and_never_relaunches(make_adapter, workspace, upstream, tmp_path):
    upstream.delay = 30
    async def go():
        first, spec = make_adapter(), make_spec(workspace)
        await first.start(spec)
        for _ in range(100):
            if upstream.requests:
                break
            await asyncio.sleep(0.05)
        pid = (await first.heartbeat(spec["run_id"]))["pid"]
        # Simulated host restart: drop the supervising task and build a fresh adapter on the same state dir.
        first._runs["zc-1"]["task"].cancel()
        second = make_adapter()
        recovered = await second.recover()
        replay = await second.start(spec)
        return pid, recovered, replay, await second.result(spec["run_id"])
    pid, recovered, replay, result = asyncio.run(go())
    assert recovered == [{"run_id": "zc-1", "idempotency_key": "mcd:run:zc-1", "outcome": "interrupted",
                          "status": "failed", "last_seq": result["last_seq"]}]
    assert (result["status"], result["error"]["code"]) == ("failed", "INTERRUPTED")
    assert replay["replayed"] is True and len(upstream.requests) == 1
    time.sleep(0.2)
    # The first adapter's event loop is gone, so nobody reaps the child: a zombie counts as dead.
    try:
        state = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        state = "gone"
    assert state in {"Z", "gone"}
    assert not (tmp_path / "state" / "zc-1.d").exists()
