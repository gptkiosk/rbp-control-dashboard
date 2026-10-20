"""Agent chat: one thread per conversation, each turn a tracked run that resumes the agent's session.

Turns follow the card approval rules: a message that pushes, deploys, publishes or contacts a
person, or edits a main/master branch, waits for the operator's approval before it runs.
"""

from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import approval
from agents import REGISTRY
from deps import get_session
import billing
from dispatch_gate import resolve_free_alias, reviewed_route_class
from dispatcher import remove_run_logs
from models import ChatMessage, ChatThread, Run
from settings import get_settings

router = APIRouter(prefix="/api/chat")


class ThreadIn(BaseModel):
    agent: str
    working_dir: str
    title: str | None = Field(default=None, max_length=200)
    model: str | None = None
    mode: str = "read"
    agent_target: str | None = None


class ThreadPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    model: str | None = None
    mode: str | None = None


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    # Background the app adds for the agent (the project consultant's guidance and what this installation knows). It is sent to the agent with
    # the message but is not the operator's words: the approval check reads `text` only, and the chat shows `text` plus a note that it was sent.
    context: str | None = Field(default=None, max_length=30_000)


CONTEXT_MARK = "\n\n---\nThe operator's message:\n"


def _split_context(stored: str) -> tuple[str, str]:
    head, mark, tail = stored.partition(CONTEXT_MARK)
    return (head, tail) if mark else ("", stored)


def _now() -> int:
    return int(time.time())


def _dispatcher(request: Request):
    d = request.app.state.dispatcher
    if d is None:
        raise HTTPException(status_code=503, detail="Agent dispatch is disabled.")
    return d


def _gate_settings(request: Request):
    d = getattr(request.app.state, "dispatcher", None)
    return d.settings if d is not None else get_settings()    # the settings the gate itself will read


def resolve_model(s: Session, request: Request, agent: str, agent_target: str | None, model: str | None) -> str | None:
    return resolve_free_alias(s, _gate_settings(request), agent, agent_target, model)


def route_problem(s: Session, request: Request, agent: str, agent_target: str | None, model: str | None) -> str | None:
    """Why the dispatch gate would refuse this route, in words the operator can act on, or None when it can start.

    The gate refuses a route nobody has reviewed (PRICE_UNKNOWN) only after the message was accepted, so the chat looked sent and then failed
    with a code. Asking first keeps the refusal at the moment the operator can still pick another model."""
    spec = REGISTRY.get(agent)
    settings = _gate_settings(request)
    chosen = model or (spec.default_model() if spec else None)
    if spec is None or not chosen:
        return None
    price = reviewed_route_class(s, settings, SimpleNamespace(agent=agent, agent_target=agent_target, id=None), chosen)
    if price is None and billing.limits(s, settings)["require_reviewed_pricing"]:
        hint = "Choose a model in Profile, AI defaults, or review the route in Billing & rates."
        if agent == "hermes":
            from native_routes import read
            free = [m for m in read(settings).get("hermes", {}).get("models", ()) if m and (m.endswith(":free") or m == "openrouter/free")]
            hint = (f"Hermes is set up with these free models: {', '.join(free)}. Choose one in Profile, AI defaults." if free else
                    "Hermes has no free model configured. Run `hermes setup` or choose another agent in Profile, AI defaults.")
        return f"{spec.name} cannot run {chosen} here: that route has not been reviewed for pricing, so the dashboard will not start it. {hint}"
    from route_reliability import allowed_class
    if not allowed_class(s, settings, price):
        return f"{chosen} is a {price} route and this installation only starts free routes. Choose a free model in Profile, AI defaults."
    return None


def _thread(s: Session, thread_id: int) -> ChatThread:
    t = s.get(ChatThread, thread_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return t


def _msg_dict(m: ChatMessage) -> dict:
    context, text = _split_context(m.text) if m.role == "user" else ("", m.text)
    return {
        "id": m.id, "thread_id": m.thread_id, "role": m.role, "text": text, "context_chars": len(context), "status": m.status,
        "approval_reasons": json.loads(m.approval_reasons) if m.approval_reasons else [],
        "approved_at": m.approved_at, "run_id": m.run_id, "model": m.model,
        "input_tokens": m.input_tokens, "output_tokens": m.output_tokens, "cost_usd": m.cost_usd,
        "duration_s": m.duration_s, "created_at": m.created_at,
    }


def _thread_dict(t: ChatThread, busy: bool, last: ChatMessage | None = None) -> dict:
    return {
        "id": t.id, "agent": t.agent, "agent_target": t.agent_target, "title": t.title,
        "model": t.model, "mode": t.mode, "working_dir": t.working_dir, "session_id": t.session_id,
        "created_at": t.created_at, "last_activity_at": t.last_activity_at, "busy": busy,
        "last_message": ({"role": last.role, "text": (_split_context(last.text)[1] if last.role == "user" else last.text)[:200], "status": last.status}
                         if last else None),
    }


@router.get("/threads")
def list_threads(request: Request, s: Session = Depends(get_session)):
    d = request.app.state.dispatcher
    threads = s.execute(select(ChatThread).order_by(ChatThread.last_activity_at.desc())).scalars().all()
    out = []
    for t in threads:
        last = s.execute(select(ChatMessage).where(ChatMessage.thread_id == t.id)
                         .order_by(ChatMessage.id.desc()).limit(1)).scalar_one_or_none()
        out.append(_thread_dict(t, bool(d and d.thread_busy(t.id)), last))
    return {"threads": out}


@router.post("/threads", status_code=201)
def create_thread(body: ThreadIn, request: Request, s: Session = Depends(get_session)):
    spec = REGISTRY.get(body.agent)
    if spec is None:
        raise HTTPException(status_code=422, detail=f"Unknown agent: {body.agent}")
    if body.mode not in ("read", "edit"):
        raise HTTPException(status_code=422, detail="Mode must be read or edit")
    roots = get_settings().workdir_roots
    real = approval.resolve_workdir(body.working_dir, roots)
    if real is None:
        raise HTTPException(status_code=422, detail="Working directory must be an existing folder inside "
                            + ", ".join(str(r) for r in roots))
    model = resolve_model(s, request, body.agent, body.agent_target, body.model)
    problem = route_problem(s, request, body.agent, body.agent_target, model)
    if problem:
        raise HTTPException(status_code=409, detail=problem)
    now = _now()
    t = ChatThread(
        agent=body.agent, agent_target=body.agent_target, title=(body.title or f"Chat with {spec.name}").strip(),
        model=model or None, mode=body.mode, working_dir=str(real),
        session_id=str(uuid.uuid4()) if spec.preassigned_session else None,
        created_at=now, last_activity_at=now,
    )
    s.add(t)
    s.commit()
    return _thread_dict(t, False)


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, request: Request, s: Session = Depends(get_session)):
    t = _thread(s, thread_id)
    d = request.app.state.dispatcher
    msgs = s.execute(select(ChatMessage).where(ChatMessage.thread_id == thread_id)
                     .order_by(ChatMessage.id)).scalars().all()
    data = _thread_dict(t, bool(d and d.thread_busy(t.id)), msgs[-1] if msgs else None)
    data["messages"] = [_msg_dict(m) for m in msgs]
    return data


@router.patch("/threads/{thread_id}")
def patch_thread(thread_id: int, body: ThreadPatch, s: Session = Depends(get_session)):
    t = _thread(s, thread_id)
    data = body.model_dump(exclude_unset=True)
    if "mode" in data and data["mode"] not in ("read", "edit"):
        raise HTTPException(status_code=422, detail="Mode must be read or edit")
    for key, value in data.items():
        setattr(t, key, value or None if key == "model" else value)
    s.commit()
    return _thread_dict(t, False)


@router.post("/threads/{thread_id}/messages", status_code=201)
async def send_message(thread_id: int, body: MessageIn, request: Request, s: Session = Depends(get_session)):
    d = _dispatcher(request)
    t = _thread(s, thread_id)
    if d.thread_busy(t.id):
        raise HTTPException(status_code=409, detail="The agent is still answering. Wait or stop it first.")
    resolved = resolve_model(s, request, t.agent, t.agent_target, t.model)
    if resolved != t.model and t.session_id is None:       # a chat made before the alias was resolved; nothing has run, so the model can still be fixed
        t.model = resolved
        s.commit()
    problem = route_problem(s, request, t.agent, t.agent_target, t.model)
    if problem:
        raise HTTPException(status_code=409, detail=problem)
    pending = s.execute(select(ChatMessage).where(ChatMessage.thread_id == t.id,
                                                  ChatMessage.status == "pending_approval")).first()
    if pending:
        raise HTTPException(status_code=409, detail="A message is waiting for your approval in this thread.")
    reasons = approval.reasons_for(body.text, t.mode, approval.current_branch(approval.Path(t.working_dir)))
    now = _now()
    stored = f"{body.context.strip()}{CONTEXT_MARK}{body.text}" if body.context and body.context.strip() else body.text
    msg = ChatMessage(thread_id=t.id, role="user", text=stored,
                      status="pending_approval" if reasons else "running",
                      approval_reasons=json.dumps(reasons) if reasons else None, created_at=now)
    s.add(msg)
    t.last_activity_at = now
    s.commit()
    if not reasons:
        if await d.start_turn(msg.id) is None:
            msg.status="failed";s.commit()
            raise HTTPException(409,"This workspace is busy with a project run, or the turn could not be claimed. Retry after it finishes.")
        s.refresh(msg)
    return _msg_dict(msg)


@router.post("/messages/{message_id}/approve")
async def approve_message(message_id: int, request: Request, s: Session = Depends(get_session)):
    d = _dispatcher(request)
    msg = s.get(ChatMessage, message_id)
    if msg is None or msg.status != "pending_approval":
        raise HTTPException(status_code=409, detail="That message is not waiting for approval.")
    if d.thread_busy(msg.thread_id):
        raise HTTPException(status_code=409, detail="The agent is still answering another message.")
    msg.approved_at = _now()
    s.commit()
    if await d.start_turn(msg.id) is None:
        msg.status="failed";s.commit()
        raise HTTPException(409,"This workspace is busy with a project run, or the turn could not be claimed. Retry after it finishes.")
    s.refresh(msg)
    return _msg_dict(msg)


@router.post("/messages/{message_id}/reject")
def reject_message(message_id: int, s: Session = Depends(get_session)):
    msg = s.get(ChatMessage, message_id)
    if msg is None or msg.status != "pending_approval":
        raise HTTPException(status_code=409, detail="That message is not waiting for approval.")
    msg.status = "cancelled"
    s.commit()
    return _msg_dict(msg)


@router.post("/threads/{thread_id}/stop")
async def stop_thread(thread_id: int, request: Request, s: Session = Depends(get_session)):
    d = _dispatcher(request)
    msg = s.execute(select(ChatMessage).where(ChatMessage.thread_id == thread_id, ChatMessage.status == "running")
                    .order_by(ChatMessage.id.desc())).scalars().first()
    if msg is None or msg.run_id is None or not await d.cancel(msg.run_id):
        raise HTTPException(status_code=409, detail="Nothing is running in this thread.")
    return {"stopped": msg.run_id}


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: int, request: Request, s: Session = Depends(get_session)):
    t = _thread(s, thread_id)
    d = request.app.state.dispatcher
    if d and d.thread_busy(t.id):
        raise HTTPException(status_code=409, detail="Stop the running turn before deleting the thread.")
    log_paths = s.execute(select(Run.log_path).where(Run.thread_id == thread_id)).scalars().all()
    from usage import retain_run_accounting
    retain_run_accounting(s, s.scalars(select(Run).where(Run.thread_id == thread_id)).all())
    s.delete(t)
    s.commit()
    remove_run_logs(log_paths)
