#!/usr/bin/env python3
"""One-command benchmark: N standardized stories per (runtime, model) cell on this Pi.

  bench/run.sh --live --free-only                # real runtimes, ':free' OpenRouter models only, $0 spend
  bench/run.sh --live --cost-cap-usd 2.00        # only if a paid cap is ever approved
  bench/run.sh                                   # harness self-test with the synthetic adapter, no network

Each cell runs in its own worker process (under `systemd-run --user --scope` when available, so the
cgroup's memory.peak belongs to that cell alone). See bench/README.md.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rcdbench import backend, cell as cellmod, report  # noqa: E402

FAKE = {"fake": {"factory": "fake", "agent": "fake", "models": ["synthetic/primary"],
                 "fallback_model": "synthetic/fallback"}}


def build_cells(args, config):
    runtimes = FAKE if not args.live else config["runtimes"]
    wanted = set(args.runtime or runtimes)
    unknown = wanted - set(runtimes)
    if unknown:
        raise SystemExit(f"unknown runtime(s): {', '.join(sorted(unknown))}")
    cells = []
    for name, rt in runtimes.items():
        if name not in wanted:
            continue
        for model in (args.model or rt["models"]):
            if model == rt["fallback_model"]:
                raise SystemExit(f"{name}: fallback model must differ from primary {model}")
            cells.append({"runtime": name, "factory": rt["factory"], "agent": rt["agent"], "model": model,
                          "fallback_model": rt["fallback_model"], "live": args.live, "free_only": args.free_only})
    return cells


def run_worker(cell, scope, work):
    spec, out = work / f'{cell["runtime"]}.spec.json', work / f'{cell["runtime"]}.out.json'
    spec.write_text(json.dumps(cell))
    out.unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "rcdbench.cell", str(spec), str(out)]
    if scope:
        cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "-p", "MemoryAccounting=yes",
               "-p", "CPUAccounting=yes", *cmd]
    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=cell["timeout_s"],
                          env={**os.environ, "MAC_CONTROL_COLLECTOR_ENABLED": "false",
                               "MAC_CONTROL_DISPATCHER_ENABLED": "false"})
    if out.exists():
        return json.loads(out.read_text())
    return {"runtime": cell["runtime"], "llm_model": cell["model"], "live": cell["live"], "status": "failed",
            "reason": f"worker exited {proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}", "stories": [],
            "hardware": cellmod.hardware(), "cgroup": {}}


def scope_ok():
    if not shutil.which("systemd-run"):
        return False
    probe = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"], capture_output=True)
    return probe.returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="use real runtimes from --config (spends OpenRouter credit)")
    ap.add_argument("--cost-cap-usd", type=float, help="hard total spend cap; required with --live")
    ap.add_argument("--free-only", action="store_true",
                    help="with --live: $0 paid spend; only ':free' models, billing=free, stop on any non-zero cost")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--runtime", action="append", help="limit to runtime(s)")
    ap.add_argument("--model", action="append", help="limit to LLM model(s)")
    ap.add_argument("--target", help="override hardware-target label (default: /proc/device-tree/model)")
    ap.add_argument("--results-dir", default=str(HERE / "results"))
    ap.add_argument("--no-backend", action="store_true", help="skip backend idle/loaded memory")
    ap.add_argument("--backend-python", help="python with apps/api deps (default apps/api/.venv)")
    ap.add_argument("--cell-timeout-s", type=int, default=1800)
    args = ap.parse_args()

    if args.free_only and not args.live:
        raise SystemExit("--free-only applies to --live runs")
    if args.free_only and args.cost_cap_usd:
        raise SystemExit("--free-only means $0 paid spend; do not combine it with --cost-cap-usd")
    if args.live and not args.free_only and not (args.cost_cap_usd and args.cost_cap_usd > 0
                                                 and args.cost_cap_usd == args.cost_cap_usd
                                                 and args.cost_cap_usd != float("inf")):
        raise SystemExit("--live requires --free-only or a finite positive --cost-cap-usd (the operator-approved cap)")
    config = json.loads(Path(args.config).read_text()) if args.live else {}
    cells = build_cells(args, config)
    if not cells:
        raise SystemExit("no cells selected")
    cap = (args.cost_cap_usd or 0.0) if args.live else 0.0
    scope = scope_ok()
    run_id = time.strftime("%Y%m%dT%H%M%S")
    hw = cellmod.hardware()
    target = report.target_label(hw, args.target)
    print(f"run {run_id}: target={target!r} cells={len(cells)} N={len(cellmod.STORIES)} live={args.live} "
          f"cap=${cap} cgroup-scope={scope}", flush=True)

    backend_result = None
    if not args.no_backend:
        print("measuring backend idle/loaded memory ...", flush=True)
        backend_result = backend.measure(args.backend_python)
        print(f'  backend: {backend_result["status"]} {backend_result.get("reason") or ""}', flush=True)

    spent, results = 0.0, []
    with tempfile.TemporaryDirectory(prefix="rcdbench-run-") as tmp:
        for i, c in enumerate(cells):
            remaining = cap - spent
            if args.live and not args.free_only and remaining <= 0:
                results.append({"runtime": c["runtime"], "llm_model": c["model"], "live": True, "status": "skipped",
                                "reason": "total cost cap exhausted", "stories": [], "hardware": hw, "cgroup": {}})
                continue
            c = {**c, "cost_cap_usd": min(cap / len(cells), remaining) if args.live and not args.free_only else 0.0,
                 "timeout_s": args.cell_timeout_s}
            print(f'cell {i + 1}/{len(cells)}: {c["runtime"]} / {c["model"]}', flush=True)
            result = run_worker(c, scope, Path(tmp))
            spent += result.get("cost_usd_total", 0.0) or 0.0
            results.append(result)
            print(f'  -> {result["status"]} cost=${result.get("cost_usd_total", 0.0):.4f}', flush=True)

    run = {"run_id": run_id, "target": target, "hardware": hw, "cells": results, "backend": backend_result,
           "cost_cap_usd": cap, "cost_spent_usd": spent, "stories_per_cell": len(cellmod.STORIES),
           "cgroup_scope": scope, "live": args.live, "free_only": args.free_only, "finished_at": int(time.time())}
    results_dir = Path(args.results_dir)
    report.write_run(results_dir / run_id, run)
    report.render(report.load_runs(results_dir), results_dir / "REPORT.md")
    print(f"spent ${spent:.4f} of ${cap}; results: {results_dir / run_id}; report: {results_dir / 'REPORT.md'}")
    if args.live and spent > cap:
        print("WARNING: spend exceeded cap", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
