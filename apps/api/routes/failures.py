"""Operator-only, read-only views of failed runs (see failure_mining)."""
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import failure_mining
from deps import get_session

router = APIRouter(prefix="/api/failures")


@router.get("")
def failures(hours: int = Query(24, ge=1, le=336), limit: int = Query(10, ge=1, le=25), category: str | None = Query(None, max_length=30),
             agent: str | None = Query(None, max_length=20), project_id: int | None = Query(None, ge=1), s: Session = Depends(get_session)):
    return failure_mining.recent(s, int(time.time()), hours, limit, category, agent, project_id)


@router.get("/summary")
def failure_summary(hours: int = Query(24, ge=1, le=336), s: Session = Depends(get_session)):
    return failure_mining.summary(s, int(time.time()), hours)


@router.get("/{run_id}")
def failure_detail(run_id: int, s: Session = Depends(get_session)):
    data = failure_mining.detail(s, run_id)
    if data is None:
        raise HTTPException(404, "No such run.")
    return data
