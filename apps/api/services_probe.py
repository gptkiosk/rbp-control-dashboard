"""Pure parsers and health rules for launchd jobs.

The crash-loop rule exists because ai.hermes / com.hermes.agent restarted 238,293 times in
2026 before anyone noticed: a KeepAlive job with a bad argument looks idle in `launchctl
list`. The tell is the `runs` counter, so we track how much it grows in 24 hours.
"""

from __future__ import annotations

import re

DEFAULT_PREFIXES: tuple[str, ...] = (
    "ai.hermes.",
    "ai.openclaw.",
    "com.openclaw.",
    "com.headroom.",
    "com.operator.",
)

# Restarts allowed in 24 h beyond what a job's schedule explains.
CRASH_LOOP_RUNS_24H = 50
# Calendar jobs (StartCalendarInterval) can legitimately fire up to hourly or more; allow more.
CALENDAR_RUNS_24H = 200

_RUN_INTERVAL_RE = re.compile(r"^\trun interval = (\d+) seconds", re.MULTILINE)

_TOP_LEVEL_RE = re.compile(r"^\t([a-z][a-z ]*?) = (.*)$")
_INT_RE = re.compile(r"^(-?\d+)")


def parse_launchctl_list(text: str, prefixes: tuple[str, ...]) -> list[str]:
    """Labels from `launchctl list` whose names start with one of the prefixes."""
    labels: list[str] = []
    for line in text.splitlines()[1:]:  # first line is the "PID Status Label" header
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].startswith(prefixes):
            labels.append(parts[2])
    return sorted(set(labels))


def parse_launchctl_print(text: str) -> dict[str, object]:
    """Top-level fields from `launchctl print <domain>/<label>`.

    Only lines indented by exactly one tab are top-level; nested blocks use two or more.
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        m = _TOP_LEVEL_RE.match(line)
        if m and m.group(1) not in fields:
            fields[m.group(1)] = m.group(2).strip()
    pid = fields.get("pid")
    runs = fields.get("runs")
    interval = _RUN_INTERVAL_RE.search(text)
    return {
        "state": fields.get("state"),
        "pid": int(pid) if pid and pid.lstrip("-").isdigit() else None,
        "runs": int(runs) if runs and runs.isdigit() else None,
        "last_exit": fields.get("last exit code"),
        "path": fields.get("path"),
        "program": fields.get("program"),
        # StartInterval jobs print "run interval = N seconds"; calendar jobs carry a
        # com.apple.launchd.calendarinterval event trigger. Both legitimately raise `runs`.
        "run_interval_s": int(interval.group(1)) if interval else None,
        "calendar": "com.apple.launchd.calendarinterval" in text,
    }


def parse_systemctl_list(text: str, prefixes: tuple[str, ...]) -> list[str]:
    """User service unit names from ``systemctl --user list-units``."""
    labels: list[str] = []
    for line in text.splitlines():
        unit = line.split(maxsplit=1)[0] if line.split() else ""
        # systemd user units naturally end in .service; config prefixes are the
        # same logical names used by launchd, so allow either spelling.
        base = unit.removesuffix(".service")
        if unit.endswith(".service") and (unit.startswith(prefixes) or base.startswith(prefixes)):
            labels.append(unit)
    return sorted(set(labels))


def parse_systemctl_show(text: str) -> dict[str, object]:
    """Map machine-readable ``systemctl show`` properties to service snapshots."""
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    pid = fields.get("MainPID", "")
    runs = fields.get("NRestarts", "")
    status = fields.get("ExecMainStatus", "")
    return {
        "state": fields.get("ActiveState"),
        "pid": int(pid) if pid.isdigit() and int(pid) else None,
        # NRestarts increments on a service process restart and is therefore the
        # systemd equivalent of launchd's runs counter for crash-loop detection.
        "runs": int(runs) if runs.isdigit() else None,
        "last_exit": status if status.isdigit() else None,
        "path": fields.get("FragmentPath") or None,
        "program": fields.get("ExecStart") or None,
        "run_interval_s": None,
        "calendar": False,
    }


def exit_code(last_exit: str | None) -> int | None:
    """Numeric exit code from launchd's text, e.g. "2", "-15", "78: EX_CONFIG"."""
    if not last_exit:
        return None
    m = _INT_RE.match(last_exit.strip())
    return int(m.group(1)) if m else None


def runs_in_window(runs_now: int | None, runs_at_window_start: int | None) -> int | None:
    """Restarts during the window. A reload resets launchd's counter; treat that as runs_now."""
    if runs_now is None:
        return None
    if runs_at_window_start is None or runs_now < runs_at_window_start:
        return runs_now
    return runs_now - runs_at_window_start


def allowed_runs_24h(run_interval_s: int | None, calendar: bool) -> int:
    """Runs in 24 h that a job's schedule explains, plus headroom for restarts.

    An interval job fires 86400 / interval times a day (plus wake-from-sleep catch-ups, hence
    the 20 percent margin). Without that, a healthy 5-minute job (288 runs a day) would look
    like a crash loop.
    """
    if run_interval_s and run_interval_s > 0:
        return int(86400 / run_interval_s * 1.2) + CRASH_LOOP_RUNS_24H
    if calendar:
        return CALENDAR_RUNS_24H
    return CRASH_LOOP_RUNS_24H


def schedule_label(run_interval_s: int | None, calendar: bool) -> str:
    if run_interval_s:
        mins, secs = divmod(run_interval_s, 60)
        return f"every {mins} min" if secs == 0 and mins else f"every {run_interval_s} s"
    return "calendar" if calendar else "on demand / keep alive"


def assess(
    last_exit: str | None,
    runs_24h: int | None,
    run_interval_s: int | None = None,
    calendar: bool = False,
) -> list[str]:
    """Flags for one job. "crash_loop" is critical; "last_exit_nonzero" is a warning.

    A negative code means the job was killed by a signal (for example -15 after a manual
    restart), which is usually benign, so it is reported as a warning, never critical.
    """
    flags: list[str] = []
    if runs_24h is not None and runs_24h > allowed_runs_24h(run_interval_s, calendar):
        flags.append("crash_loop")
    code = exit_code(last_exit)
    if code is not None and code != 0:
        flags.append("last_exit_nonzero")
    return flags
