"""Subscription limit awareness for Claude Code and Codex.

When a run stops on a usage or session limit, MCD records one limit event per provider with
the time the CLI says it lifts, tells the operator once, and offers a single choice: send the
stories that have not started to an approved alternate route of the same grade until the limit
lifts. Without that choice nothing changes: each story still hands itself off when it meets the
limit (see projects.on_finish), exactly as before.

Only routes the approved plan already lists are ever used, so this never widens what a story
may run on. A lift time comes from the CLI's own message; when it is missing the event expires
after a few hours or at the first later success on that provider.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from models import Card, ProjectTask, ProviderLimit

PROVIDERS = ("claude", "codex")
NAMES = {"claude": "Claude Code", "codex": "Codex"}
UNKNOWN_LIFT_TTL_S = 6 * 3600
MAX_LIFT_AHEAD_S = 8 * 86400

# A real subscription limit. Plain rate limits and 429s are short and handled as transient
# errors, so they only count when the message also says when to try again.
NARROW = re.compile(r"(?:usage|session|weekly|daily|hourly|5.?hour) limit|hit your (?:\w+ )?limit|"
                    r"limit reached|quota (?:exceeded|exhausted)", re.I)
BROAD = re.compile(r"rate.?limit|too many requests|quota|\b429\b", re.I)

MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
# Claude: "You've hit your session limit · resets 7:40pm (America/Los_Angeles)", "resets 11am (...)".
RESET_RE = re.compile(
    r"resets?\s+(?:at\s+)?(?:(?P<mon>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?:at\s+)?)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>[ap])\.?m\.?(?:\s*\((?P<tz>[A-Za-z_]+(?:/[A-Za-z_+-]+)*)\))?", re.I)
# Codex: "try again at 10:03 PM." and "try again at Oct 13th, 2026 3:04 AM."
AGAIN_RE = re.compile(
    r"try again (?:at|after)\s+(?:(?P<mon>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?:(?P<year>\d{4})\s+)?(?:at\s+)?)?(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>[AP])\.?M\.?", re.I)


def parse_reset(text: str, now: int, local_tz=None) -> int | None:
    """Epoch seconds when the CLI says the limit lifts, or None when it does not say or says
    something implausible. A time without a date is the next such time after ``now``."""
    match = RESET_RE.search(text or "") or AGAIN_RE.search(text or "")
    if not match:
        return None
    g = match.groupdict()
    zone = local_tz or datetime.now().astimezone().tzinfo
    if g.get("tz"):
        try:
            zone = ZoneInfo(g["tz"])
        except (ZoneInfoNotFoundError, ValueError):
            pass
    hour = int(g["h"]) % 12 + (12 if g["ap"].lower() == "p" else 0)
    minute = int(g.get("m") or 0)
    if not (0 <= minute < 60) or not (1 <= int(g["h"]) <= 12):
        return None
    now_dt = datetime.fromtimestamp(now, zone)
    try:
        if g.get("mon"):
            month = MONTHS.get(g["mon"][:3].lower())
            if month is None:
                return None
            year = int(g.get("year") or now_dt.year)
            dt = datetime(year, month, int(g["day"]), hour, minute, tzinfo=zone)
            if not g.get("year") and dt < now_dt - timedelta(days=1):
                dt = dt.replace(year=year + 1)
        else:
            dt = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if dt <= now_dt:
                dt += timedelta(days=1)
    except ValueError:
        return None
    lift = int(dt.timestamp())
    return lift if lift - now <= MAX_LIFT_AHEAD_S else None


def clock_label(epoch: int, now: int) -> str:
    """'4:00 PM', or 'Oct 14, 3:00 AM' when it is not today, in the host's time zone."""
    dt, today = datetime.fromtimestamp(epoch).astimezone(), datetime.fromtimestamp(now).astimezone()
    clock = dt.strftime("%I:%M %p").lstrip("0")
    return clock if dt.date() == today.date() else f"{dt.strftime('%b')} {dt.day}, {clock}"


# ---------------------------------------------------------------------------- grades


def tier(model: str | None) -> str:
    """light, mid or top, from the model name. Unknown names count as mid."""
    name = (model or "").lower()
    if any(k in name for k in ("haiku", "luna", "mini", "small")):
        return "light"
    if any(k in name for k in ("opus", "sol", "astra", "ultra", "max")):
        return "top"
    return "mid"


def alternate(routes: list[dict], agent: str, model: str | None, limited: set[str]) -> dict | None:
    """The approved route of the other subscription provider closest in grade, or None.
    Never a provider that is itself limited."""
    others = [r for r in routes if r.get("agent") in PROVIDERS and r["agent"] != agent
              and r["agent"] not in limited]
    same = [r for r in others if tier(r.get("model")) == tier(model)]
    return (same or others or [None])[0]


def other_provider(provider: str) -> str:
    return "codex" if provider == "claude" else "claude"


# ---------------------------------------------------------------------------- events


def is_active(row: ProviderLimit, now: int) -> bool:
    if row.resolved_at is not None:
        return False
    if row.lift_at is not None:
        return row.lift_at > now
    return row.last_seen_at > now - UNKNOWN_LIFT_TTL_S


def active(s, now: int) -> list[ProviderLimit]:
    rows = s.scalars(select(ProviderLimit).where(ProviderLimit.resolved_at.is_(None))
                     .order_by(ProviderLimit.detected_at.desc())).all()
    return [r for r in rows if is_active(r, now)]


def active_row(s, provider: str, now: int) -> ProviderLimit | None:
    return next((r for r in active(s, now) if r.provider == provider), None)


def limited_providers(s, now: int) -> set[str]:
    return {r.provider for r in active(s, now)}


def observe(s, run, now: int) -> ProviderLimit | None:
    """Called for every finished run. Records or refreshes a limit event on a limit failure and
    ends the event when a later run on the same provider succeeds. Returns the event, if any."""
    if run.agent not in PROVIDERS:
        return None
    if run.stage == "succeeded":
        for row in active(s, now):
            if row.provider == run.agent and (run.started_at or now) >= row.detected_at:
                row.resolved_at = now
        return None
    if run.stage not in ("failed", "timeout"):
        return None
    text = f"{run.error or ''}\n{run.result_text or ''}"
    lift = parse_reset(text, now) if (NARROW.search(text) or BROAD.search(text)) else None
    if not NARROW.search(text) and lift is None:
        return None
    row = active_row(s, run.agent, now)
    if row is None:
        row = ProviderLimit(provider=run.agent, detected_at=now, last_seen_at=now, lift_at=lift,
                            run_id=run.id, rerouting=False, handoffs=0, rerouted=0)
        s.add(row)
    else:
        row.last_seen_at = now
        if lift is not None:
            row.lift_at = max(row.lift_at or 0, lift)
    if row.lift_at and "Limit lifts" not in (run.error or ""):
        run.error = f"{(run.error or '').rstrip()} Limit lifts about {clock_label(row.lift_at, now)}."
    return row


def note_handoff(s, provider: str, now: int) -> None:
    row = active_row(s, provider, now)
    if row is not None:
        row.handoffs += 1


def rerouting_row(s, provider: str, now: int) -> ProviderLimit | None:
    row = active_row(s, provider, now)
    return row if row is not None and row.rerouting else None


def set_reroute(s, provider: str, enabled: bool, now: int) -> ProviderLimit | None:
    row = active_row(s, provider, now)
    if row is None:
        return None
    row.rerouting = bool(enabled)
    return row


def waiting_stories(s, provider: str) -> int:
    """Project stories that have not started and are assigned to this provider."""
    return s.scalar(select(func.count()).select_from(Card).join(ProjectTask, ProjectTask.card_id == Card.id)
                    .where(ProjectTask.role == "story", Card.agent == provider,
                           Card.assignee_type == "agent", Card.column.in_(("queued", "backlog")))) or 0


def payload(s, now: int) -> dict:
    limited = limited_providers(s, now)
    items = []
    for row in active(s, now):
        alt = other_provider(row.provider)
        waiting = waiting_stories(s, row.provider)
        items.append({
            "provider": row.provider, "name": NAMES[row.provider],
            "detected_at": row.detected_at, "lift_at": row.lift_at,
            "seconds_left": max(0, row.lift_at - now) if row.lift_at else None,
            "lift_label": clock_label(row.lift_at, now) if row.lift_at else None,
            "rerouting": row.rerouting, "handoffs": row.handoffs, "rerouted": row.rerouted,
            "waiting": waiting, "alternate": alt, "alternate_name": NAMES[alt],
            "alternate_limited": alt in limited,
            "can_reroute": waiting > 0 and alt not in limited,
        })
    return {"active": items, "now": now}
