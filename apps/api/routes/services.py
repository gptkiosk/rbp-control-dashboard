"""launchd services with crash-loop detection."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

import services_probe
from deps import get_session

router = APIRouter(prefix="/api")

_SEVERITY = {"crash_loop": 2, "last_exit_nonzero": 1}


@router.get("/services")
def services(session: Session = Depends(get_session)):
    now = int(time.time())
    latest = session.execute(
        text(
            "SELECT s.* FROM service_snapshot s JOIN ("
            "  SELECT label, MAX(ts) AS ts FROM service_snapshot GROUP BY label"
            ") m ON s.label = m.label AND s.ts = m.ts"
        )
    ).mappings().all()
    oldest = {
        r["label"]: r["runs"]
        for r in session.execute(
            text(
                "SELECT s.label, s.runs FROM service_snapshot s JOIN ("
                "  SELECT label, MIN(ts) AS ts FROM service_snapshot WHERE ts >= :since GROUP BY label"
                ") m ON s.label = m.label AND s.ts = m.ts"
            ),
            {"since": now - 86400},
        ).mappings()
    }
    out = []
    for r in latest:
        runs_24h = services_probe.runs_in_window(r["runs"], oldest.get(r["label"]))
        calendar = bool(r["calendar"])
        flags = services_probe.assess(r["last_exit"], runs_24h, r["run_interval_s"], calendar)
        out.append(
            {
                "label": r["label"],
                "domain": r["domain"],
                "state": r["state"],
                "pid": r["pid"],
                "runs": r["runs"],
                "runs_24h": runs_24h,
                "last_exit": r["last_exit"],
                "last_exit_code": services_probe.exit_code(r["last_exit"]),
                "flags": flags,
                "schedule": services_probe.schedule_label(r["run_interval_s"], calendar),
                "allowed_runs_24h": services_probe.allowed_runs_24h(r["run_interval_s"], calendar),
                "severity": max((_SEVERITY[f] for f in flags), default=0),
                "path": r["path"],
                "program": r["program"],
                "observed_at": r["ts"],
            }
        )
    out.sort(key=lambda s: (-s["severity"], s["label"]))
    return {"services": out, "crash_loop_threshold_24h": services_probe.CRASH_LOOP_RUNS_24H}
