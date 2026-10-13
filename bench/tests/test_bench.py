"""Harness self-tests: stats, report rendering, and an end-to-end synthetic cell (no network)."""
import asyncio
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE.parent)]

from rcdbench import cell, report  # noqa: E402
from rcdbench.stats import median, p95, percentile  # noqa: E402


def test_stats():
    assert median([3, 1, 2]) == 2 and median([1, 2, 3, 4]) == 2.5 and median([]) is None
    assert percentile([1, 2, 3, 4, 5], 95) == 4.8
    assert p95([None, 7]) == 7


def test_twenty_stories_cover_every_criterion():
    kinds = set(cell.STORIES)
    assert len(cell.STORIES) == 20
    assert {"structured", "tool", "memory_write", "memory_read", "artifact", "approval",
            "timeout", "cancel", "model_pin"} <= kinds
    # a read must always follow a write
    assert cell.STORIES.index("memory_read") > cell.STORIES.index("memory_write")


def test_synthetic_cell_end_to_end(tmp_path):
    out = asyncio.run(cell.run_cell({"runtime": "fake", "factory": "fake", "agent": "fake", "model": "synthetic/primary",
                                     "fallback_model": "synthetic/fallback", "live": False, "cost_cap_usd": 0}))
    assert out["status"] == "ok" and len(out["stories"]) == 20
    failed = [s for s in out["stories"] if not s["ok"]]
    assert not failed, failed
    assert not any(s["pin_violation"] for s in out["stories"])
    by_kind = {s["kind"]: s for s in out["stories"]}
    assert abs(by_kind["timeout"]["timeout_overshoot_s"]) < 1.0
    assert by_kind["cancel"]["cancel_ack_s"] < 1.0
    run = {"run_id": "t", "target": "test-host", "hardware": out["hardware"], "cells": [out], "backend": None}
    report.write_run(tmp_path / "t", run)
    report.render(report.load_runs(tmp_path), tmp_path / "REPORT.md")
    text = (tmp_path / "REPORT.md").read_text()
    assert "Hardware target: test-host" in text and "synthetic" in text
    assert (tmp_path / "t/stories.csv").read_text().count("\n") == 21


def test_unavailable_factory_is_recorded_not_faked():
    out = asyncio.run(cell.run_cell({"runtime": "zeroclaw", "factory": "nonexistent.module:create", "agent": "zeroclaw",
                                     "model": "m", "fallback_model": "f", "live": True, "cost_cap_usd": 1}))
    assert out["status"] == "unavailable" and out["stories"] == []


def test_live_zero_cap_still_prevents_story_dispatch():
    out = asyncio.run(cell.run_cell({"runtime": "fake", "factory": "fake", "agent": "fake",
                                     "model": "synthetic/primary", "fallback_model": "synthetic/fallback",
                                     "live": True, "cost_cap_usd": 0}))
    assert len(out["stories"]) == 20
    assert all(row.get("skipped") == "cost_cap" for row in out["stories"])


def _free_cell(model):
    return {"runtime": "fake", "factory": "fake", "agent": "fake", "model": model,
            "fallback_model": "synthetic/fallback:free", "live": True, "free_only": True, "cost_cap_usd": 0}


def test_free_only_runs_all_stories_at_zero_cap():
    out = asyncio.run(cell.run_cell(_free_cell("synthetic/primary:free")))
    assert out["status"] == "ok" and len(out["stories"]) == 20
    assert not any(s.get("skipped") for s in out["stories"])
    assert out["cost_usd_total"] == 0


def test_free_only_refuses_model_not_marked_free():
    out = asyncio.run(cell.run_cell(_free_cell("vendor/paid-model")))
    assert out["status"] == "refused" and out["stories"] == []
