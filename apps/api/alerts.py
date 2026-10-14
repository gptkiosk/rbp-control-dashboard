"""Durable failure alerts through the existing Hermes send CLI; never an LLM turn."""
from __future__ import annotations
import asyncio
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time
import threading
import tomllib
import uuid
from collections import defaultdict
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, exists, func, update, text
from models import AlertEvent, AlertState, Run, ServiceSnapshot
from settings import tool_search_dirs

class RunRules(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)
    enabled: bool = True
    stages: list[str] = Field(default_factory=lambda: ["failed", "timeout", "interrupted"], min_length=1, max_length=3)
    @model_validator(mode="after")
    def valid(self):
        if not set(self.stages) <= {"failed", "timeout", "interrupted"}:
            raise ValueError("Unsupported failure stage")
        return self

class ServiceRules(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)
    enabled: bool = True
    window_seconds: int = Field(default=600, ge=120, le=86400)
    excess_runs: int = Field(default=5, ge=2, le=1000)
    calendar_allowance: int = Field(default=20, ge=2, le=2000)
    sample_max_age_seconds: int = Field(default=180, ge=60, le=600)
    recovery_samples: int = Field(default=2, ge=2, le=10)

class AlertRules(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)
    enabled: bool = False
    delivery_enabled: bool = False
    destination: str = ""
    poll_seconds: int = Field(default=30, ge=10, le=300)
    max_deliveries_per_tick: int = Field(default=3, ge=1, le=10)
    pending_max_age_seconds: int = Field(default=3600, ge=60, le=86400)
    runs: RunRules = Field(default_factory=RunRules)
    services: ServiceRules = Field(default_factory=ServiceRules)
    @model_validator(mode="after")
    def valid(self):
        if self.destination and not re.fullmatch(r"discord:[0-9]{16,22}", self.destination):
            raise ValueError("Use an explicit Discord channel ID")
        if self.delivery_enabled and (not self.enabled or not self.destination):
            raise ValueError("Delivery requires monitoring and an explicit destination")
        return self


def load_rules(path: Path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return AlertRules(), None
    except OSError:
        return AlertRules(), "Alert rules are unavailable; delivery is paused."
    try:
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError()
            raw = source.read(16385)
            if len(raw) > 16384:
                raise ValueError()
        return AlertRules.model_validate(tomllib.loads(raw.decode("utf-8"))), None
    except (ValueError, OSError):
        return AlertRules(), "Alert rules are invalid; delivery is paused."


def identifier(value):
    # No mentions, links, directives, MEDIA paths or prompt/log content reach the sender.
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value))[:100]


def run_message(run, test=False):
    prefix = "[MCD TEST]" if test else "[MCD]"
    return (f"{prefix} Run failed\nRun: #{run.id} · Agent: {identifier(run.agent)}\n"
            f"State: {identifier(run.stage)} · Exit: {run.exit_code if run.exit_code is not None else 'not reported'}\n"
            + ("Temporary verification run; no production task or service was changed." if test else "Open MCD to inspect the run."))


class HermesSender:
    def __init__(self, binary):
        self.binary = binary
    def __call__(self, destination, message):
        # Credentials stay in Hermes's own private configuration. Message text travels on stdin.
        env = {"HOME": str(Path.home()), "PATH": os.pathsep.join((*tool_search_dirs(), "/usr/bin", "/bin")), "LANG": "en_US.UTF-8"}
        proc = None
        try:
            proc = subprocess.Popen([self.binary, "send", "--to", destination, "--file", "-", "--json"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=env, start_new_session=True)
            stdout, _ = proc.communicate(message, timeout=30)
            if proc.returncode != 0 or len(stdout) > 32768:
                return None
            payload = json.loads(stdout)
            if (payload.get("success") is True and payload.get("platform") == "discord"
                    and str(payload.get("chat_id")) == destination.split(":")[1]
                    and re.fullmatch(r"[0-9]{16,22}", str(payload.get("message_id", "")))):
                return str(payload["message_id"])
        except subprocess.TimeoutExpired:
            if proc:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.communicate(timeout=3)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.communicate()
        except (OSError, ValueError, AttributeError):
            pass
        # A remote post might have succeeded before its acknowledgement was lost. No auto-retry.
        return None


class AlertMonitor:
    def __init__(self, sessions, path, sender, clock=time.time):
        self.sessions, self.path, self.sender, self.clock = sessions, path, sender, clock
        self.rules = AlertRules()
        self.error = None
        self.checked_at = None
        self.task = None
        self.stopping = threading.Event()
        self.tick_lock = threading.Lock()

    def start(self):
        # An interrupted in-flight delivery is ambiguous, so never send it again automatically.
        with self.sessions.begin() as s:
            for event in s.scalars(select(AlertEvent).where(AlertEvent.status == "delivering")):
                event.status = "uncertain"
                event.error = "Delivery was interrupted. Check the Discord channel before any manual resend."
        self.task = asyncio.create_task(self.loop(), name="alerts")

    async def stop(self):
        self.stopping.set()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def loop(self):
        while True:
            try:
                # Shield the worker: orderly shutdown waits for an in-flight CLI, bounded by 33s.
                worker = asyncio.create_task(asyncio.to_thread(self.tick))
                try: await asyncio.shield(worker)
                except asyncio.CancelledError:
                    await worker
                    raise
            except asyncio.CancelledError:
                raise
            except Exception:
                self.error = "Alert monitor could not complete a check. Delivery is paused for this check."
            await asyncio.sleep(self.rules.poll_seconds)

    def initialize(self, s, now):
        record = s.get(AlertState, "monitor")
        if record:
            return record, json.loads(record.value)
        # Exclude terminal runs already present at activation, even those in the same second.
        excluded = list(s.scalars(select(Run.id).where(Run.ended_at >= now)))
        state = {"activated_at": now, "excluded": excluded, "services": {}}
        record = AlertState(key="monitor", value=json.dumps(state))
        s.add(record)
        return record, state

    def collect(self, rules, now):
        with self.sessions.begin() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            record, state = self.initialize(s, now)
            if rules.runs.enabled:
                seen = exists().where(AlertEvent.run_id == Run.id)
                runs = s.scalars(select(Run).where(Run.stage.in_(rules.runs.stages),
                    Run.ended_at >= state["activated_at"], Run.ended_at <= now, ~Run.id.in_(state["excluded"]), ~seen)
                    .order_by(Run.ended_at, Run.id).limit(100))
                for run in runs:
                    s.add(AlertEvent(id=uuid.uuid4().hex, source_key=f"run:{run.id}", run_id=run.id,
                        kind="run_failed", message=run_message(run), destination=rules.destination,
                        status="pending", created_at=now))
            if rules.services.enabled:
                since = max(state["activated_at"], now - rules.services.window_seconds)
                snapshots = s.scalars(select(ServiceSnapshot).where(ServiceSnapshot.ts >= since, ServiceSnapshot.ts <= now)
                    .order_by(ServiceSnapshot.ts.desc(), ServiceSnapshot.id.desc()).limit(5000)).all()
                grouped = defaultdict(list)
                for row in reversed(snapshots):
                    grouped[f"{row.domain}:{row.label}"].append(row)
                for key, rows in grouped.items():
                    latest = rows[-1]
                    if latest.ts < now - rules.services.sample_max_age_seconds:
                        continue
                    known = [r for r in rows if r.runs is not None]
                    if len(known) < 2:
                        continue
                    # Use only the most recent launchd counter epoch after a manual reload.
                    first = 0
                    for i in range(1, len(known)):
                        if known[i].runs < known[i-1].runs: first = i
                    baseline = known[first]
                    if baseline.ts == latest.ts or latest.runs is None:
                        continue
                    delta = latest.runs - baseline.runs
                    elapsed = latest.ts - baseline.ts
                    allowed = rules.services.excess_runs
                    if latest.run_interval_s and latest.run_interval_s > 0:
                        allowed += math.ceil(elapsed / latest.run_interval_s * 1.2)
                    elif latest.calendar:
                        allowed = max(allowed, rules.services.calendar_allowance)
                    incident = state["services"].setdefault(key, {"active": False, "healthy": 0, "last_sample": 0})
                    if delta > allowed:
                        incident["healthy"] = 0
                        if not incident["active"]:
                            incident["active"] = True
                            event_id = uuid.uuid4().hex
                            message = (f"[MCD] Service crash loop\nService: {identifier(latest.label)}\n"
                                       f"Launches: {delta} in {elapsed}s · Allowed: {allowed}\nOpen MCD Services to inspect the job.")
                            s.add(AlertEvent(id=event_id, source_key=f"service:{event_id}", kind="service_crash_loop",
                                message=message, destination=rules.destination, status="pending", created_at=now))
                    elif latest.ts != incident["last_sample"]:
                        incident["healthy"] += 1
                        if incident["healthy"] >= rules.services.recovery_samples: incident["active"] = False
                    incident["last_sample"] = latest.ts
            record.value = json.dumps(state)

    def deliver(self, rules, now):
        if not rules.delivery_enabled:
            return
        with self.sessions.begin() as s:
            pending = s.scalars(select(AlertEvent).where(AlertEvent.status == "pending").order_by(AlertEvent.created_at, AlertEvent.id)).all()
            ids = []
            for event in pending:
                if event.created_at < now - rules.pending_max_age_seconds:
                    event.status, event.error = "expired", "Alert expired before delivery."
                elif event.destination != rules.destination:
                    event.status, event.error = "held", "Destination changed; this alert will not be rerouted automatically."
                elif len(ids) < rules.max_deliveries_per_tick:
                    ids.append(event.id)
        for event_id in ids:
            if self.stopping.is_set(): return
            current, error = load_rules(self.path)
            if error or not current.enabled or not current.delivery_enabled or current.destination != rules.destination:
                return
            # Commit the claim before contacting Discord. A restart cannot duplicate a claimed event.
            with self.sessions.begin() as s:
                claimed = s.execute(update(AlertEvent).where(AlertEvent.id == event_id, AlertEvent.status == "pending").values(status="delivering"))
                if claimed.rowcount != 1: continue
                event = s.get(AlertEvent, event_id)
                target, message = event.destination, event.message
            try: message_id = self.sender(target, message)
            except Exception: message_id = None
            with self.sessions.begin() as s:
                event = s.get(AlertEvent, event_id)
                if message_id:
                    event.status, event.message_id, event.sent_at = "sent", message_id, int(self.clock())
                else:
                    event.status = "uncertain"
                    event.error = "Delivery was not confirmed. Check Discord before any manual resend; automatic retry is disabled."

    def tick(self):
        with self.tick_lock:
            self._tick()

    def _tick(self):
        self.rules, self.error = load_rules(self.path)
        self.checked_at = int(self.clock())
        if self.error or not self.rules.enabled:
            return
        self.collect(self.rules, self.checked_at)
        self.deliver(self.rules, self.checked_at)

    def status(self):
        rules, error = load_rules(self.path)
        with self.sessions() as s:
            events = s.scalars(select(AlertEvent).order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc()).limit(25)).all()
            record = s.get(AlertState, "monitor")
            activated = json.loads(record.value)["activated_at"] if record else None
            attention = s.scalar(select(func.count()).select_from(AlertEvent).where(AlertEvent.status.in_(["held", "uncertain"]), AlertEvent.reviewed_at.is_(None)))
            pending = s.scalar(select(func.count()).select_from(AlertEvent).where(AlertEvent.status == "pending"))
        return {"enabled": rules.enabled, "delivery_enabled": rules.delivery_enabled, "destination": rules.destination,
                "checked_at": self.checked_at, "activated_at": activated, "error": error or self.error,
                "attention": attention, "pending": pending, "events": [{"id": e.id, "kind": e.kind,
                    "message": e.message, "status": e.status, "created_at": e.created_at,
                    "sent_at": e.sent_at, "message_id": e.message_id, "reviewed_at": e.reviewed_at, "error": e.error} for e in events]}
