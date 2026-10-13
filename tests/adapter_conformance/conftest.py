from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
import importlib
import os

import pytest

from .fake_adapter import FakeDriver
from .harness import Budget, DriverConfig, Probe, Services, ac, validate


def pytest_addoption(parser):
    parser.addoption("--legacy-adapters", action="store_true", default=False,
                     help="Include mocked legacy wrappers (requires API test dependencies)")


def pytest_ignore_collect(collection_path, config):
    # Preserve the standalone fake suite's independence from application dependencies.
    if collection_path.name == "test_legacy_adapters.py":
        return not config.getoption("--legacy-adapters")
    return None


def pytest_configure(config):
    config.addinivalue_line("markers", "criterion(name): named adapter evaluation criterion")
    if os.getenv("RCD_CONFORMANCE_LIVE", "0") not in {"0", "1"}:
        raise pytest.UsageError("RCD_CONFORMANCE_LIVE must be 0 or 1")
    if os.getenv("RCD_CONFORMANCE_LIVE") == "1" and getattr(config.option, "numprocesses", 0):
        raise pytest.UsageError("Live conformance requires one worker for a shared session cost cap")


@pytest.fixture(scope="session")
def driver_settings():
    live = os.getenv("RCD_CONFORMANCE_LIVE") == "1"
    if not live:
        return FakeDriver, False, {"agent": "fake", "model": "synthetic/primary"}, {
            "agent": "fake", "model": "synthetic/fallback"}, Budget(Decimal("0"))
    required = ["RCD_CONFORMANCE_FACTORY", "RCD_CONFORMANCE_AGENT", "RCD_CONFORMANCE_MODEL",
                "RCD_CONFORMANCE_FALLBACK_AGENT", "RCD_CONFORMANCE_FALLBACK_MODEL",
                "RCD_CONFORMANCE_COST_CAP_USD"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise pytest.UsageError(f"Live conformance missing: {', '.join(missing)}")
    try:
        cap = Decimal(os.environ["RCD_CONFORMANCE_COST_CAP_USD"])
        if not cap.is_finite() or cap <= 0:
            raise ValueError("Cost cap must be finite and positive")
        module, name = os.environ["RCD_CONFORMANCE_FACTORY"].split(":")
    except (InvalidOperation, ValueError) as exc:
        raise pytest.UsageError(str(exc)) from exc
    # Import provider code only after explicit opt-in and complete cap/model configuration.
    factory = getattr(importlib.import_module(module), name)
    primary = {"agent": os.environ["RCD_CONFORMANCE_AGENT"], "model": os.environ["RCD_CONFORMANCE_MODEL"]}
    fallback = {"agent": os.environ["RCD_CONFORMANCE_FALLBACK_AGENT"],
                "model": os.environ["RCD_CONFORMANCE_FALLBACK_MODEL"]}
    if primary == fallback:
        raise pytest.UsageError("Fallback must be distinct from the primary route")
    return factory, True, primary, fallback, Budget(cap)


@pytest.fixture
def probe(tmp_path, driver_settings, request):
    factory, live, primary, fallback, budget = driver_settings
    config = DriverConfig(tmp_path, Services(tmp_path), primary, fallback, budget, live)
    with asyncio.Runner() as runner:
        driver = factory(config)
        try:
            assert isinstance(driver.adapter, ac.AgentAdapter)
            capabilities = driver.adapter.capabilities()
            validate("Capabilities", capabilities)
            assert capabilities["pins_model"]
            assert capabilities["reports_model"] != "never"
            assert capabilities["disables_native_fallback"]
            assert capabilities["enforces_budget"] in {"runtime", "adapter"}
            assert capabilities["reports_cost"]
            value = Probe(driver, config)
            value.run = runner.run
            value.measurements = {}
            try:
                yield value
            finally:
                request.node.user_properties.extend(value.measurements.items())
        finally:
            runner.run(asyncio.wait_for(driver.close(), 3))


@pytest.fixture(autouse=True)
def criterion_evidence(request):
    criterion = request.node.get_closest_marker("criterion")
    assert criterion is not None, "Every conformance case needs a named evaluation criterion"
    request.node.user_properties.append(("evaluation_criterion", criterion.args[0]))
