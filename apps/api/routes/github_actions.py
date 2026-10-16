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


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm: bool = False


@router.get("")
def pending(request: Request):
    """Drafts waiting for a decision, each with its exact preview."""
    operator(request)
    return {"actions": request.app.state.github_actions.pending(), "writes_enabled": request.app.state.github_actions.enabled}


@router.post("/{action_id}/run")
def run(request: Request, action_id: str, body: RunIn):
    """Approve and execute one draft after the operator has read its exact preview and confirmed it. The fingerprint must match the preview shown,
    so a draft that changed since is refused; the guard still records the approval by this operator and runs its own preflight."""
    actor = operator(request)
    if not body.confirm:
        raise HTTPException(422, "Confirm the preview before running it.")
    guard = request.app.state.github_actions
    try:
        current = guard.get(action_id)
        if current["fingerprint"] != body.fingerprint:
            raise ActionError("This action changed after you read it. Review it again.")
        reviewed = guard.review(action_id, actor)
        guard.approve(action_id, reviewed["fingerprint"], reviewed["nonce"], actor)
        done = guard.execute(action_id, reviewed["fingerprint"], actor)
    except ActionError as exc:
        raise HTTPException(exc.status, exc.message) from None
    return {"state": done["state"], "result": done.get("result") or {}, "action": {k: done[k] for k in ("id", "fingerprint", "preview", "state")}}


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
