"""Operator-only coordinator scorecard and plan scoring (see coordinator_score and scorecard). Agents are refused as for every operator route."""
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

import coordinator_score as cs
import scorecard
import standards
import telemetry
from deps import get_session
from routes.agent_tools import operator
from settings import get_settings

router = APIRouter(prefix="/api/coordinator")


class ScoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[dict] = Field(max_length=100)
    brief_id: str | None = Field(default=None, max_length=40)


@router.get("/scorecard")
def scorecard_report(request: Request, days: int = Query(90, ge=1, le=telemetry.MAX_DAYS), s: Session = Depends(get_session)):
    operator(request)
    return scorecard.report(s, int(time.time()), days)


@router.get("/briefs")
def briefs(request: Request):
    operator(request)
    return {"briefs": [{k: b[k] for k in ("id", "title", "brief", "expect")} for b in cs.briefs()]}


@router.post("/score")
def score(request: Request, body: ScoreIn):
    """Score any plan (for example one a model wrote for a fixed brief) with the same checks the live scorecard uses. Stores nothing."""
    operator(request)
    expect = None
    if body.brief_id:
        match = next((b for b in cs.briefs() if b["id"] == body.brief_id), None)
        if match is None:
            raise HTTPException(404, "No such brief.")
        expect = match["expect"]
    found = standards.starter(get_settings().data_dir)
    return cs.score_plan(body.nodes, expect=expect, found=found, tier_of=scorecard._tier)
