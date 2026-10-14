"""Same probes for every runtime. pytest markers name the evaluated guarantee."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import time

from jsonschema import Draft202012Validator
import pytest

from .harness import ac, assert_provider_model, token_count, validate


@pytest.mark.criterion("structured_results")
def test_structured_result_matches_contract_and_requested_schema(probe):
    async def case():
        spec = probe.spec()
        result, events = await probe.finish(spec)
        assert result["status"] == "succeeded"
        assert result["error"] is None
        Draft202012Validator(spec["output"]["json_schema"]).validate(result["structured_output"])
        assert result["context_digest"] == spec["context"]["digest"]
        assert result == await probe.adapter.result(spec["run_id"])
        status = None
        for event in events:
            if event["type"] == "status":
                assert event["data"]["from"] == status
                new = event["data"]["to"]
                assert ac.can_transition(ac.RunStatus(status) if status else None, ac.RunStatus(new))
                status = new
        assert status == "succeeded"
    probe.run(case())


@pytest.mark.criterion("reliable_tool_use")
def test_tool_call_round_trip_reaches_tool_and_returns_to_model(probe):
    async def case():
        spec = probe.spec("tool")
        result, events = await probe.finish(spec)
        assert result["status"] == "succeeded"
        calls = [e for e in events if e["type"] == "tool_call" and e["data"]["name"] == "echo"]
        assert len(calls) == 1
        call_id = calls[0]["data"]["call_id"]
        replies = [e for e in events if e["type"] == "tool_result" and e["data"]["call_id"] == call_id]
        assert len(replies) == 1 and replies[0]["data"]["ok"] is True
        assert replies[0]["seq"] > calls[0]["seq"]
        executed = [c for c in probe.config.services.calls if c["call_id"] == call_id]
        assert len(executed) == 1 and executed[0]["result"] == spec["run_id"]
        assert result["structured_output"]["value"] == executed[0]["result"]
    probe.run(case())


@pytest.mark.criterion("assigned_model")
def test_assigned_model_verified_from_provider_response_metadata(probe):
    async def case():
        spec = probe.spec()
        result, events = await probe.finish(spec)
        assert result["status"] == "succeeded"
        assert_provider_model(probe, spec, result)
        models = [e["data"]["reported"] for e in events if e["type"] == "model"]
        assert models and set(models) == {spec["model_policy"]["assigned"]["model"]}
        receipts = probe.driver.receipts(spec["run_id"])
        for key in ("input_tokens", "output_tokens"):
            assert result["usage"][key] == sum(r["usage"][key] for r in receipts)
    probe.run(case())


@pytest.mark.criterion("assigned_model")
def test_provider_model_mismatch_fails_without_artifacts(probe):
    async def case():
        spec = probe.spec("artifact", reported_model="synthetic/unapproved-served-model")
        result, _ = await probe.finish(spec)
        assert result["status"] == "failed"
        assert result["error"]["code"] == "MODEL_MISMATCH"
        assert not result["error"]["fallback_eligible"]
        assert probe.driver.receipts(spec["run_id"])[0]["model"] == "synthetic/unapproved-served-model"
        assert not probe.config.services.writes
        assert not result["artifacts"]
    probe.run(case())


@pytest.mark.criterion("approved_fallback_routes")
@pytest.mark.parametrize("failure", ["PROVIDER_RATE_LIMITED", "PROVIDER_QUOTA_EXHAUSTED",
                                      "PROVIDER_AUTH", "PROVIDER_ERROR", "TOOL_DENIED"])
@pytest.mark.parametrize("approved", [True, False], ids=["approved", "unapproved"])
def test_fallback_requires_eligible_error_and_explicit_approved_route(probe, failure, approved):
    async def case():
        fallback = probe.config.fallback
        spec = probe.spec(failure=failure, fallbacks=[fallback] if approved else [])
        failed, events = await probe.finish(spec)
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == failure
        eligible = failure in {"PROVIDER_RATE_LIMITED", "PROVIDER_QUOTA_EXHAUSTED"}
        assert failed["error"]["fallback_eligible"] == eligible
        # Even approved fallback is informational: the adapter may never switch itself.
        assert not probe.driver.receipts(spec["run_id"])
        assert not probe.config.services.calls
        assert not [e for e in events if e["type"] in {"model", "tool_call"}]
        assert failed["model"]["route"] == probe.config.primary
        await asyncio.sleep(0.05)
        assert await probe.adapter.result(spec["run_id"]) == failed
        assert not probe.driver.receipts(spec["run_id"])
        # Synthetic dispatcher action, only on the approved/eligible intersection.
        if eligible and approved:
            retry = probe.spec(route=fallback, story=1)
            retry["attempt"] = 2
            success, _ = await probe.finish(retry)
            assert retry["work_key"] == spec["work_key"]
            assert retry["idempotency_key"] != spec["idempotency_key"]
            assert success["status"] == "succeeded"
            assert_provider_model(probe, retry, success)
    probe.run(case())


@pytest.mark.criterion("unapproved_model_refusal")
@pytest.mark.parametrize("listed_as_fallback", [False, True])
def test_unapproved_model_refused_before_inference(probe, listed_as_fallback):
    async def case():
        forbidden = {"agent": probe.config.primary["agent"], "model": "synthetic/never-approved"}
        spec = probe.spec("artifact", route=forbidden, fallbacks=[forbidden] if listed_as_fallback else [])
        result, _ = await probe.finish(spec)
        assert result["status"] == "failed"
        assert result["error"]["code"] == "MODEL_NOT_ALLOWED"
        assert not result["error"]["fallback_eligible"]
        assert token_count(probe.driver.receipts(spec["run_id"])) == 0
        assert not probe.driver.receipts(spec["run_id"])
        assert not probe.config.services.calls
        assert not result["artifacts"]
    probe.run(case())


@pytest.mark.criterion("shared_context_and_handoffs")
def test_memory_write_is_read_by_next_dependent_story(probe):
    async def case():
        first = probe.spec("memory_write", story=101)
        written, _ = await probe.finish(first)
        assert written["status"] == "succeeded"
        assert probe.config.services.memory["handoff"] == first["run_id"]
        second = probe.spec("memory_read", story=102)
        read, _ = await probe.finish(second)
        assert first["work_key"] != second["work_key"]
        assert read["status"] == "succeeded"
        assert read["structured_output"]["value"] == first["run_id"]
        assert [c["name"] for c in probe.config.services.calls] == ["memory_write", "memory_read"]
    probe.run(case())


@pytest.mark.criterion("bounded_timeout")
def test_timeout_fires_within_ten_percent_of_wall_clock_deadline(probe):
    async def case():
        spec = probe.spec("long_running", timeout=1)
        began = time.monotonic()
        result, _ = await probe.finish(spec)
        elapsed = time.monotonic() - began
        probe.measurements["timeout_elapsed_s"] = elapsed
        assert result["status"] == "timed_out"
        assert result["error"]["code"] == "TIMEOUT"
        assert 0.9 <= elapsed <= 1.1, f"Timeout took {elapsed:.4f}s for a 1s limit"
        heartbeat = await probe.adapter.heartbeat(spec["run_id"])
        assert not heartbeat["alive"]
        tokens = token_count(probe.driver.receipts(spec["run_id"]))
        await asyncio.sleep(0.15)
        assert token_count(probe.driver.receipts(spec["run_id"])) == tokens
    probe.run(case())


@pytest.mark.criterion("cancellation_without_more_tokens")
def test_cancel_stops_active_run_and_provider_token_usage(probe):
    async def case():
        spec = probe.spec("long_running")
        await probe.running_with_usage(spec)
        request = {"schema_version": ac.SCHEMA_VERSION, "run_id": spec["run_id"],
                   "request_id": f'cancel:{spec["run_id"]}', "reason": "operator", "actor": "synthetic-operator"}
        validate("CancelRequest", request)
        before_ack = time.monotonic()
        ack = await asyncio.wait_for(probe.adapter.cancel(request), 1)
        assert time.monotonic() - before_ack <= 1
        assert ack["status"] == "cancelled"
        result, _ = await probe.finish(spec, start=False)
        assert result["error"]["code"] == "CANCELLED"
        receipts = probe.driver.receipts(spec["run_id"])
        assert token_count(receipts) > 0, "Must cancel real active inference"
        writes = deepcopy(probe.config.services.writes)
        for _ in range(3):
            await asyncio.sleep(0.1)
            heartbeat = await probe.adapter.heartbeat(spec["run_id"])
            assert heartbeat["status"] == "cancelled" and not heartbeat["alive"]
            assert probe.driver.receipts(spec["run_id"]) == receipts
            assert await probe.adapter.result(spec["run_id"]) == result
            assert probe.config.services.writes == writes
        replay = await probe.adapter.cancel(request)
        assert replay["replayed"] is True and replay["status"] == "cancelled"
    probe.run(case())


@pytest.mark.criterion("idempotent_retry")
def test_same_idempotency_key_concurrent_and_completed_retry_has_no_duplicate_artifacts(probe):
    async def case():
        spec = probe.spec("artifact")
        acks = await asyncio.gather(*(probe.adapter.start(deepcopy(spec)) for _ in range(5)))
        assert sum(not ack["replayed"] for ack in acks) == 1
        assert {ack["run_id"] for ack in acks} == {spec["run_id"]}
        result, _ = await probe.finish(spec, start=False)
        assert result["status"] == "succeeded"
        assert len(result["artifacts"]) == 1
        assert len(probe.config.services.writes) == 1
        path = probe.config.workspace / result["artifacts"][0]["path"]
        assert path.read_text() == "one artifact"
        receipts = probe.driver.receipts(spec["run_id"])
        replay = await probe.adapter.start(deepcopy(spec))
        assert replay["replayed"] is True
        replayed, _ = await probe.finish(spec, start=False, after_seq=result["last_seq"])
        assert replayed == result
        assert probe.driver.receipts(spec["run_id"]) == receipts
        assert len(probe.config.services.writes) == 1
        altered = deepcopy(spec)
        altered["prompt"] += " changed work"
        with pytest.raises(ac.AdapterError) as exc:
            await probe.adapter.start(altered)
        assert exc.value.code == "IDEMPOTENCY_CONFLICT"
        assert len(probe.config.services.writes) == 1
    probe.run(case())


@pytest.mark.criterion("approval_checkpoint_resume")
def test_approval_pauses_and_resumes_from_checkpoint_without_repeating_work(probe):
    async def case():
        spec = probe.spec("approval", timeout=1)
        paused, events = await probe.finish(spec)
        assert paused["status"] == "awaiting_approval"
        approval = paused["approval"]
        assert approval["resume_mode"] == "checkpoint"
        assert approval["checkpoint"].get("state_ref") or approval["checkpoint"].get("session_id")
        assert any(e["type"] == "approval_requested" for e in events)
        assert (probe.config.workspace / "before.txt").exists()
        assert not (probe.config.workspace / "after.txt").exists()
        receipts = probe.driver.receipts(spec["run_id"])
        # Longer than the run timeout: the running clock must be paused at the gate.
        await asyncio.sleep(1.2)
        assert await probe.adapter.result(spec["run_id"]) == paused
        assert probe.driver.receipts(spec["run_id"]) == receipts
        heartbeat = await probe.adapter.heartbeat(spec["run_id"])
        assert heartbeat["status"] == "awaiting_approval" and not heartbeat["alive"]
        decision = {"schema_version": ac.SCHEMA_VERSION, "run_id": spec["run_id"],
                    "decision_id": f'decision:{spec["run_id"]}', "approval_id": approval["approval_id"],
                    "verdict": "approve", "actor": "synthetic-operator", "decided_at": int(time.time())}
        validate("Decision", decision)
        ack = await probe.adapter.resume(decision)
        assert ack["status"] == "running" and not ack["replayed"]
        replay = await probe.adapter.resume(deepcopy(decision))
        assert replay["replayed"]
        finished, continuation = await probe.finish(spec, start=False, after_seq=paused["last_seq"])
        assert finished["status"] == "succeeded"
        assert_provider_model(probe, spec, finished)
        assert all(e["segment"] > events[-1]["segment"] for e in continuation)
        assert len([e for e in continuation if e["type"] == "decision_applied"]) == 1
        assert finished["session"]["session_id"] == paused["session"]["session_id"]
        assert (probe.config.workspace / "after.txt").exists()
        assert [w[1] for w in probe.config.services.writes] == ["before.txt", "after.txt"]
        assert finished["structured_output"]["value"] == "continued from checkpoint"
        assert len(finished["artifacts"]) == 2
        conflict = {**decision, "decision_id": decision["decision_id"] + "-conflict", "verdict": "reject"}
        with pytest.raises(ac.AdapterError) as exc:
            await probe.adapter.resume(conflict)
        assert exc.value.code == "DECISION_CONFLICT"
        assert await probe.adapter.result(spec["run_id"]) == finished
        assert len(probe.config.services.writes) == 2
    probe.run(case())
