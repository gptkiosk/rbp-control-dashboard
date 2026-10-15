"""Read-only jobs and telemetry (see telemetry). Signed-in operator only; agent processes are refused as for every operator route."""
import time

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

import telemetry
from deps import get_session
from routes.agent_tools import operator

router = APIRouter(prefix="/api/telemetry")


@router.get("")
def overview(request: Request, days: int = Query(30, ge=1, le=telemetry.MAX_DAYS), job: str | None = Query(None, max_length=40),
             kind: str | None = Query(None, max_length=16), risk: str | None = Query(None, max_length=8), size: str | None = Query(None, max_length=4),
             tier: str | None = Query(None, max_length=16), assignee: str | None = Query(None, max_length=255),
             agent: str | None = Query(None, max_length=40), model: str | None = Query(None, max_length=120), s: Session = Depends(get_session)):
    operator(request)
    return telemetry.overview(s, int(time.time()), days, {"job": job, "kind": kind, "risk": risk, "size": size, "tier": tier,
                                                          "assignee": assignee, "agent": agent, "model": model})
