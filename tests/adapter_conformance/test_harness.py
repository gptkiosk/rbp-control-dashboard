"""Negative controls: prove the acceptance probes reject plausible false positives."""
from __future__ import annotations

import asyncio
from decimal import Decimal

from jsonschema import ValidationError
import pytest

from .fake_adapter import FakeDriver
from .harness import Budget, DriverConfig, Probe, Services
from . import test_conformance as cases


@pytest.fixture
def fake_probe(tmp_path):
    config = DriverConfig(tmp_path, Services(tmp_path), {"agent": "fake", "model": "synthetic/primary"},
                          {"agent": "fake", "model": "synthetic/fallback"}, Budget(Decimal("0")))
    driver = FakeDriver(config)
    with asyncio.Runner() as runner:
        probe = Probe(driver, config)
        probe.run = runner.run
        try:
            yield probe
        finally:
            runner.run(driver.close())


@pytest.mark.criterion("harness_integrity")
def test_rejects_schema_invalid_result(fake_probe, monkeypatch):
    original = fake_probe.adapter.result
    async def broken(run_id):
        result = await original(run_id)
        del result["structured_output"]
        return result
    monkeypatch.setattr(fake_probe.adapter, "result", broken)
    with pytest.raises(ValidationError, match="structured_output"):
        cases.test_structured_result_matches_contract_and_requested_schema(fake_probe)


@pytest.mark.criterion("harness_integrity")
def test_rejects_assignment_echo_as_provider_evidence(fake_probe, monkeypatch):
    original = fake_probe.driver.receipts
    def broken(run_id):
        receipts = original(run_id)
        for receipt in receipts:
            receipt["source"] = "requested_model_echo"
        return receipts
    monkeypatch.setattr(fake_probe.driver, "receipts", broken)
    with pytest.raises(AssertionError):
        cases.test_assigned_model_verified_from_provider_response_metadata(fake_probe)


@pytest.mark.criterion("harness_integrity")
def test_rejects_tool_events_without_tool_execution(fake_probe, monkeypatch):
    monkeypatch.setattr(fake_probe.config.services, "tool", lambda run, call, name, args: args["value"])
    with pytest.raises(AssertionError):
        cases.test_tool_call_round_trip_reaches_tool_and_returns_to_model(fake_probe)


@pytest.mark.criterion("harness_integrity")
def test_rejects_duplicate_artifact_side_effect(fake_probe, monkeypatch):
    original = fake_probe.config.services.tool
    def broken(run_id, call_id, name, arguments):
        result = original(run_id, call_id, name, arguments)
        if name == "artifact_write":
            original(run_id, call_id + "-duplicate", name, arguments)
        return result
    monkeypatch.setattr(fake_probe.config.services, "tool", broken)
    with pytest.raises(AssertionError):
        cases.test_same_idempotency_key_concurrent_and_completed_retry_has_no_duplicate_artifacts(fake_probe)


@pytest.mark.criterion("harness_integrity")
def test_rejects_token_usage_continuing_after_cancel(fake_probe, monkeypatch):
    original = fake_probe.driver.receipts
    def broken(run_id):
        run = fake_probe.adapter.runs.get(run_id)
        if run and run["status"] == "cancelled":
            fake_probe.driver.provider.response(run_id, "synthetic/primary")
        return original(run_id)
    monkeypatch.setattr(fake_probe.driver, "receipts", broken)
    with pytest.raises(AssertionError):
        cases.test_cancel_stops_active_run_and_provider_token_usage(fake_probe)


@pytest.mark.criterion("harness_integrity")
def test_rejects_spontaneous_native_fallback(fake_probe, monkeypatch):
    original = fake_probe.adapter._work
    async def broken(run, resumed=False):
        await original(run, resumed)
        if run["error"] and run["error"]["code"] == "PROVIDER_RATE_LIMITED":
            fake_probe.driver.provider.response(run["spec"]["run_id"], "synthetic/fallback")
    monkeypatch.setattr(fake_probe.adapter, "_work", broken)
    with pytest.raises(AssertionError):
        cases.test_fallback_requires_eligible_error_and_explicit_approved_route(
            fake_probe, "PROVIDER_RATE_LIMITED", True)


@pytest.mark.criterion("harness_integrity")
def test_rejects_checkpoint_resume_repeating_prior_work(fake_probe, monkeypatch):
    original = fake_probe.adapter.resume
    async def broken(decision):
        ack = await original(decision)
        if not ack["replayed"]:
            fake_probe.config.services.tool(decision["run_id"], "duplicate-pre-gate", "artifact_write",
                                            {"path": "before.txt", "value": "completed before approval"})
        return ack
    monkeypatch.setattr(fake_probe.adapter, "resume", broken)
    with pytest.raises(AssertionError):
        cases.test_approval_pauses_and_resumes_from_checkpoint_without_repeating_work(fake_probe)


@pytest.mark.criterion("harness_integrity")
def test_session_budget_reservations_bound_all_runs_and_replays():
    budget = Budget(Decimal("1.00"))
    allocated = [budget.allocate(f"run-{i}") for i in range(64)]
    assert sum(allocated) <= 1.00
    assert budget.allocate("run-0") == allocated[0]
    assert budget.reserved == budget.cap
    with pytest.raises(RuntimeError, match="exhausted"):
        budget.allocate("run-65")


@pytest.mark.criterion("harness_integrity")
@pytest.mark.parametrize("cap", ["0", "-1", "NaN", "Infinity", "not-a-number"])
def test_live_invalid_cap_refused_before_factory_import(monkeypatch, cap):
    from .conftest import driver_settings
    values = {"RCD_CONFORMANCE_LIVE": "1", "RCD_CONFORMANCE_FACTORY": "must_not_import:factory",
              "RCD_CONFORMANCE_AGENT": "runtime", "RCD_CONFORMANCE_MODEL": "model",
              "RCD_CONFORMANCE_FALLBACK_AGENT": "runtime", "RCD_CONFORMANCE_FALLBACK_MODEL": "fallback",
              "RCD_CONFORMANCE_COST_CAP_USD": cap}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(pytest.UsageError):
        driver_settings.__wrapped__()


@pytest.mark.criterion("harness_integrity")
def test_live_missing_settings_refused_before_factory_import(monkeypatch):
    from .conftest import driver_settings
    monkeypatch.setenv("RCD_CONFORMANCE_LIVE", "1")
    monkeypatch.setenv("RCD_CONFORMANCE_FACTORY", "must_not_import:factory")
    monkeypatch.delenv("RCD_CONFORMANCE_COST_CAP_USD", raising=False)
    with pytest.raises(pytest.UsageError, match="missing"):
        driver_settings.__wrapped__()


@pytest.mark.criterion("harness_integrity")
def test_default_mode_never_imports_live_factory(monkeypatch):
    from .conftest import driver_settings
    monkeypatch.delenv("RCD_CONFORMANCE_LIVE", raising=False)
    monkeypatch.setenv("RCD_CONFORMANCE_FACTORY", "must_not_import:factory")
    factory, live, _, _, budget = driver_settings.__wrapped__()
    assert factory is FakeDriver and not live and budget.cap == 0
