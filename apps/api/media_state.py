"""The decisions made about a project's media, kept with the project.

`media/decisions.json` in the project folder records, per slot, whether it was skipped (the site ships on the fallback) and a short history of
what happened: generated, accepted, rejected, published, skipped, restored. It is written only by MCD and only describes choices; it grants
nothing and no code reads it as an instruction. Published files and candidates on disk remain the source of truth for what exists; this file is
the memory of why. It survives restarts and moves with the folder.
"""
from __future__ import annotations

import json
import os
import time
import threading
from pathlib import Path

FILE = Path("media") / "decisions.json"
EVENTS = {"generated", "generate_failed", "accepted", "rejected", "published", "skipped", "restored", "regenerated", "plan_edited"}
MAX_HISTORY = 40


def _path(root):
    return Path(root) / FILE


def load(root):
    try:
        data = json.loads(_path(root).read_text("utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("slots"), dict) else {"slots": {}}
    except (OSError, ValueError):
        return {"slots": {}}


def _write(root, data):
    path = _path(root)
    folder = path.parent
    if folder.is_symlink() or path.is_symlink():
        return                                    # never write through a link
    folder.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def record(root, slot, event, detail="", actor=""):
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(str(Path(root).resolve()), threading.RLock())
    with lock:
        return _record(root, slot, event, detail, actor)


def _record(root, slot, event, detail="", actor=""):
    """Append an event to a slot's history. `skipped` and `restored` also set or clear the skip flag. Returns the slot's entry."""
    if event not in EVENTS:
        raise ValueError(event)
    data = load(root)
    entry = data["slots"].setdefault(slot, {"skipped": False, "history": []})
    if event == "skipped":
        entry["skipped"] = True
    elif event in {"restored", "published", "accepted", "generated"}:
        entry["skipped"] = False
    entry["history"] = (entry.get("history", []) + [{"ts": int(time.time()), "event": event, "detail": str(detail)[:400], "actor": str(actor)[:120]}])[-MAX_HISTORY:]
    _write(root, data)
    return entry


def entry(root, slot):
    e = load(root)["slots"].get(slot) or {}
    return {"skipped": bool(e.get("skipped")), "history": list(e.get("history", []))[-6:]}


DECISIONS = {"accepted", "published", "rejected", "skipped"}


def unreviewed(root, slot):
    """How many generations this slot has had since the last decision about it (accept, publish, reject or skip): paid for, not yet looked at."""
    count = 0
    for item in (load(root)["slots"].get(slot) or {}).get("history", []):
        if item.get("event") in DECISIONS:
            count = 0
        elif item.get("event") in {"generated", "regenerated"}:
            count += 1
    return count


def summary(slots, is_published):
    """Counts and a plain-text summary for a decision record. `slots` are slot dicts with `name` and `skipped`; `is_published(slot)` says if files exist."""
    done, skipped, pending = [], [], []
    for s in slots:
        (done if is_published(s) else skipped if s.get("skipped") else pending).append(s["name"])
    total = len(slots)
    parts = [f"Media: {len(done)} of {total} slots published" + (f", {len(skipped)} skipped (the site uses its fallback)" if skipped else "") + (f", {len(pending)} still undecided" if pending else "") + "."]
    if done:
        parts.append("Published: " + ", ".join(done) + ".")
    if skipped:
        parts.append("Skipped: " + ", ".join(skipped) + ".")
    if pending:
        parts.append("Undecided: " + ", ".join(pending) + ".")
    return {"published": len(done), "skipped": len(skipped), "pending": len(pending), "total": total, "complete": not pending and total > 0,
            "pending_slots": pending, "text": " ".join(parts)}
