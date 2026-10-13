"""Run liveness with real short-lived synthetic processes (no agents, no network)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from types import SimpleNamespace

import run_liveness


def _run(pid, started_at, log_path, stage="running", ended_at=None):
    return SimpleNamespace(pid=pid, started_at=started_at, log_path=str(log_path), stage=stage,
                           ended_at=ended_at)


def test_live_then_dead_after_the_runner_exits(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("hello")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        now = int(time.time())
        run = _run(proc.pid, now - 5, log)
        got = run_liveness.check(run, quiet_after_s=600, now=now)
        assert got.state == "live" and got.running and got.pid_alive is True
        proc.kill()
        proc.wait(timeout=10)
        got = run_liveness.check(run, quiet_after_s=600, now=now)
        assert got.state == "dead" and not got.running and got.pid_alive is False
        assert got.as_dict()["stale"] is True and got.checked_at == now
    finally:
        proc.kill()


def test_silent_runner_is_quiet_not_live(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("x")
    old = int(time.time()) - 3600
    os.utime(log, (old, old))
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        now = int(time.time())
        got = run_liveness.check(_run(proc.pid, now - 3000, log), quiet_after_s=600, now=now)
        assert got.state == "quiet" and got.running and got.as_dict()["stale"] is True
    finally:
        proc.kill()


def test_reused_pid_is_dead(tmp_path):
    # This test process is older than a run that claims to have started in the future.
    now = int(time.time())
    got = run_liveness.check(_run(os.getpid(), now + 3600, tmp_path / "none.log"), 600, now)
    assert got.state == "dead"


def test_finished_run_is_never_running(tmp_path):
    now = int(time.time())
    for stage, ended in (("done", now), ("running", now)):
        got = run_liveness.check(_run(os.getpid(), now - 5, tmp_path / "x", stage, ended), 600, now)
        assert got.state == "dead" and not got.running


def test_no_pid_is_starting_then_unknown(tmp_path):
    now = int(time.time())
    assert run_liveness.check(_run(None, now - 5, tmp_path / "x"), 600, now).state == "live"
    assert run_liveness.check(_run(None, now - 600, tmp_path / "x"), 600, now).state == "unknown"
