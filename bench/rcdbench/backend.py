"""Measure the RCD backend's own idle and loaded memory on a private loopback port.

Safety: never uses port 8800, a fresh temporary data dir, collector/dispatcher disabled, no
alerts or integrations. Only the PID this module spawned is ever signalled.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from . import procmetrics as pm
from .stats import median

ROOT = Path(__file__).resolve().parents[2]
LOAD_PATHS = ("/healthz", "/api/metrics/current", "/api/projects", "/")


def free_port():
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port != 8800:
            return port


def _tree_rss(pid):
    return pm.tree_rss_kb([pid, *pm.descendants(pid)])[0]


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code  # 401 still exercises the request path
    except OSError:
        return None


def measure(python=None, idle_s=10, load_s=15, workers=8):
    api = ROOT / "apps/api"
    python = python or (str(api / ".venv/bin/python") if (api / ".venv/bin/python").exists() else "python3")
    port = free_port()
    out = {"port": port, "python": python, "status": "ok", "reason": None}
    if not pm.have_proc():
        return {**out, "status": "unavailable", "reason": "no /proc on this host"}
    with tempfile.TemporaryDirectory(prefix="rcdbench-api-") as data:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("MAC_CONTROL_", "OPENROUTER", "ANTHROPIC", "OPENAI"))}
        env.update(MAC_CONTROL_HOST="127.0.0.1", MAC_CONTROL_PORT=str(port), MAC_CONTROL_DATA_DIR=data,
                   MAC_CONTROL_COLLECTOR_ENABLED="false", MAC_CONTROL_DISPATCHER_ENABLED="false")
        log = open(Path(data) / "api.log", "w")
        proc = subprocess.Popen([python, "serve.py"], cwd=api, env=env, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            t0 = time.monotonic()
            while time.monotonic() - t0 < 60:
                if proc.poll() is not None:
                    break
                if _get(f"http://127.0.0.1:{port}/healthz") == 200:
                    out["startup_s"] = time.monotonic() - t0
                    break
                time.sleep(0.2)
            else:
                out.update(status="failed", reason="healthz not ready in 60s")
            if proc.poll() is not None or out["status"] != "ok" or "startup_s" not in out:
                log.flush()
                tail = (Path(data) / "api.log").read_text()[-400:]
                return {**out, "status": "failed", "reason": out.get("reason") or f"backend exited: {tail}"}
            time.sleep(2)  # let import-time allocations settle before 'idle'
            idle = []
            for _ in range(int(idle_s * 2)):
                idle.append(_tree_rss(proc.pid))
                time.sleep(0.5)
            out["idle_rss_kb_median"], out["idle_rss_kb_max"] = median(idle), max(idle)
            stop, counts, loaded = threading.Event(), [0], []

            def hammer():
                i = 0
                while not stop.is_set():
                    if _get(f"http://127.0.0.1:{port}{LOAD_PATHS[i % len(LOAD_PATHS)]}") is not None:
                        counts[0] += 1
                    i += 1

            threads = [threading.Thread(target=hammer, daemon=True) for _ in range(workers)]
            for t in threads:
                t.start()
            t_load = time.monotonic()
            while time.monotonic() - t_load < load_s:
                loaded.append(_tree_rss(proc.pid))
                time.sleep(0.25)
            stop.set()
            for t in threads:
                t.join(6)
            out.update(loaded_rss_kb_median=median(loaded), loaded_rss_kb_peak=max(loaded),
                       load_workers=workers, load_requests=counts[0], load_seconds=load_s)
            hwm = pm.rss_kb(proc.pid)
            out["vm_hwm_kb"] = hwm[1] if hwm else None
            return out
        finally:
            # Only the PID we spawned (own session/process group).
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
            log.close()
