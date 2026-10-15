"""Housekeeping the coordinator can find, explain and propose, and only this code can do.

The principle: a model reads findings and writes words; deterministic code decides and acts. Nothing here is reachable by a
model's own tool call with write effect. A model proposes finding ids; the operator approves; `apply` re-verifies every id
against live state, takes a consistent database backup when rows change, acts, and writes an audit trail.

Kinds (each: scan, verify at apply time, apply):
  stale_approval_wait   a run left in awaiting_approval on a story that is already done or failed, because a later run on that
                        story succeeded. Nothing can be decided any more. Applied as stage 'cancelled' (superseded) with an
                        audit note; results, logs, usage and sessions are never touched.
  old_update_backup     an update backup folder under <data>/upgrades older than the retention rule. The newest few are always
                        kept, and nothing is removed while a source update is running. Receipts (the small audit JSON) are kept.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

from sqlalchemy import select, text

from failure_mining import redact
from models import MaintenanceProposal, Run, RunEvent

BACKUP_KEEP_NEWEST = 3
BACKUP_MIN_AGE_S = 30 * 86400
BACKUP_NAME = re.compile(r"^(?:[0-9]{8}T[0-9]{6}Z|pre-[a-z0-9-]{3,60}-[0-9]{8}T[0-9]{6})$")
FINDING_ID = re.compile(r"^(?:stale_approval_wait:[0-9]{1,9}|old_update_backup:[A-Za-z0-9-]{8,90})$")
MAX_IDS = 50

STALE_SQL = text(
    'SELECT r.id AS run_id, r.card_id, r.agent, r.started_at, r.ended_at, c.title, c."column" AS col, '
    "(SELECT MIN(r2.id) FROM run r2 WHERE r2.card_id = r.card_id AND r2.id > r.id AND r2.stage = 'succeeded') AS later "
    "FROM run r JOIN card c ON c.id = r.card_id "
    "WHERE r.stage = 'awaiting_approval' AND c.\"column\" IN ('done', 'failed') ORDER BY r.id")


class MaintenanceError(Exception):
    pass


def upgrades_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "upgrades"


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def _update_running(data_dir: Path) -> bool:
    try:
        import source_update
        return source_update.operation_active(Path(data_dir))
    except Exception:  # noqa: BLE001 - when in doubt, treat an update as running and leave backups alone
        return True


# ---------------------------------------------------------------------------- scan


def _stale_findings(s, now: int) -> list[dict]:
    out = []
    for row in s.execute(STALE_SQL).mappings():
        if row["later"] is None:
            continue                                         # no later success: not provably superseded, so not a finding
        age_h = round((now - (row["ended_at"] or row["started_at"] or now)) / 3600, 1)
        out.append({
            "id": f"stale_approval_wait:{row['run_id']}", "kind": "stale_approval_wait",
            "reason": f"Run {row['run_id']} ({row['agent']}) was left waiting for output approval, but its story is {row['col']} and run {row['later']} completed it. There is nothing left to decide.",
            "evidence": {"run_id": row["run_id"], "story_id": row["card_id"], "story": redact(row["title"], 120), "story_state": row["col"],
                         "completed_by_run": row["later"], "age_hours": age_h},
            "action": "Mark the run cancelled (superseded) with an audit note. Results and logs are not changed."})
    return out


def _backup_findings(data_dir: Path, now: int) -> list[dict]:
    base = upgrades_dir(data_dir)
    try:
        entries = [e for e in os.scandir(base) if e.is_dir(follow_symlinks=False) and BACKUP_NAME.match(e.name)]
    except OSError:
        return []
    entries.sort(key=lambda e: e.stat(follow_symlinks=False).st_mtime, reverse=True)
    if _update_running(data_dir):
        return []
    out = []
    for entry in entries[BACKUP_KEEP_NEWEST:]:
        age = now - entry.stat(follow_symlinks=False).st_mtime
        if age < BACKUP_MIN_AGE_S:
            continue
        out.append({
            "id": f"old_update_backup:{entry.name}", "kind": "old_update_backup",
            "reason": f"Update backup {entry.name} is {int(age // 86400)} days old and is not one of the newest {BACKUP_KEEP_NEWEST}.",
            "evidence": {"name": entry.name, "age_days": int(age // 86400), "size_mb": round(_dir_size(Path(entry.path)) / 1048576, 1)},
            "action": "Delete the backup folder. The receipt file beside it is kept."})
    return out


def scan(s, data_dir: Path, now: int | None = None) -> list[dict]:
    now = int(now if now is not None else time.time())
    return _stale_findings(s, now) + _backup_findings(Path(data_dir), now)


# ---------------------------------------------------------------------------- apply


def _audit(data_dir: Path, entry: dict) -> None:
    folder = Path(data_dir) / "maintenance"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    fd = os.open(folder / "audit.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def backup_database(data_dir: Path, now: int) -> Path:
    """A consistent copy of the task database (SQLite's backup API works while the service runs)."""
    folder = upgrades_dir(data_dir) / f"pre-maintenance-{time.strftime('%Y%m%dT%H%M%S', time.gmtime(now))}"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = folder / "data.db"
    source, dest = sqlite3.connect(str(Path(data_dir) / "data.db"), timeout=30), sqlite3.connect(str(target))
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    os.chmod(target, 0o600)
    return target


def apply(s, data_dir: Path, finding_ids: list[str], actor: str, now: int | None = None) -> list[dict]:
    """Re-verify and apply exactly these findings. Returns one outcome per id; a finding that changed is skipped, never forced."""
    now = int(now if now is not None else time.time())
    ids = list(dict.fromkeys(finding_ids))
    if not ids or len(ids) > MAX_IDS or any(not FINDING_ID.match(i) for i in ids):
        raise MaintenanceError("Give between 1 and %d valid finding ids." % MAX_IDS)
    current = {f["id"]: f for f in scan(s, data_dir, now)}
    outcomes: list[dict] = []
    stale = [i for i in ids if i.startswith("stale_approval_wait:") and i in current]
    backup = None
    if stale:
        backup = backup_database(Path(data_dir), now)            # before any row changes; the writer lock is not held yet
    for finding_id in ids:
        found = current.get(finding_id)
        if found is None:
            outcomes.append({"id": finding_id, "status": "skipped", "reason": "No longer a finding: it changed since it was listed."})
            continue
        if found["kind"] == "stale_approval_wait":
            run_id, later = found["evidence"]["run_id"], found["evidence"]["completed_by_run"]
            run = s.get(Run, run_id)
            if run is None or run.stage != "awaiting_approval":
                outcomes.append({"id": finding_id, "status": "skipped", "reason": "The run is no longer waiting."})
                continue
            run.stage = "cancelled"
            run.error = f"Superseded: this run's output approval was never decided and run #{later} later completed the story. Resolved by housekeeping."
            s.add(RunEvent(run_id=run_id, ts=now, kind="stage", text="cancelled"))
            s.add(RunEvent(run_id=run_id, ts=now, kind="note", text=(
                f"Housekeeping (approved by {actor}): run #{run_id} was left in awaiting_approval after its story was completed by run #{later}. "
                "The stage is now cancelled (superseded). The original result, logs, model, usage and session were not changed; "
                "no model was resumed and nothing was written by this correction.")))
            outcomes.append({"id": finding_id, "status": "applied", "backup": str(backup)})
        else:
            name = found["evidence"]["name"]
            path = upgrades_dir(data_dir) / name
            if path.is_symlink() or not path.is_dir() or not BACKUP_NAME.match(name):
                outcomes.append({"id": finding_id, "status": "skipped", "reason": "Not a plain backup folder."})
                continue
            shutil.rmtree(path)
            outcomes.append({"id": finding_id, "status": "applied"})
    s.commit()
    for outcome in outcomes:
        _audit(Path(data_dir), {"at": now, "actor": actor, **outcome})
    return outcomes


# ---------------------------------------------------------------------------- proposals


def proposal_dict(p: MaintenanceProposal) -> dict:
    return {"id": p.id, "created_at": p.created_at, "created_by": p.created_by, "summary": p.summary, "finding_ids": json.loads(p.finding_ids),
            "status": p.status, "decided_at": p.decided_at, "decided_by": p.decided_by, "result": json.loads(p.result) if p.result else None}


def propose(s, data_dir: Path, owner: str, finding_ids: list[str], summary: str, now: int | None = None) -> MaintenanceProposal:
    """Record a proposal for exactly these ids. Only ids that are findings right now can be proposed."""
    now = int(now if now is not None else time.time())
    ids = list(dict.fromkeys(finding_ids))
    if not ids or len(ids) > MAX_IDS or any(not FINDING_ID.match(i) for i in ids):
        raise MaintenanceError("Propose between 1 and %d valid finding ids." % MAX_IDS)
    live = {f["id"] for f in scan(s, data_dir, now)}
    unknown = [i for i in ids if i not in live]
    if unknown:
        raise MaintenanceError("These are not current findings: " + ", ".join(unknown[:5]))
    existing = s.scalar(select(MaintenanceProposal).where(MaintenanceProposal.status == "pending", MaintenanceProposal.finding_ids == json.dumps(sorted(ids))))
    if existing:
        return existing
    row = MaintenanceProposal(created_at=now, created_by=owner, summary=redact(summary, 500), finding_ids=json.dumps(sorted(ids)), status="pending")
    s.add(row)
    s.commit()
    return row


def decide(s, data_dir: Path, proposal_id: int, approve: bool, actor: str, now: int | None = None) -> MaintenanceProposal:
    now = int(now if now is not None else time.time())
    row = s.get(MaintenanceProposal, proposal_id)
    if row is None or row.status != "pending":
        raise MaintenanceError("That proposal is not waiting for a decision.")
    row.decided_at, row.decided_by = now, actor
    if not approve:
        row.status = "rejected"
        s.commit()
        return row
    try:
        outcomes = apply(s, data_dir, json.loads(row.finding_ids), actor, now)
        row.status = "applied" if any(o["status"] == "applied" for o in outcomes) else "failed"
        row.result = json.dumps(outcomes)
    except (MaintenanceError, OSError, sqlite3.Error) as exc:
        s.rollback()
        row = s.get(MaintenanceProposal, proposal_id)
        row.status, row.decided_at, row.decided_by, row.result = "failed", now, actor, json.dumps([{"status": "error", "reason": type(exc).__name__}])
    s.commit()
    return row
