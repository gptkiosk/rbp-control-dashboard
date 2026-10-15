"""launchd services with crash-loop detection."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import service_control
import services_probe
from deps import get_session
from routes.agent_tools import operator
from settings import get_settings

router = APIRouter(prefix="/api")

_SEVERITY = {"crash_loop": 2, "last_exit_nonzero": 1}


def _listing(session: Session) -> list[dict]:
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
                "own": r["label"] == service_control.own_label(),
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
    return out


@router.get("/services")
def services(session: Session = Depends(get_session)):
    return {"services": _listing(session), "crash_loop_threshold_24h": services_probe.CRASH_LOOP_RUNS_24H}


class ActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool
    confirm_label: str | None = Field(default=None, max_length=128)


def _run():
    return service_control.default_run


@router.get("/services/{label}/why")
def why(label: str, request: Request, session: Session = Depends(get_session)):
    operator(request)
    rows = {r["label"]: r for r in _listing(session)}
    try:
        service_control._check(label, set(rows), get_settings().service_prefixes)
    except service_control.ServiceError as error:
        raise HTTPException(404, str(error)) from None
    return service_control.why(rows[label], rows[label]["flags"], service_control.read_log(label, Path.home(), _run()))


@router.post("/services/{label}/{action}")
def act(label: str, action: str, body: ActionIn, request: Request, session: Session = Depends(get_session)):
    actor = operator(request)
    if not body.confirm:
        raise HTTPException(422, "Explicit confirmation is required.")
    rows = {r["label"] for r in _listing(session)}
    try:
        return service_control.act(action, label, rows, get_settings().service_prefixes, get_settings().data_dir, actor, run=_run(), confirm_label=body.confirm_label)
    except service_control.ServiceError as error:
        raise HTTPException(409, str(error)) from None
