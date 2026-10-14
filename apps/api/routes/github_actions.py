"""Separate preview, human approval and execution routes; no task/agent auto-approval."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from github_actions import ActionError
from routes.agent_tools import operator

router = APIRouter(prefix="/api/github/actions")


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=30)
    repo: str = Field(max_length=200)
    content: dict


class ApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    nonce: str = Field(min_length=20, max_length=100)


class ExecuteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


def call(request, method, *args):
    actor = operator(request)
    try:
        return getattr(request.app.state.github_actions, method)(*args, actor)
    except ActionError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.post("", status_code=201)
def draft(request: Request, body: DraftIn):
    return call(request, "draft", body.model_dump())


@router.get("/{action_id}")
def get(request: Request, action_id: str):
    operator(request)
    try:
        return request.app.state.github_actions.get(action_id)
    except ActionError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.post("/{action_id}/preview")
def preview(request: Request, action_id: str):
    return call(request, "review", action_id)


@router.post("/{action_id}/approve")
def approve(request: Request, action_id: str, body: ApprovalIn):
    return call(request, "approve", action_id, body.fingerprint, body.nonce)


@router.post("/{action_id}/revoke")
def revoke(request: Request, action_id: str):
    return call(request, "revoke", action_id)


@router.post("/{action_id}/execute")
def execute(request: Request, action_id: str, body: ExecuteIn):
    return call(request, "execute", action_id, body.fingerprint)
