"""Operator dashboard issue intake: Hermes creates an approval-gated implementation task."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from deps import get_session
from routes.agent_tools import operator
from routes.tasks import _one
from settings import get_settings
import issue_tasks

router = APIRouter(prefix="/api/issue-tasks")


class IssueTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue_url: str = Field(min_length=30, max_length=500)
    working_dir: str = Field(min_length=1, max_length=500)
    agent: str = Field(default="codex", pattern=r"^(codex|claude|openclaw)$")


@router.post("", status_code=201)
def create(body: IssueTaskIn, request: Request, s: Session = Depends(get_session)):
    operator(request)
    card, created, issue = issue_tasks.create_or_get(
        s, get_settings(), request.app.state.github, body.issue_url, body.working_dir, body.agent
    )
    s.commit()
    return {"created": created, "issue": issue, "task": _one(s, card)}
