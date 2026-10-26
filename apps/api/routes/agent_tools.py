"""Curated agent API. Draft writes cannot queue work or approve operator decisions."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from deps import get_session
from settings import get_settings
from models import AgentAccess, Card
from agents import REGISTRY
import cards
from routes.tasks import CardIn, DependencyIn, _dependency_maps, _card_dict

router = APIRouter(prefix="/api/agent-tools")
admin = APIRouter(prefix="/api/agent-access")

class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str = "read"
    days: int = Field(default=7, ge=1, le=30)

class DraftIn(CardIn):
    model_config = ConfigDict(extra="forbid")

class DraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=100_000)
    acceptance: str | None = Field(default=None, max_length=20_000)
    priority: str | None = None
    due_date: str | None = None
    estimate_minutes: int | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    assignee_user: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, max_length=16)
    size: str | None = Field(default=None, max_length=4)
    risk: str | None = Field(default=None, max_length=8)
    area: str | None = Field(default=None, max_length=40)
    route_reason: str | None = Field(default=None, max_length=300)

def operator(request):
    user = getattr(request.state, "user", None)
    if not user or getattr(request.state, "agent_grant", None): raise HTTPException(403, "Operator sign-in is required.")
    return user["email"]

@admin.get("")
def access_list(request: Request):
    operator(request)
    return request.app.state.agent_access.list()

@admin.post("", status_code=201)
def issue(request: Request, body: GrantIn):
    email = operator(request)
    try: return request.app.state.agent_access.issue(body.scope, body.days, email)
    except OSError: raise HTTPException(409, "Private agent credential file could not be written. Existing permissions were not expanded.") from None

@admin.post("/{grant_id}/revoke")
def revoke(request: Request, grant_id: str):
    operator(request)
    return request.app.state.agent_access.revoke(grant_id)

def grant(request, session, write=False):
    if write: session.execute(text("BEGIN IMMEDIATE"))
    identity = getattr(request.state, "agent_grant", None)
    row = session.get(AgentAccess, identity["id"]) if identity else None
    if not row or row.revoked_at or row.expires_at <= request.app.state.agent_access.clock():
        raise HTTPException(401, "Agent access is no longer active.")
    if write and row.scope != "draft": raise HTTPException(403, "Read access cannot change drafts.")
    return row

def draft(session, card_id):
    card = session.get(Card, card_id)
    if not card: raise HTTPException(404, "Task not found.")
    if card.created_by != "hermes" or card.column != "backlog":
        raise HTTPException(403, "Hermes can edit only its own Backlog drafts. Operator action is required for other tasks.")
    return card

def task(session, card):
    data = _card_dict(card, deps=_dependency_maps(session, [card.id]))
    # _card_dict without a last run exposes no commands, logs, session IDs or result text.
    # Approval nonces and audit are for the operator's approve request only.
    for key in ("approval_challenge", "approval_pin", "approval_audit"):
        data.pop(key, None)
    return data

@router.get("/tasks")
def tasks(request: Request, session: Session = Depends(get_session)):
    grant(request, session)
    rows = session.scalars(select(Card).order_by(Card.id.desc()).limit(500)).all()
    return {"cards": [task(session, c) for c in rows], "limited": len(rows) == 500}

@router.get("/tasks/{card_id}")
def get_task(request: Request, card_id: int, session: Session = Depends(get_session)):
    grant(request, session)
    card = session.get(Card, card_id)
    if not card: raise HTTPException(404, "Task not found.")
    return task(session, card)

@router.get("/agents")
def agents(request: Request, session: Session = Depends(get_session)):
    grant(request, session)
    collector = request.app.state.collector
    sub = (collector.subagents if collector else None) or {}
    return {"agents": [{"id": a.id, "name": a.name, "role": a.role,
        "available": a.available(get_settings()), "default_model": a.default_model(),
        "subagents": {"agents": [{"id": r.get("id"), "name": r.get("name")} for r in (sub.get(a.id) or {}).get("agents", [])]}}
        for a in REGISTRY.values()]}

@router.post("/tasks", status_code=201)
def create(request: Request, body: DraftIn, session: Session = Depends(get_session)):
    grant(request, session, True)
    card = cards.create(session, body.model_dump(), get_settings(), created_by="hermes")
    session.commit()
    return task(session, card)

@router.patch("/tasks/{card_id}")
def edit(request: Request, card_id: int, body: DraftPatch, session: Session = Depends(get_session)):
    grant(request, session, True)
    card = draft(session, card_id)
    data = body.model_dump(exclude_unset=True)
    if any(data.get(k) is None for k in ("title", "body", "priority", "tags") if k in data):
        raise HTTPException(422, "Title, description, priority and tags cannot be null.")
    cards.edit(session, card, data, get_settings())
    session.commit()
    return task(session, card)

@router.post("/tasks/{card_id}/dependencies", status_code=201)
def dependency(request: Request, card_id: int, body: DependencyIn, session: Session = Depends(get_session)):
    grant(request, session, True)
    card = draft(session, card_id)
    cards.add_dependency(session, card, body.depends_on_id)
    session.commit()
    return task(session, card)

@router.delete("/tasks/{card_id}/dependencies/{depends_on_id}")
def remove_dependency(request: Request, card_id: int, depends_on_id: int, session: Session = Depends(get_session)):
    grant(request, session, True)
    card = draft(session, card_id)
    cards.remove_dependency(session, card, depends_on_id)
    session.commit()
    return task(session, card)


@router.get('/coordinator')
def coordinator_view(request:Request,operation:str,project_id:int|None=None,working_dir:str='',
        project_type:str|None=None,session:Session=Depends(get_session)):
    identity=grant(request,session)
    if operation not in {'capabilities','types','context','models','status','workspace','repository_intake','packet','intake_questions'}:
        raise HTTPException(403,'This grant does not include run diagnostics or execution.')
    import coordinator_read
    return coordinator_read.read(session,get_settings(),operation,identity.created_by,project_id=project_id,
        working_dir=working_dir,project_type=project_type)
