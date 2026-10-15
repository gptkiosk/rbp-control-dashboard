"""Operator-only decisions on proposed additions to a repository's standards. Agents are refused as for every operator route."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

import projects
import standards_proposals as sp
from deps import get_session
from models import StandardsProposal
from routes.agent_tools import operator
from settings import get_settings

router = APIRouter(prefix="/api/standards")


@router.get("/proposals")
def listing(project_id: int, request: Request, s: Session = Depends(get_session)):
    operator(request)
    projects.get(s, project_id)
    return {"proposals": [sp.proposal_dict(p) for p in sp.for_project(s, project_id)]}


def _decide(proposal_id: int, request: Request, s: Session, approve: bool):
    actor = operator(request)
    row = s.get(StandardsProposal, proposal_id)
    if row is None:
        raise HTTPException(404, "No such proposal.")
    workdir = projects.document(projects.get(s, row.project_id))["working_dir"]
    try:
        return sp.proposal_dict(sp.decide(s, get_settings().data_dir, proposal_id, approve, actor, workdir))
    except sp.ProposalError as error:
        raise HTTPException(409, str(error)) from None


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: int, request: Request, s: Session = Depends(get_session)):
    return _decide(proposal_id, request, s, True)


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: int, request: Request, s: Session = Depends(get_session)):
    return _decide(proposal_id, request, s, False)
