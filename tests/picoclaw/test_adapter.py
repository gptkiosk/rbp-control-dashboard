from __future__ import annotations

import asyncio
import json
from pathlib import Path

from adapter_contract import SCHEMA_VERSION, run_key, work_key
from integrations.picoclaw import PicoClawAdapter, PicoClawConfig


def spec(tmp_path: Path, *, billing="free"):
    return {"schema_version": SCHEMA_VERSION, "run_id": "pico-1", "idempotency_key": run_key("pico-1"),
            "work_key": work_key(1), "attempt": 1, "origin": {"kind": "story"}, "prompt": "do work",
            "context": {"digest": "0" * 64},
            "model_policy": {"assigned": {"agent": "picoclaw", "model": "openai/gpt-test"},
                             "approved_fallback_routes": [], "allow_runtime_fallback": False,
                             "require_model_report": True},
            "workspace": {"path": str(tmp_path), "mode": "edit", "allowed_tools": []},
            "limits": {"timeout_s": 1, "kill_grace_s": .01},
            "budget": {"billing": billing, "max_cost_usd": .01}, "session": {"mode": "new"},
            "output": {"format": "json", "json_schema": {"type": "object"}}}


def test_capabilities_are_honest_about_unavailable_provider_evidence(tmp_path):
    capabilities = PicoClawAdapter(PicoClawConfig(tmp_path / "state")).capabilities()
    assert capabilities["pins_model"] is True
    assert capabilities["disables_native_fallback"] is True
    assert capabilities["reports_model"] == "never"
    assert capabilities["reports_cost"] is False
    assert capabilities["enforces_budget"] == "none"


def test_paid_run_fails_closed_before_subprocess(tmp_path):
    async def check():
        adapter = PicoClawAdapter(PicoClawConfig(tmp_path / "state", executable="not-run"))
        await adapter.start(spec(tmp_path, billing="api"))
        result = await adapter.result("pico-1")
        assert result["status"] == "failed"
        assert result["error"]["code"] == "BUDGET_EXCEEDED"
        assert result["model"]["reported"] is None
        assert result["cost"]["usd"] is None
    asyncio.run(check())


def test_free_label_cannot_bypass_missing_provider_boundary(tmp_path, monkeypatch):
    async def check():
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")
        adapter = PicoClawAdapter(PicoClawConfig(tmp_path / "state", executable="definitely-not-picoclaw"))
        await adapter.start(spec(tmp_path))
        async for _ in adapter.events("pico-1"):
            pass
        result = await adapter.result("pico-1")
        assert result["status"] == "failed"
        assert result["error"]["code"] == "BUDGET_EXCEEDED"
        persisted = json.loads((tmp_path / "state" / "pico-1.json").read_text())
        assert "process" not in persisted
    asyncio.run(check())
