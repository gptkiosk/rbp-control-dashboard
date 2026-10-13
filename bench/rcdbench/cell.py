"""Worker for one (runtime, llm-model) cell: runs the 20 standard stories and measures them.

Invoked by the orchestrator as `python -m rcdbench.cell SPEC.json OUT.json` so each cell has
its own process (and, under systemd-run --scope, its own cgroup for memory.peak).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]

from . import procmetrics as pm  # noqa: E402
from .stats import median  # noqa: E402

# The 20 standardized stories: (scenario, kind). Order matters: memory_read follows memory_write.
STORIES = (
    ["structured"] * 5 + ["tool"] * 4
    + ["memory_write", "memory_read", "memory_write", "memory_read"]
    + ["artifact"] * 2 + ["approval"] * 2
    + ["timeout", "cancel", "model_pin"]
)
assert len(STORIES) == 20
TIMEOUT_S = 3  # timeout story limit; the measured overshoot is latency beyond this
CANCEL_AFTER_USAGE_S = 5


def load_factory(spec_name):
    module, name = spec_name.split(":")
    return getattr(importlib.import_module(module), name)


async def run_story(probe, idx, kind, state, sampler, harness):
    ac, validate = harness.ac, harness.validate
    row = {"story": idx + 1, "kind": kind, "ok": False, "expected_structured": kind not in ("timeout", "cancel", "model_pin"),
           "structured_ok": None, "startup_s": None, "wall_s": None, "timeout_overshoot_s": None,
           "cancel_ack_s": None, "cancel_to_terminal_s": None, "cost_usd": 0.0, "input_tokens": 0,
           "output_tokens": 0, "pin_violation": False, "status": None, "error": None,
           "peak_rss_kb": None, "steady_rss_kb": None, "cpu_s": None}
    scenario = {"timeout": "long_running", "cancel": "long_running", "model_pin": "structured"}.get(kind, kind)
    for leftover in probe.config.workspace.glob("*.txt"):
        leftover.unlink()
    spec = probe.spec(scenario, timeout=TIMEOUT_S if kind == "timeout" else (30 if kind == "cancel" else 20),
                      reported_model="bench/unassigned-model" if kind == "model_pin" else None)
    run_id = spec["run_id"]
    cpu0, t0 = sum(pm.cpu_seconds()), time.monotonic()
    startup = None
    try:
        await probe.adapter.start(spec)
        t_ack = time.monotonic()
        startup = asyncio.ensure_future(_first_event_times(probe, spec, t0))
        if kind == "cancel":
            await asyncio.wait_for(_wait_usage(probe, spec, harness), CANCEL_AFTER_USAGE_S)
            request = {"schema_version": ac.SCHEMA_VERSION, "run_id": run_id, "request_id": f"cancel:{run_id}",
                       "reason": "operator", "actor": "bench"}
            validate("CancelRequest", request)
            t_cancel = time.monotonic()
            await asyncio.wait_for(probe.adapter.cancel(request), 10)
            row["cancel_ack_s"] = time.monotonic() - t_cancel
        row["startup_s"] = await startup
        result, _ = await _finish(probe, spec, harness)
        t_end = time.monotonic()
        if kind == "cancel":
            row["cancel_to_terminal_s"] = t_end - t_cancel
        row["status"] = result["status"]
        if kind == "approval" and result["status"] == "awaiting_approval":
            decision = {"schema_version": ac.SCHEMA_VERSION, "run_id": run_id, "decision_id": f"decision:{run_id}",
                        "approval_id": result["approval"]["approval_id"], "verdict": "approve",
                        "actor": "bench", "decided_at": int(time.time())}
            validate("Decision", decision)
            await probe.adapter.resume(decision)
            result, _ = await _finish(probe, spec, harness, start=False, after_seq=result["last_seq"])
            t_end = time.monotonic()
            row["status"] = result["status"]
        output = result.get("structured_output") or {}
        value = output.get("value") if isinstance(output, dict) else None
        if kind == "structured":
            row["ok"] = result["status"] == "succeeded" and output.get("ok") is True and isinstance(value, str)
        elif kind == "tool":
            row["ok"] = result["status"] == "succeeded" and value == run_id
        elif kind == "memory_write":
            row["ok"] = result["status"] == "succeeded" and value == run_id
            state["handoff"] = run_id
        elif kind == "memory_read":
            row["ok"] = result["status"] == "succeeded" and value == state.get("handoff")
        elif kind == "artifact":
            artifact = probe.config.workspace / "artifact.txt"
            row["ok"] = (result["status"] == "succeeded" and artifact.exists()
                         and artifact.read_text() == "one artifact")
        elif kind == "approval":
            row["ok"] = (result["status"] == "succeeded" and value == "continued from checkpoint"
                         and (probe.config.workspace / "after.txt").exists())
        elif kind == "timeout":
            row["ok"] = result["status"] == "timed_out"
            row["timeout_overshoot_s"] = (t_end - t_ack) - TIMEOUT_S
        elif kind == "cancel":
            row["ok"] = result["status"] == "cancelled"
        elif kind == "model_pin":
            # Correct behaviour: the adapter refuses a served model that is not the assigned one.
            row["ok"] = result["status"] != "succeeded"
            row["pin_violation"] = result["status"] == "succeeded"
        if row["expected_structured"]:
            row["structured_ok"] = row["ok"]
        if kind != "model_pin":
            if result["status"] == "succeeded" and result.get("model", {}).get("matches_assignment") is not True:
                row["pin_violation"] = True
    except Exception as exc:  # a failed story is data, not a harness crash
        row["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        if row["expected_structured"]:
            row["structured_ok"] = False
        if startup is not None and not startup.done():
            startup.cancel()
        # Best effort: never leave a runtime consuming tokens after a harness-side failure.
        try:
            await asyncio.wait_for(probe.adapter.cancel({
                "schema_version": ac.SCHEMA_VERSION, "run_id": run_id, "request_id": f"cleanup:{run_id}",
                "reason": "benchmark cleanup", "actor": "bench"}), 10)
        except Exception:
            pass
    t1 = time.monotonic()
    row["wall_s"] = t1 - t0
    row["cpu_s"] = sum(pm.cpu_seconds()) - cpu0
    receipts = probe.driver.receipts(run_id)
    assigned = spec["model_policy"]["assigned"]["model"]
    row["cost_usd"] = sum(r["cost_usd"] for r in receipts)
    row["input_tokens"] = sum(r["usage"]["input_tokens"] for r in receipts)
    row["output_tokens"] = sum(r["usage"]["output_tokens"] for r in receipts)
    if kind != "model_pin" and any(r["model"] != assigned for r in receipts):
        row["pin_violation"] = True  # independent provider evidence, not adapter claims
    row["peak_rss_kb"] = sampler.peak_kb(t0, t1)
    row["steady_rss_kb"] = sampler.steady_kb(t0, t1)
    return row


async def _wait_usage(probe, spec, harness):
    while True:
        hb = await probe.adapter.heartbeat(spec["run_id"])
        if harness.token_count(probe.driver.receipts(spec["run_id"])) > 0:
            return
        if hb["status"] not in ("queued", "running"):
            raise RuntimeError(f"run ended before any metered usage: {hb['status']}")
        await asyncio.sleep(0.01)


async def _first_event_times(probe, spec, t0):
    """Seconds from start() call to the first event whose status reached running (else first event)."""
    first_any = None
    async def scan():
        nonlocal first_any
        async for event in probe.adapter.events(spec["run_id"], 0):
            now = time.monotonic() - t0
            first_any = first_any if first_any is not None else now
            if event["type"] == "status" and event["data"].get("to") == "running":
                return now
        return first_any
    return await asyncio.wait_for(scan(), spec["limits"]["timeout_s"] + 5)


async def _finish(probe, spec, harness, **kwargs):
    return await probe.finish(spec, **kwargs)


def hardware():
    info = {"model": None, "memory_total_kb": None, "kernel": os.uname().release, "arch": os.uname().machine,
            "os": None, "cpus": os.cpu_count()}
    try:
        info["model"] = Path("/proc/device-tree/model").read_text().strip("\x00\n ")
    except OSError:
        pass
    try:
        info["memory_total_kb"] = int(next(l.split()[1] for l in Path("/proc/meminfo").read_text().splitlines()
                                           if l.startswith("MemTotal")))
    except (OSError, StopIteration):
        pass
    try:
        info["os"] = next(l.split("=", 1)[1].strip('"') for l in Path("/etc/os-release").read_text().splitlines()
                          if l.startswith("PRETTY_NAME="))
    except (OSError, StopIteration):
        pass
    return info


async def run_cell(cell):
    from tests.adapter_conformance import harness
    from tests.adapter_conformance.fake_adapter import FakeDriver

    out = {"runtime": cell["runtime"], "llm_model": cell["model"], "live": cell["live"], "status": "ok",
           "reason": None, "stories": [], "hardware": hardware(), "cgroup": {}, "started_at": int(time.time())}
    cg = pm.cgroup_dir()
    out["cgroup"]["path"] = str(cg) if cg else None
    out["cgroup"]["peak_reset"] = bool(cg and pm.reset_cgroup_peak(cg))
    cg_before = pm.cgroup_stat(cg)
    baseline_kb = (pm.rss_kb(os.getpid()) or (None,))[0]
    cap = Decimal(str(cell["cost_cap_usd"]))
    # Free-only policy: $0 paid spend. RunSpecs carry billing "free" and a $0 cap; the runtime driver must
    # refuse non-zero-priced models before any request. The bench additionally refuses models not marked
    # ':free' up front and stops the cell at the first non-zero cost receipt.
    free_only = bool(cell.get("free_only"))
    if free_only and not str(cell["model"]).endswith(":free"):
        out.update(status="refused", reason=f"free-only: {cell['model']!r} is not a ':free' model; refused before dispatch")
        return out
    with tempfile.TemporaryDirectory(prefix="rcdbench-") as tmp:
        workspace = Path(tmp)
        config = harness.DriverConfig(workspace, harness.Services(workspace),
                                      {"agent": cell["agent"], "model": cell["model"]},
                                      {"agent": cell["agent"], "model": cell["fallback_model"]},
                                      harness.Budget(cap), cell["live"] and not free_only)
        t_boot = time.monotonic()
        try:
            factory = FakeDriver if cell["factory"] == "fake" else load_factory(cell["factory"])
            driver = factory(config)
        except Exception as exc:  # runtime not installed / adapter not written yet: record, never fake
            out.update(status="unavailable", reason=f"{type(exc).__name__}: {exc}"[:400])
            return out
        out["factory_init_s"] = time.monotonic() - t_boot
        out["capabilities"] = driver.adapter.capabilities()
        sampler = pm.TreeSampler(interval=cell.get("sample_interval_s", 0.1)).start()
        probe = harness.Probe(driver, config)
        state, spent = {}, 0.0
        t_cell = time.monotonic()
        try:
            for idx, kind in enumerate(STORIES):
                # Synthetic self-tests never contact a provider and use a zero
                # budget. Keep the reservation guard for every live cell.
                if free_only and spent > 0:
                    out["stories"].append({"story": idx + 1, "kind": kind, "ok": False, "skipped": "paid_spend_detected"})
                    continue
                if cell["live"] and not free_only and spent >= float(cap) * 0.95:
                    out["stories"].append({"story": idx + 1, "kind": kind, "ok": False, "skipped": "cost_cap"})
                    continue
                row = await run_story(probe, idx, kind, state, sampler, harness)
                spent += row["cost_usd"]
                out["stories"].append(row)
        finally:
            sampler.stop()
            try:
                await asyncio.wait_for(driver.close(), 5)
            except Exception as exc:
                out["close_error"] = str(exc)[:200]
        t_end = time.monotonic()
    after = pm.cgroup_stat(cg)
    out["cell_wall_s"] = t_end - t_cell
    out["harness_baseline_rss_kb"] = baseline_kb
    out["runtime_peak_rss_kb"] = sampler.peak_kb()
    out["runtime_steady_rss_kb"] = sampler.steady_kb()
    out["cgroup"].update(memory_peak_bytes=after["memory_peak_bytes"],
                         cpu_usage_usec_delta=(after["cpu_usage_usec"] - cg_before["cpu_usage_usec"]
                                               if after["cpu_usage_usec"] is not None and cg_before["cpu_usage_usec"] is not None else None))
    out["cpu_s_self_children"] = pm.cpu_seconds()
    out["cost_usd_total"] = sum(s.get("cost_usd", 0.0) for s in out["stories"])
    return out


def main(argv):
    cell = json.loads(Path(argv[1]).read_text())
    result = asyncio.run(run_cell(cell))
    Path(argv[2]).write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
