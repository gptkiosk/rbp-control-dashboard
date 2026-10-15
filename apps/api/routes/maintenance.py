"""Operator-only housekeeping: scan, apply and decide proposals (see maintenance). Agents are refused as for every operator route."""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import maintenance
from deps import get_session
from models import MaintenanceProposal
from routes.agent_tools import operator
from settings import get_settings

router = APIRouter(prefix="/api/maintenance")


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_ids: list[str] = Field(min_length=1, max_length=maintenance.MAX_IDS)
    confirm: bool


def _refused(exc: maintenance.MaintenanceError):
    return HTTPException(409, str(exc))


@router.get("")
def overview(request: Request, s: Session = Depends(get_session)):
    operator(request)
    data_dir = get_settings().data_dir
    proposals = s.scalars(select(MaintenanceProposal).order_by(MaintenanceProposal.id.desc()).limit(20)).all()
    return {"findings": maintenance.scan(s, data_dir), "proposals": [maintenance.proposal_dict(p) for p in proposals], "auto": maintenance.auto_status(get_settings()),
            "retention": {"keep_newest_backups": maintenance.BACKUP_KEEP_NEWEST, "backup_min_age_days": maintenance.BACKUP_MIN_AGE_S // 86400}}


@router.post("/apply")
def apply(request: Request, body: ApplyIn, s: Session = Depends(get_session)):
    actor = operator(request)
    if not body.confirm:
        raise HTTPException(422, "Explicit confirmation is required.")
    try:
        return {"outcomes": maintenance.apply(s, get_settings().data_dir, body.finding_ids, actor)}
    except maintenance.MaintenanceError as exc:
        raise _refused(exc) from None


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: int, request: Request, s: Session = Depends(get_session)):
    actor = operator(request)
    try:
        return maintenance.proposal_dict(maintenance.decide(s, get_settings().data_dir, proposal_id, True, actor))
    except maintenance.MaintenanceError as exc:
        raise _refused(exc) from None


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: int, request: Request, s: Session = Depends(get_session)):
    actor = operator(request)
    try:
        return maintenance.proposal_dict(maintenance.decide(s, get_settings().data_dir, proposal_id, False, actor))
    except maintenance.MaintenanceError as exc:
        raise _refused(exc) from None
