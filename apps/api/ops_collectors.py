"""Deterministic Ops report collectors. No model is ever called.

Only sources named in the host-owned `ops-collectors.json` run, and only from the fixed kinds
below. A `command` source must also name an executable that the host allowlisted in settings.
One invocation holds a single lock (in-process and on disk). Results are cached, compared with
the previous state, and a report is written only when something changed or a reminder is due,
so a healthy unchanged fleet costs no report, no alert and no tokens.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from sqlalchemy import func, select

from reports import DIR_FLAGS, FLAGS, MAX_BYTES, SUFFIXES, open_directory, sensitive_component

CONFIG = "ops-collectors.json"
STATE = "ops-collectors-state.json"
LOCK = "ops-collectors.lock"
STORE_DIR = "fleet-health"
ARCHIVE_DIR = "historic-archive"
ARCHIVE_MANIFEST = "LABEL.json"
ARCHIVE_NOTE = "ARCHIVE-LABEL.md"
ARCHIVE_LABEL = ("Historic reports, archived before the deterministic collectors were introduced. "
                 "These are read-only copies; the originals and the old Hermes jobs are unchanged.")
ARCHIVE_FILES = 500
REPORT_NAME = re.compile(r"^(\d{8}-\d{6})(?:-\d+)?\.md$")
SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
RANK = {"ok": 0, "warn": 1, "crit": 2}
KINDS = {
    "disk": {"path", "warn_pct", "crit_pct"},
    "memory": {"warn_pct", "crit_pct"},
    "jobs": {"window_s", "stuck_s", "warn_failed", "crit_failed"},
    "file_age": {"path", "warn_s", "crit_s"},
    "command": {"argv", "ok_exit", "warn_exit"},
    "service": {"name", "scope"},
    "agents": {"quiet_s", "warn_dead", "crit_dead"},
    "waits": {"warn_s", "crit_s"},
    "load": {"warn_ratio", "crit_ratio"},
    "release": {"stuck_s"},
    "dir_age": {"path", "warn_s", "crit_s"},
}
ACTIONS = {
    "disk": "Free space or move large data off this volume.",
    "memory": "Check the Processes view for the largest consumers.",
    "jobs": "Open Tasks, read the failed or waiting cards, then retry, approve or cancel.",
    "file_age": "Check that the scheduled job producing this file still runs.",
    "command": "Run the allowlisted check by hand and read its output.",
    "service": "Start or restart the service from the host, then read its log.",
    "agents": "Open Agents, read the unresponsive runs, then cancel or retry them.",
    "waits": "Open Tasks and approve, cancel or wait for the oldest queued item.",
    "load": "Check the Processes view for what is using the CPU.",
    "release": "Open Settings, then Updates, and finish or roll back the interrupted update.",
    "dir_age": "Check that the scheduled backup or export still writes to this folder.",
}
LINKS = {"jobs": "/tasks", "waits": "/tasks", "agents": "/agents", "memory": "/pi", "disk": "/pi", "load": "/pi",
         "service": "/services", "release": "/profile", "dir_age": "/pi"}
SERVICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")
SCAN_LIMIT = 2000
TOOL_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
UPDATE_OK = {"committed", "staged", "restored"}
DEFAULTS = {"interval_s": 900, "source_timeout_s": 5, "concurrency": 3, "cache_ttl_s": 60,
            "stale_after_s": 3600, "renotify_s": 21600,
            "retention": {"max_reports": 100, "max_age_days": 30, "max_total_bytes": 2 * 1024 * 1024,
                          "max_report_bytes": 32 * 1024, "max_archive_bytes": 32 * 1024 * 1024}}
# Replacement schedules. They are always created disabled; only the host config can enable one.
# Times are UTC. weekday 0 is Monday. `interval_s` is still accepted for older files but no longer drives a loop.
DEFAULT_SCHEDULES = [
    {"id": "morning-health", "label": "Morning fleet health", "enabled": False, "at": "07:00"},
    {"id": "evening-review", "label": "Evening review", "enabled": False, "at": "19:00"},
    {"id": "weekly-maintenance", "label": "Weekly fleet maintenance", "enabled": False, "at": "06:00", "weekday": 0},
]
SCHEDULE_KEYS = {"id", "label", "enabled", "every_s", "at", "weekday", "sources"}
MAX_SCHEDULES = 12
LOOP_TICK_S = 30
LIMITS = {"interval_s": (60, 86400), "source_timeout_s": (1, 30), "concurrency": (1, 8),
          "cache_ttl_s": (0, 3600), "stale_after_s": (60, 7 * 86400), "renotify_s": (300, 7 * 86400),
          "max_reports": (1, 1000), "max_age_days": (1, 365),
          "max_total_bytes": (4096, 64 * 1024 * 1024), "max_report_bytes": (1024, 256 * 1024),
          "max_archive_bytes": (0, 512 * 1024 * 1024), "every_s": (300, 7 * 86400)}
MAX_SOURCES = 40
MAX_CONFIG = 16384
MAX_EVIDENCE = 500


class ConfigError(ValueError):
    pass


class Busy(RuntimeError):
    pass


def _number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ConfigError(f"{name} must be a number from {low} to {high}.")
    return value


def _clean(text, limit=MAX_EVIDENCE):
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(text))
    return text.strip()[:limit]


def _thresholds(spec, warn, crit, default_warn, default_crit, name):
    low, high = (0, 100) if name.endswith("_pct") else (0, 10 ** 9)
    w = _number(spec.get(warn, default_warn), low, high, warn)
    c = _number(spec.get(crit, default_crit), low, high, crit)
    if c < w:
        raise ConfigError(f"{crit} must not be below {warn}.")
    return w, c


def _grade(value, warn, crit):
    return "crit" if value >= crit else "warn" if value >= warn else "ok"


def _absolute(value, private_check=True):
    if not isinstance(value, str) or not value or "\x00" in value or len(value) > 4096:
        raise ConfigError("Paths must be absolute local paths.")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ConfigError("Paths must be absolute and must not contain '..'.")
    # /private is the macOS ancestor of /var and /tmp, not a secret folder (as in report_storage).
    if private_check and any(sensitive_component(p) for i, p in enumerate(path.parts[1:], 1) if not (i == 1 and p == "private")):
        raise ConfigError("Paths must not name private folders.")
    return path


def _slot_before(schedule, when):
    """Latest fixed-time slot at or before `when` (UTC epoch seconds)."""
    hour, minute = (int(part) for part in schedule["at"].split(":"))
    slot = int(when) - int(when) % 86400 + hour * 3600 + minute * 60
    if slot > when:
        slot -= 86400
    if "weekday" in schedule:
        while (slot // 86400 + 3) % 7 != schedule["weekday"]:  # 1970-01-01 was a Thursday
            slot -= 86400
    return slot


def next_due(schedule, reference, now):
    """When the schedule is next due, given its last run (or the time it was armed)."""
    if "every_s" in schedule:
        return now if reference is None else reference + schedule["every_s"]
    period = (7 if "weekday" in schedule else 1) * 86400
    return _slot_before(schedule, reference if reference is not None else now) + period


def _schedule(raw, source_ids):
    if not isinstance(raw, dict) or set(raw) - SCHEDULE_KEYS or not SOURCE_ID.fullmatch(str(raw.get("id", ""))):
        raise ConfigError("Each schedule needs a lowercase id and only known settings.")
    out = {"id": raw["id"], "label": _clean(raw.get("label", raw["id"]), 80) or raw["id"], "enabled": raw.get("enabled", False)}
    if type(out["enabled"]) is not bool:
        raise ConfigError(f"Schedule {raw['id']}: enabled must be true or false.")
    if ("every_s" in raw) == ("at" in raw):
        raise ConfigError(f"Schedule {raw['id']} needs exactly one of every_s or at.")
    if "every_s" in raw:
        if "weekday" in raw:
            raise ConfigError("weekday only applies to a fixed time.")
        out["every_s"] = int(_number(raw["every_s"], *LIMITS["every_s"], "every_s"))
    else:
        if not isinstance(raw["at"], str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", raw["at"]):
            raise ConfigError("at must be a UTC time such as 07:30.")
        out["at"] = raw["at"]
        if "weekday" in raw:
            if type(raw["weekday"]) is not int or not 0 <= raw["weekday"] <= 6:
                raise ConfigError("weekday must be 0 (Monday) to 6 (Sunday).")
            out["weekday"] = raw["weekday"]
    if "sources" in raw:
        names = raw["sources"]
        if not isinstance(names, list) or not names or len(set(map(str, names))) != len(names) or set(map(str, names)) - source_ids:
            raise ConfigError(f"Schedule {raw['id']} names a source that is not configured.")
        out["sources"] = names
    return out


def load_config(data_dir: Path, commands: tuple[str, ...] = ()):
    """Return (config, error). A missing file yields built-in safe defaults; a broken one fails closed."""
    config = json.loads(json.dumps(DEFAULTS))
    config["sources"] = [{"id": "disk-data", "kind": "disk", "path": str(data_dir)},
                         {"id": "jobs", "kind": "jobs"}]
    config["schedules"] = json.loads(json.dumps(DEFAULT_SCHEDULES))
    try:
        fd = open_directory(data_dir)
    except OSError:
        return config, None
    try:
        try:
            file_fd = os.open(CONFIG, FLAGS | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return config, None
        with os.fdopen(file_fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise ConfigError("Collector configuration must be a regular file.")
            raw = file.read(MAX_CONFIG + 1)
        if len(raw) > MAX_CONFIG:
            raise ConfigError("Collector configuration is too large.")
        return _validate(json.loads(raw), commands), None
    except (ConfigError, ValueError, OSError) as exc:
        return None, _clean(exc if isinstance(exc, ConfigError) else "Collector configuration is unreadable.", 200)
    finally:
        os.close(fd)


def _validate(raw, commands):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS) - {"sources", "schedules"}:
        raise ConfigError("Unknown collector setting.")
    config = json.loads(json.dumps(DEFAULTS))
    for key in LIMITS:
        if key in raw:
            if key in config:
                config[key] = _number(raw[key], *LIMITS[key], key)
    if "retention" in raw:
        retention = raw["retention"]
        if not isinstance(retention, dict) or set(retention) - set(DEFAULTS["retention"]):
            raise ConfigError("Unknown retention setting.")
        for key, value in retention.items():
            config["retention"][key] = int(_number(value, *LIMITS[key], key))
    sources, seen = raw.get("sources"), set()
    if not isinstance(sources, list) or not sources or len(sources) > MAX_SOURCES:
        raise ConfigError(f"Configure 1 to {MAX_SOURCES} sources.")
    allowed = set(commands)
    for spec in sources:
        if not isinstance(spec, dict) or not SOURCE_ID.fullmatch(str(spec.get("id", ""))) or spec["id"] in seen:
            raise ConfigError("Each source needs a unique lowercase id.")
        kind = spec.get("kind")
        if kind not in KINDS or set(spec) - KINDS[kind] - {"id", "kind"}:
            raise ConfigError(f"Source {spec['id']} has an unsupported kind or setting.")
        seen.add(spec["id"])
        if kind in {"disk", "file_age", "dir_age"}:
            _absolute(spec.get("path"))
        if kind in {"disk", "memory"}:
            _thresholds(spec, "warn_pct", "crit_pct", 85, 95, "warn_pct")
        if kind in {"file_age", "dir_age"}:
            _thresholds(spec, "warn_s", "crit_s", 86400, 3 * 86400, "warn_s")
        if kind == "waits":
            _thresholds(spec, "warn_s", "crit_s", 6 * 3600, 24 * 3600, "warn_s")
        if kind == "load":
            _thresholds(spec, "warn_ratio", "crit_ratio", 1.5, 3, "warn_ratio")
        if kind == "agents":
            _thresholds(spec, "warn_dead", "crit_dead", 1, 3, "warn_dead")
            _number(spec.get("quiet_s", 900), 60, 86400, "quiet_s")
        if kind == "release":
            _number(spec.get("stuck_s", 1800), 60, 86400, "stuck_s")
        if kind == "service":
            if not isinstance(spec.get("name"), str) or not SERVICE_NAME.fullmatch(spec["name"]):
                raise ConfigError(f"Source {spec['id']} needs a plain service name.")
            if spec.get("scope", "user") not in ("user", "system"):
                raise ConfigError("scope must be user or system.")
        if kind == "jobs":
            _thresholds(spec, "warn_failed", "crit_failed", 1, 5, "warn_failed")
            _number(spec.get("window_s", 86400), 60, 30 * 86400, "window_s")
            _number(spec.get("stuck_s", 6 * 3600), 60, 30 * 86400, "stuck_s")
        if kind == "command":
            argv = spec.get("argv")
            if (not isinstance(argv, list) or not 1 <= len(argv) <= 8
                    or not all(isinstance(a, str) and 0 < len(a) <= 512 and "\x00" not in a for a in argv)):
                raise ConfigError(f"Source {spec['id']} needs an argv of up to 8 strings.")
            _absolute(argv[0], private_check=False)  # the host allowlist, not the folder name, is the control
            if argv[0] not in allowed:
                raise ConfigError(f"Executable for {spec['id']} is not in the host command allowlist.")
            for key in ("ok_exit", "warn_exit"):
                codes = spec.get(key, [0] if key == "ok_exit" else [])
                if not isinstance(codes, list) or not all(isinstance(c, int) and 0 <= c < 256 for c in codes):
                    raise ConfigError(f"{key} must list exit codes.")
    config["sources"] = sources
    schedules = raw.get("schedules", json.loads(json.dumps(DEFAULT_SCHEDULES)))
    if not isinstance(schedules, list) or len(schedules) > MAX_SCHEDULES:
        raise ConfigError(f"Configure at most {MAX_SCHEDULES} schedules.")
    config["schedules"] = [_schedule(item, seen) for item in schedules]
    if len({item["id"] for item in config["schedules"]}) != len(config["schedules"]):
        raise ConfigError("Schedule ids must be unique.")
    return config


# ---------------------------------------------------------------- checks (each returns status, summary, evidence)

def _check_disk(spec, _ctx):
    usage = shutil.disk_usage(spec["path"])
    pct = round(usage.used * 100 / usage.total, 1) if usage.total else 100.0
    free = usage.free // (1024 * 1024)
    return (_grade(pct, spec.get("warn_pct", 85), spec.get("crit_pct", 95)),
            f"{pct}% used", f"{free} MiB free at {spec['path']}")


def _check_memory(spec, _ctx):
    import psutil
    pct = float(psutil.virtual_memory().percent)
    return _grade(pct, spec.get("warn_pct", 85), spec.get("crit_pct", 95)), f"{pct}% used", "psutil virtual memory"


def _check_file_age(spec, ctx):
    path = Path(spec["path"])
    fd = open_directory(path.parent)
    try:
        info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return "crit", "missing", f"{path.name} does not exist"
    finally:
        os.close(fd)
    if not stat.S_ISREG(info.st_mode):
        return "warn", "not a regular file", path.name
    age = max(0, int(ctx["now"] - info.st_mtime))
    return (_grade(age, spec.get("warn_s", 86400), spec.get("crit_s", 3 * 86400)),
            f"{age // 60} min old", f"{path.name} modified {age}s ago")


def _check_jobs(spec, ctx):
    from models import Card, Run
    now, window = ctx["now"], int(spec.get("window_s", 86400))
    stuck = int(spec.get("stuck_s", 6 * 3600))
    with ctx["sessions"]() as session:
        failed = session.scalar(select(func.count()).select_from(Card).where(
            Card.column == "failed", Card.updated_at >= now - window)) or 0
        timed_out = session.scalar(select(func.count()).select_from(Run).where(
            Run.stage.in_(("timeout", "failed")), Run.started_at >= now - window)) or 0
        approvals = session.scalar(select(func.count()).select_from(Card).where(
            Card.column == "review", Card.needs_approval.is_(True), Card.approved_at.is_(None))) or 0
        waiting = session.scalar(select(func.count()).select_from(Card).where(
            Card.column == "queued", Card.retry_after > now)) or 0
        long_running = session.scalar(select(func.count()).select_from(Run).where(
            Run.stage == "running", Run.ended_at.is_(None), Run.started_at < now - stuck)) or 0
        neglected = session.scalar(select(func.count()).select_from(Card).where(
            Card.column == "review", Card.needs_approval.is_(True), Card.approved_at.is_(None),
            Card.updated_at < now - stuck)) or 0
    # Short waits are normal and only appear as evidence; a wait past stuck_s is a finding.
    status = _grade(failed + long_running + neglected, spec.get("warn_failed", 1), spec.get("crit_failed", 5))
    summary = f"{failed} failed, {long_running} stuck runs, {neglected} approvals waiting too long"
    return status, summary, f"{approvals} awaiting approval, {waiting} in retry wait, {timed_out} run failures in window"


def _check_command(spec, ctx):
    argv = spec["argv"]
    # A clean environment: no operator credentials or data paths ever reach a check.
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=env, cwd="/", start_new_session=True)
    try:
        out, _ = process.communicate(timeout=ctx["timeout"])
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return "warn", "timed out", f"No answer within {ctx['timeout']}s"
    line = _clean(out[:4096].decode("utf-8", "replace").splitlines()[0] if out.strip() else "", 200)
    code = process.returncode
    status = "ok" if code in spec.get("ok_exit", [0]) else "warn" if code in spec.get("warn_exit", []) else "crit"
    return status, line or f"exit {code}", f"exit {code}"


def _tool(argv, timeout, env=TOOL_ENV):
    """Run one fixed OS tool: no shell, scrubbed environment, bounded output, process group killed on timeout."""
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=env, cwd="/", start_new_session=True)
    try:
        out, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    return process.returncode, out[:65536].decode("utf-8", "replace")


def _check_service(spec, ctx):
    name, scope = spec["name"], spec.get("scope", "user")
    if sys.platform == "darwin":
        from services_probe import exit_code, parse_launchctl_print
        domain = f"gui/{os.getuid()}" if scope == "user" else "system"
        code, out = _tool(["/bin/launchctl", "print", f"{domain}/{name}"], ctx["timeout"])
        if code != 0:
            return "crit", "not loaded", f"launchctl has no {name} in {domain}"
        info = parse_launchctl_print(out)
        if info["pid"]:
            return "ok", "running", f"pid {info['pid']}"
        last = exit_code(info["last_exit"])
        if last not in (None, 0):
            return "warn", f"last exit {last}", f"state {info['state']}"
        # An interval or calendar job is idle between runs; only a bad last exit is a finding.
        if info["run_interval_s"] or info["calendar"]:
            return "ok", "scheduled", f"state {info['state']}"
        return "crit", "not running", f"state {info['state']}"
    env = dict(TOOL_ENV, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}") if scope == "user" else TOOL_ENV
    argv = ["/usr/bin/systemctl"] + (["--user"] if scope == "user" else []) + ["is-active", name]
    code, out = _tool(argv, ctx["timeout"], env)
    state = _clean(out.splitlines()[0] if out.strip() else "unknown", 40)
    if code == 0:
        return "ok", "running", f"systemd state {state}"
    return ("warn" if state in ("activating", "reloading") else "crit"), f"not running ({state})", f"systemd state {state}"


def _check_agents(spec, ctx):
    import run_liveness
    from models import Run
    now = int(ctx["now"])
    with ctx["sessions"]() as session:
        runs = session.scalars(select(Run).where(Run.stage == "running", Run.ended_at.is_(None)).limit(SCAN_LIMIT)).all()
        states = [run_liveness.check(run, int(spec.get("quiet_s", 900)), now).state for run in runs]
    dead = sum(1 for s in states if s in ("dead", "unknown"))
    return (_grade(dead, spec.get("warn_dead", 1), spec.get("crit_dead", 3)), f"{dead} unresponsive runs",
            f"{len(states)} marked running, {states.count('quiet')} quiet, {dead} with no live process")


def _check_waits(spec, ctx):
    from models import Card
    now = int(ctx["now"])
    pending = (Card.column == "review", Card.needs_approval.is_(True), Card.approved_at.is_(None))
    with ctx["sessions"]() as session:
        retrying = session.scalar(select(func.count()).select_from(Card).where(
            Card.column == "queued", Card.retry_after > now)) or 0
        retry_until = session.scalar(select(func.max(Card.retry_after)).where(Card.column == "queued", Card.retry_after > now))
        approvals = session.scalar(select(func.count()).select_from(Card).where(*pending)) or 0
        oldest = session.scalar(select(func.min(Card.updated_at)).where(*pending))
    approval_age = max(0, now - oldest) if oldest is not None else 0
    retry_wait = max(0, retry_until - now) if retry_until is not None else 0
    return (_grade(max(approval_age, retry_wait), spec.get("warn_s", 6 * 3600), spec.get("crit_s", 24 * 3600)),
            f"{approvals} approvals, {retrying} in rate-limit or retry wait",
            f"oldest approval waiting {approval_age // 60} min, longest retry wait {retry_wait // 60} min")


def _check_load(spec, _ctx):
    one, cores = os.getloadavg()[0], os.cpu_count() or 1
    ratio = round(one / cores, 2)
    return (_grade(ratio, spec.get("warn_ratio", 1.5), spec.get("crit_ratio", 3)), f"load {ratio} per core",
            f"1 minute load {one:.2f} on {cores} cores")


def _check_release(spec, ctx):
    root = getattr(ctx["settings"], "update_root", None)
    if root is None:
        return "ok", "not configured", "no update root is set"
    import release_verify as rv
    try:
        data, _ = rv.read_regular(Path(root) / "state" / "install.json", 256 * 1024, "install state")
        state = rv.strict_json(data, "install state")
    except rv.VerificationError:
        return "warn", "install state unreadable", "install.json is missing or invalid"
    if not isinstance(state, dict):
        return "warn", "install state unreadable", "install.json is not an object"
    tx, last = state.get("tx"), state.get("last") or {}
    if tx:
        started = tx.get("started_at") if isinstance(tx.get("started_at"), int) else int(ctx["now"])
        age = max(0, int(ctx["now"]) - started)
        return (("crit" if age > int(spec.get("stuck_s", 1800)) else "warn"), f"update {tx.get('phase', 'in progress')}",
                f"{tx.get('kind')} to {tx.get('target')} started {age}s ago")
    if last.get("outcome") not in (None, *UPDATE_OK):
        return "warn", f"last update {last.get('outcome')}", f"{last.get('kind')} to {last.get('target')}: {last.get('detail', '')}"
    return "ok", "idle", f"current {state.get('current') or 'none'}"


def _check_dir_age(spec, ctx):
    path = Path(spec["path"])
    label = path.name or str(path)
    try:
        fd = open_directory(path)
    except OSError:
        return "crit", "folder missing", f"{label} cannot be opened"
    newest, seen = None, 0
    try:
        with os.scandir(fd) as entries:
            for entry in entries:
                seen += 1
                if seen > SCAN_LIMIT:
                    break
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode) and (newest is None or info.st_mtime > newest):
                    newest = info.st_mtime
    finally:
        os.close(fd)
    if newest is None:
        return "crit", "no files", f"no regular files in {label}"
    age = max(0, int(ctx["now"] - newest))
    return (_grade(age, spec.get("warn_s", 86400), spec.get("crit_s", 3 * 86400)), f"newest file {age // 60} min old",
            f"{label}: newest of up to {SCAN_LIMIT} entries, {age}s old")


CHECKS = {"disk": _check_disk, "memory": _check_memory, "file_age": _check_file_age,
          "jobs": _check_jobs, "command": _check_command, "service": _check_service, "agents": _check_agents,
          "waits": _check_waits, "load": _check_load, "release": _check_release, "dir_age": _check_dir_age}


def _evaluate(spec, ctx):
    started = time.monotonic()
    try:
        status, summary, evidence = CHECKS[spec["kind"]](spec, ctx)
    except Exception as exc:  # a failing source is itself a finding, never a crashed run
        status, summary, evidence = "warn", "check failed", type(exc).__name__
    return {"id": spec["id"], "kind": spec["kind"], "status": status, "summary": _clean(summary, 200),
            "evidence": _clean(evidence), "checked_at": int(ctx["now"]),
            "elapsed_ms": int((time.monotonic() - started) * 1000)}


def _fingerprint(result):
    # Evidence and timing vary run to run; status and summary are the stable signal.
    return hashlib.sha256(f"{result['id']}|{result['status']}|{result['summary']}".encode()).hexdigest()[:16]


class OpsCollectors:
    def __init__(self, settings, sessions, root_provider, clock=time.time, hermes_root_provider=None):
        self.settings = settings
        self.sessions = sessions
        self.root_provider = root_provider
        self.hermes_root_provider = hermes_root_provider or (lambda: None)
        self.armed = {}
        self.last_archive = None
        self.clock = clock
        self.mutex = Lock()
        self.task = None
        self.last_error = None

    # -------------------------------------------------------------- state
    def _read_state(self):
        try:
            fd = open_directory(self.settings.data_dir)
        except OSError:
            return {"sources": {}}
        try:
            file_fd = os.open(STATE, FLAGS | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as file:
                state = json.loads(file.read(1024 * 1024))
            return state if isinstance(state, dict) and isinstance(state.get("sources"), dict) else {"sources": {}}
        except (OSError, ValueError):
            return {"sources": {}}
        finally:
            os.close(fd)

    def _write_state(self, state):
        fd = open_directory(self.settings.data_dir)
        temporary = f".ops-collectors-{uuid4().hex}.tmp"
        try:
            out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(out, "w") as file:
                json.dump(state, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, STATE, src_dir_fd=fd, dst_dir_fd=fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
            os.close(fd)

    # -------------------------------------------------------------- status
    def status(self):
        config, error = load_config(self.settings.data_dir, self.settings.ops_collector_commands)
        state, now = self._read_state(), self.clock()
        sources = []
        for spec in (config or {}).get("sources", []):
            entry = state["sources"].get(spec["id"])
            stale_after = config["stale_after_s"]
            if entry is None:
                sources.append({"id": spec["id"], "kind": spec["kind"], "status": "missing", "stale": True})
            else:
                sources.append({**{k: entry.get(k) for k in ("id", "kind", "status", "summary", "evidence", "checked_at", "since")},
                                "stale": now - entry.get("checked_at", 0) > stale_after})
        worst = max((RANK.get(s["status"], 1) for s in sources), default=0)
        schedules = []
        for item in (config or {}).get("schedules", []):
            last = state.get("schedules", {}).get(item["id"], {}).get("last_run")
            reference = last if last is not None else self.armed.get(item["id"])
            schedules.append({**{k: item.get(k) for k in ("id", "label", "enabled", "every_s", "at", "weekday", "sources")},
                              "last_run": last, "next_due": next_due(item, reference, now) if item["enabled"] else None})
        return {"enabled": bool(self.settings.ops_collectors_enabled), "error": error or self.last_error,
                "schedules": schedules, "archive": self.last_archive, "sources": sources,
                "overall": [k for k, v in RANK.items() if v == worst][0] if not error else "warn",
                "last_run": state.get("last_run"), "link": "/reports"}

    # -------------------------------------------------------------- run
    def run(self, source_ids=None, force=False, schedule=None):
        config, error = load_config(self.settings.data_dir, self.settings.ops_collector_commands)
        if config is None:
            raise ConfigError(error)
        specs = config["sources"]
        if source_ids is not None:
            known = {s["id"] for s in specs}
            if not isinstance(source_ids, list) or not source_ids or set(source_ids) - known:
                raise ConfigError("Refresh names a source that is not configured.")
            specs = [s for s in specs if s["id"] in source_ids]
        if not self.mutex.acquire(blocking=False):
            raise Busy()
        lock_fd = None
        try:
            data_fd = open_directory(self.settings.data_dir)
            try:
                lock_fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=data_fd)
            finally:
                os.close(data_fd)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy() from None
            return self._run_locked(config, specs, force, schedule)
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            self.mutex.release()

    def _run_locked(self, config, specs, force, schedule=None):
        now = int(self.clock())
        state = self._read_state()
        previous = state["sources"]
        ctx = {"now": now, "sessions": self.sessions, "timeout": config["source_timeout_s"], "settings": self.settings}
        todo, cached = [], 0
        for spec in specs:
            entry = previous.get(spec["id"])
            if not force and entry and now - entry.get("checked_at", 0) < config["cache_ttl_s"]:
                cached += 1
            else:
                todo.append(spec)
        results = {}
        if todo:
            pool = ThreadPoolExecutor(max_workers=int(config["concurrency"]), thread_name_prefix="ops-collector")
            futures = {pool.submit(_evaluate, spec, ctx): spec for spec in todo}
            rounds = -(-len(todo) // int(config["concurrency"]))
            done, pending = wait(futures, timeout=config["source_timeout_s"] * rounds + 1)
            pool.shutdown(wait=False, cancel_futures=True)
            for future in done:
                results[futures[future]["id"]] = future.result()
            for future in pending:
                spec = futures[future]
                results[spec["id"]] = {"id": spec["id"], "kind": spec["kind"], "status": "warn", "summary": "timed out",
                                       "evidence": f"No answer within {config['source_timeout_s']}s", "checked_at": now,
                                       "elapsed_ms": int(config["source_timeout_s"] * 1000)}
        events = []
        for sid, result in results.items():
            old = previous.get(sid)
            fingerprint = _fingerprint(result)
            changed = old is None and result["status"] != "ok" or (old is not None and old.get("fingerprint") != fingerprint)
            reminder = (old is not None and not changed and result["status"] != "ok"
                        and now - old.get("notified_at", 0) >= config["renotify_s"])
            entry = {**result, "fingerprint": fingerprint,
                     "since": old["since"] if old and old.get("fingerprint") == fingerprint else now,
                     "notified_at": old.get("notified_at", 0) if old else 0}
            if changed or reminder:
                entry["notified_at"] = now
                events.append({**result, "previous": old.get("status") if old else None,
                               "reason": "reminder" if reminder else "recovered" if result["status"] == "ok" else "changed"})
            previous[sid] = entry
        configured = {s["id"] for s in config["sources"]}
        for sid in list(previous):
            if sid not in configured:
                del previous[sid]
        stale = [s["id"] for s in config["sources"]
                 if s["id"] in previous and now - previous[s["id"]]["checked_at"] > config["stale_after_s"]]
        label = next((s["label"] for s in config["schedules"] if s["id"] == schedule), None)
        report = self._write_report(config, events, stale, now, label) if events else None
        state["last_run"] = {"at": now, "checked": sorted(results), "cached": cached, "schedule": schedule,
                             "changed": [e["id"] for e in events], "report": report}
        if schedule:
            state.setdefault("schedules", {})[schedule] = {"last_run": now}
        self._write_state(state)
        return {**state["last_run"], "events": events, "stale": stale}

    # -------------------------------------------------------------- report store
    def _open_root(self):
        root = self.root_provider()
        if root is None:
            raise OSError("Report folder is unavailable.")
        try:
            fd = open_directory(root)
        except FileNotFoundError:
            if not Path(root).is_relative_to(self.settings.data_dir.expanduser().absolute()):
                raise
            Path(root).mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = open_directory(root)
        return fd

    def _open_child(self, name):
        fd = self._open_root()
        try:
            try:
                os.mkdir(name, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            return os.open(name, DIR_FLAGS, dir_fd=fd)
        finally:
            os.close(fd)

    def _open_store(self):
        return self._open_child(STORE_DIR)

    def _write_report(self, config, events, stale, now, label=None):
        retention = config["retention"]
        stamp = datetime.fromtimestamp(now, timezone.utc)
        worst = max((RANK.get(e["status"], 1) for e in events), default=0)
        lines = [f"# Fleet health: {[k for k, v in RANK.items() if v == worst][0]}" + (f" ({label})" if label else ""),
                 f"Checked {stamp:%Y-%m-%d %H:%M:%S} UTC. Dashboard: /reports", ""]
        for e in sorted(events, key=lambda e: (-RANK.get(e["status"], 1), e["id"])):
            lines += [f"## {e['id']} - {e['status']} ({e['reason']})",
                      f"- Was: {e['previous'] or 'not checked before'}. Now: {e['summary']}.",
                      f"- Evidence: {e['evidence']} (at {datetime.fromtimestamp(e['checked_at'], timezone.utc):%H:%M:%S} UTC)",
                      f"- Next: {ACTIONS[e['kind']]} Link: {LINKS.get(e['kind'], '/reports')}", ""]
        if stale:
            lines.append("Stale sources (no recent check): " + ", ".join(stale))
        data = "\n".join(lines).encode()
        if len(data) > retention["max_report_bytes"]:
            data = data[:retention["max_report_bytes"] - 40].decode("utf-8", "ignore").encode() + b"\n\n[truncated]\n"
        fd = self._open_store()
        try:
            name = None
            for n in range(20):
                candidate = f"{stamp:%Y%m%d-%H%M%S}" + (f"-{n}" if n else "") + ".md"
                try:
                    out = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                except FileExistsError:
                    continue
                with os.fdopen(out, "wb") as file:
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
                name = f"{STORE_DIR}/{candidate}"
                break
            self._prune(fd, retention, now)
            return name
        finally:
            os.close(fd)

    @staticmethod
    def _prune(fd, retention, now):
        """Delete only files this module wrote, oldest first, always keeping the newest."""
        files = []
        with os.scandir(fd) as entries:
            for entry in entries:
                match = REPORT_NAME.match(entry.name)
                if not match:
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    files.append((entry.name, info.st_size))
        files.sort()
        cutoff = datetime.fromtimestamp(now - retention["max_age_days"] * 86400, timezone.utc).strftime("%Y%m%d-%H%M%S")
        total = sum(size for _, size in files)
        while len(files) > 1 and (len(files) > retention["max_reports"] or total > retention["max_total_bytes"]
                                  or REPORT_NAME.match(files[0][0]).group(1) < cutoff):
            name, size = files.pop(0)
            try:
                os.unlink(name, dir_fd=fd)
            except OSError:
                pass
            total -= size

    # -------------------------------------------------------------- schedule
    def run_due(self):
        """Run every enabled schedule that is due, once each. Slots missed while down collapse into one run."""
        config, error = load_config(self.settings.data_dir, self.settings.ops_collector_commands)
        if config is None:
            raise ConfigError(error)
        now, state, ran = self.clock(), self._read_state(), []
        for item in config["schedules"]:
            if not item["enabled"]:
                continue
            last = state.get("schedules", {}).get(item["id"], {}).get("last_run")
            if last is None and "every_s" not in item:
                last = self.armed.setdefault(item["id"], int(now))  # first fixed-time run waits for its next slot
            if now < next_due(item, last, now):
                continue
            try:
                self.run(item.get("sources"), schedule=item["id"])
            except Busy:
                break
            ran.append(item["id"])
        return ran

    async def loop(self, stop):
        import asyncio
        try:
            await asyncio.to_thread(self.archive_historic)
        except (ConfigError, OSError) as exc:
            self.last_error = _clean(exc, 200)
        while not stop.is_set():
            try:
                await asyncio.to_thread(self.run_due)
                self.last_error = None
            except (ConfigError, OSError) as exc:
                self.last_error = _clean(exc, 200)
            try:
                await asyncio.wait_for(stop.wait(), timeout=LOOP_TICK_S)
            except asyncio.TimeoutError:
                pass

    # -------------------------------------------------------------- archive
    def _historic_files(self, fd, skip, parts=(), found=None):
        """Report-like files at most two folders deep; symlinks, hidden and private names are skipped."""
        found = [] if found is None else found
        with os.scandir(fd) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                name = entry.name
                if len(found) >= ARCHIVE_FILES:
                    break
                if (name.startswith(".") or sensitive_component(name) or sensitive_component(Path(name).stem)
                        or (not parts and name in skip)):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode) and len(parts) < 2:
                        child = os.open(name, DIR_FLAGS, dir_fd=fd)
                        try:
                            self._historic_files(child, skip, (*parts, name), found)
                        finally:
                            os.close(child)
                    elif stat.S_ISREG(info.st_mode) and Path(name).suffix.lower() in SUFFIXES:
                        found.append((*parts, name))
                except OSError:
                    continue
        return found

    @staticmethod
    def _read_copy(root_fd, parts):
        """Read one report through directory descriptors; returns (bytes, mtime) or None."""
        directory = root_fd
        try:
            for part in parts[:-1]:
                child = os.open(part, DIR_FLAGS, dir_fd=directory)
                if directory != root_fd:
                    os.close(directory)
                directory = child
            with os.fdopen(os.open(parts[-1], FLAGS | os.O_NONBLOCK, dir_fd=directory), "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode):
                    return None
                return source.read(MAX_BYTES + 1), info.st_mtime
        except OSError:
            return None
        finally:
            if directory != root_fd:
                os.close(directory)

    def archive_historic(self):
        """Copy earlier reports into a labelled archive folder. Idempotent and non-destructive.

        Sources are the Ops report folder and, read only, the Hermes cron report folder. Originals are never
        moved, changed or deleted, and nothing is written to the Hermes folder; the old Hermes jobs are not touched.
        """
        config, _ = load_config(self.settings.data_dir, self.settings.ops_collector_commands)
        limit = (config or DEFAULTS)["retention"]["max_archive_bytes"]
        roots = {"ops": self.root_provider(), "hermes": self.hermes_root_provider()}
        archive = self._open_child(ARCHIVE_DIR)
        result = {"archived": 0, "already": 0, "left_in_place": [], "bytes": 0}
        try:
            try:
                note_fd = os.open(ARCHIVE_NOTE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=archive)
                with os.fdopen(note_fd, "w") as note:
                    note.write(f"# Historic report archive\n\n{ARCHIVE_LABEL}\n\n"
                               f"{ARCHIVE_MANIFEST} lists the source, size and SHA-256 of every copy.\n")
            except FileExistsError:
                pass
            manifest = {"label": ARCHIVE_LABEL, "files": {}}
            try:
                with os.fdopen(os.open(ARCHIVE_MANIFEST, FLAGS | os.O_NONBLOCK, dir_fd=archive), "rb") as file:
                    loaded = json.loads(file.read(4 * 1024 * 1024))
                if isinstance(loaded, dict) and isinstance(loaded.get("files"), dict):
                    manifest = loaded
            except (OSError, ValueError):
                pass
            used = sum(int(entry.get("size", 0)) for entry in manifest["files"].values())
            now = int(self.clock())
            for source, root in roots.items():
                if root is None:
                    continue
                try:
                    root_fd = open_directory(Path(root))
                except OSError:
                    continue
                try:
                    for parts in self._historic_files(root_fd, {STORE_DIR, ARCHIVE_DIR} if source == "ops" else set()):
                        key = f"{source}:{'/'.join(parts)}"
                        if key in manifest["files"]:
                            result["already"] += 1
                            continue
                        read = self._read_copy(root_fd, parts)
                        if read is None:
                            continue
                        data, modified = read
                        if len(data) > MAX_BYTES or used + len(data) > limit:
                            result["left_in_place"].append(key)
                            continue
                        copy = f"{source}--{'__'.join(parts)}"
                        try:
                            out = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=archive)
                        except FileExistsError:
                            result["left_in_place"].append(key)
                            continue
                        with os.fdopen(out, "wb") as file:
                            file.write(data)
                            file.flush()
                            os.fsync(file.fileno())
                        manifest["files"][key] = {"copy": copy, "label": "historic", "source": source, "size": len(data),
                                                  "sha256": hashlib.sha256(data).hexdigest(),
                                                  "original_modified_at": int(modified), "archived_at": now}
                        used += len(data)
                        result["archived"] += 1
                        result["bytes"] += len(data)
                finally:
                    os.close(root_fd)
            temporary = f".manifest-{uuid4().hex}.tmp"
            try:
                out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=archive)
                with os.fdopen(out, "w") as file:
                    json.dump(manifest, file, indent=1, sort_keys=True)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, ARCHIVE_MANIFEST, src_dir_fd=archive, dst_dir_fd=archive)
            finally:
                try:
                    os.unlink(temporary, dir_fd=archive)
                except FileNotFoundError:
                    pass
            result["left_in_place"] = result["left_in_place"][:20]
            self.last_archive = {**result, "at": now}
            return result
        finally:
            os.close(archive)
