"""Truthful liveness for runs the database still lists as running.

`Run.stage == "running"` is what the dispatcher last wrote. If the runner was killed, the
dispatcher stopped or the host rebooted, that row can stay "running" until recovery runs.
Status views must not show it as running. This module checks the runner process and its log
and returns one of:

  live     the runner process exists and wrote output recently
  quiet    the runner process exists but has written nothing for `quiet_after_s`
  dead     a pid was recorded and no matching process exists (exited, killed, pid reused)
  unknown  no pid is recorded (a claim not yet started, or a legacy row) and it is not new

Read-only: it never changes a run. Recovery stays with the dispatcher. Every result carries
the time it was checked so a client can show how fresh it is.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import psutil

START_GRACE_S = 30  # a claimed run may not have recorded its pid yet


@dataclass(frozen=True)
class Liveness:
    state: str  # live | quiet | dead | unknown
    checked_at: int
    pid_alive: bool | None
    last_activity_at: int | None
    reason: str

    @property
    def running(self) -> bool:
        return self.state in ("live", "quiet")

    def as_dict(self) -> dict:
        return {"state": self.state, "stale": self.state != "live", "checked_at": self.checked_at,
                "pid_alive": self.pid_alive, "last_activity_at": self.last_activity_at,
                "reason": self.reason}


def _pid_alive(pid: int, started_at: int) -> bool:
    try:
        proc = psutil.Process(pid)
        # A process older than the run is a reused pid, not this runner.
        if proc.create_time() < (started_at or 0) - 2:
            return False
        return proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True  # cannot be inspected: do not claim it died


def _last_activity(run, now: int) -> int | None:
    try:
        mtime = int(os.stat(run.log_path).st_mtime)
    except (OSError, TypeError, ValueError):
        return None
    return min(mtime, now)


def check(run, quiet_after_s: int, now: int | None = None) -> Liveness:
    now = int(time.time()) if now is None else now
    last = _last_activity(run, now)
    if run.ended_at is not None or run.stage != "running":
        return Liveness("dead", now, None, last, f"run is {run.stage}, not running")
    if run.pid is None:
        if now - run.started_at <= START_GRACE_S:
            return Liveness("live", now, None, last, "starting")
        return Liveness("unknown", now, None, last, "no runner process recorded")
    if not _pid_alive(run.pid, run.started_at):
        return Liveness("dead", now, False, last, "runner process is gone")
    idle_since = last if last is not None else run.started_at
    if now - idle_since > quiet_after_s:
        return Liveness("quiet", now, True, last, f"no output for {now - idle_since}s")
    return Liveness("live", now, True, last, "runner alive")
