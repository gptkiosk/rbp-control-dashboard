"""Card rules: creation, moves between columns, approval, and edits.

Column rules:
  running   only the dispatcher moves a card in; the operator cancels instead of dragging out
  queued    a card that needs approval and is not approved goes to Review instead
  review    waiting for the operator's approval
  backlog / done / failed   free moves for any card that is not running

Approval is tied to the card's content: editing the prompt, mode, working directory, agent or
model clears the approval and re-runs the rules. An approval is a single-use grant bound to the
card's route pin, a nonce and an expiry (approval.py); each new execution needs a new approval.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import approval
import job_envelope
from agents import REGISTRY
from models import COLUMNS, Card, CardDependency

APPROVAL_FIELDS = {"body", "mode", "working_dir", "agent", "model", "agent_target", "assignee_type"}
EDITABLE_FIELDS = APPROVAL_FIELDS | {"title", "timeout_s", "idle_timeout_s", "max_attempts", "retry_backoff_s", "budget_usd", "priority", "due_date",
                                     "estimate_minutes", "tags", "acceptance", "kind", "size", "risk", "area", "route_reason", "assignee_user"}
PRIORITIES = ("urgent", "high", "normal", "low")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9 &._:-]{0,31}$")   # ":" allows namespaced tags such as kind:implement
MAX_TAGS = 10


def normalize_tags(tags) -> list[str]:
    """Lowercase, trimmed, de-duplicated tags in input order. Raises 422 on a bad tag."""
    out: list[str] = []
    for raw in tags or []:
        tag = " ".join(str(raw).strip().lower().split())
        if not tag:
            continue
        if not TAG_RE.match(tag):
            raise HTTPException(status_code=422, detail=f"Tag not allowed: {raw!r} (letters, digits, "
                                "space, & . _ -, max 32)")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_TAGS} tags per task")
    return out


def _now() -> int:
    return int(time.time())


def _next_position(s: Session, column: str) -> float:
    current = s.execute(select(func.max(Card.position)).where(Card.column == column)).scalar()
    return (current or 0.0) + 1.0


def _apply_rules(card: Card, roots) -> None:
    if card.assignee_type == "human":
        # The operator's own task: nothing is dispatched, so there is nothing to approve.
        card.agent = card.agent_target = card.model = card.working_dir = None
        card.needs_approval, card.approval_reasons, card.approved_at = False, None, None
        return
    if not card.agent or card.agent not in REGISTRY:
        raise HTTPException(status_code=422, detail="An agent task needs a known agent")
    if not (card.body or "").strip():
        raise HTTPException(status_code=422, detail="An agent task needs a prompt")
    if not card.working_dir:
        raise HTTPException(status_code=422, detail="An agent task needs a working directory")
    real = approval.resolve_workdir(card.working_dir, roots)
    if real is None:
        raise HTTPException(status_code=422, detail="Working directory must be an existing folder inside "
                            + ", ".join(str(r) for r in roots))
    card.working_dir = str(real)
    reasons = approval.reasons_for(card.body, card.mode, approval.current_branch(real))
    card.needs_approval = bool(reasons)
    card.approval_reasons = json.dumps(reasons) if reasons else None
    card.approved_at = None
    if reasons:
        approval.issue_challenge(card)


def validate_fields(data: dict) -> None:
    if "assignee_type" in data and data["assignee_type"] not in ("agent", "human"):
        raise HTTPException(status_code=422, detail="Assignee must be agent or human")
    if data.get("agent") is not None and data["agent"] not in REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unknown agent: {data['agent']}")
    if "priority" in data and data["priority"] not in PRIORITIES:
        raise HTTPException(status_code=422, detail="Priority must be urgent, high, normal or low")
    if data.get("due_date"):
        try:
            date.fromisoformat(data["due_date"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Due date must be YYYY-MM-DD") from exc
    envelope = job_envelope.problems(data)
    if envelope:
        raise HTTPException(status_code=422, detail="; ".join(envelope))
    if data.get("estimate_minutes") is not None and not 1 <= int(data["estimate_minutes"]) <= 100_000:
        raise HTTPException(status_code=422, detail="Estimate must be 1 to 100000 minutes")
    if "mode" in data and data["mode"] not in ("read", "edit"):
        raise HTTPException(status_code=422, detail="Mode must be read or edit")
    if data.get("idle_timeout_s") is not None and not 1 <= int(data["idle_timeout_s"]) <= 6 * 3600:
        raise HTTPException(status_code=422, detail="Idle timeout must be 1 to 21600 seconds")
    if data.get("max_attempts") is not None and not 1 <= int(data["max_attempts"]) <= 10:
        raise HTTPException(status_code=422, detail="Max attempts must be 1 to 10")
    if data.get("retry_backoff_s") is not None and not 0 <= int(data["retry_backoff_s"]) <= 3600:
        raise HTTPException(status_code=422, detail="Retry backoff must be 0 to 3600 seconds")
    if "title" in data and not str(data["title"]).strip():
        raise HTTPException(status_code=422, detail="Title is required")


def create(s: Session, data: dict, settings, created_by: str = "operator") -> Card:
    validate_fields(data)
    now = _now()
    card = Card(
        title=data["title"].strip(), body=data.get("body") or "",
        assignee_type=data.get("assignee_type") or "agent", agent=data.get("agent"),
        agent_target=data.get("agent_target"), model=data.get("model") or None,
        mode=data.get("mode") or "read", working_dir=data.get("working_dir"),
        column="backlog", position=_next_position(s, "backlog"),
        timeout_s=int(data.get("timeout_s") or settings.default_timeout_s),
        idle_timeout_s=data.get("idle_timeout_s"), max_attempts=int(data.get("max_attempts") or 1),
        retry_backoff_s=int(data.get("retry_backoff_s") or 0),
        budget_usd=data.get("budget_usd"), created_by=created_by,
        priority=data.get("priority") or "normal", due_date=data.get("due_date") or None,
        estimate_minutes=data.get("estimate_minutes"),
        tags=json.dumps(normalize_tags(data.get("tags"))) if data.get("tags") else None,
        acceptance=data.get("acceptance") or None,
        assignee_user=data.get("assignee_user") or None,
        kind=data.get("kind") or None, size=data.get("size") or None, risk=data.get("risk") or None,
        area=data.get("area") or None, route_reason=data.get("route_reason") or None,
        route_tier=job_envelope.tier_for(data.get("assignee_type") or "agent", data.get("agent"), data.get("model")),
        created_at=now, updated_at=now, needs_approval=False,
    )
    if card.assignee_user and card.assignee_type != "human":
        raise HTTPException(status_code=422, detail="Only a human task is assigned to a person; an agent task is assigned through its agent and model.")
    _apply_rules(card, settings.workdir_roots)
    s.add(card)
    s.flush()
    for dep_id in data.get("depends_on") or []:
        add_dependency(s, card, int(dep_id))
    return card


def edit(s: Session, card: Card, data: dict, settings) -> Card:
    import projects
    projects.protect(s, card)
    if card.column == "running":
        raise HTTPException(status_code=409, detail="A running card cannot be edited. Cancel it first.")
    validate_fields(data)
    if "tags" in data:
        data = {**data, "tags": json.dumps(normalize_tags(data["tags"])) if data["tags"] else None}
    changed = {k for k in data if k in EDITABLE_FIELDS and getattr(card, k) != data[k]}
    for key in changed:
        value = data[key]
        if key in ("model", "due_date", "acceptance", "assignee_user") and not value:
            value = None
        setattr(card, key, value)
    if card.assignee_user and card.assignee_type != "human":
        raise HTTPException(status_code=422, detail="Only a human task is assigned to a person; an agent task is assigned through its agent and model.")
    if changed & APPROVAL_FIELDS:
        _apply_rules(card, settings.workdir_roots)
        if card.column in ("queued", "review"):
            card.column = "review" if card.needs_approval else "queued"
    card.updated_at = _now()
    return card


def move(s: Session, card: Card, to: str, position: float | None) -> Card:
    import projects
    projects.protect(s, card)
    if to not in COLUMNS:
        raise HTTPException(status_code=422, detail=f"Unknown column: {to}")
    if card.column == "running" and card.assignee_type != "human":
        raise HTTPException(status_code=409, detail="A running card cannot be moved. Cancel it first.")
    human = card.assignee_type == "human"
    if to == "running" and not human:
        raise HTTPException(status_code=409, detail="Only the dispatcher starts runs. Move the card to Queued.")
    if to == "queued" and not human and card.needs_approval:
        # Project stories are authorized by their approved project revision, not a card grant.
        problem = (("not approved" if card.approved_at is None else None) if projects.binding(s, card.id)
                   else approval.grant_problem(card, _now(), card.idempotency_key))
        if problem:
            if card.approved_at is not None:  # a used or stale grant never re-arms on a move
                approval.audit(card, _now(), "dispatch_refused", problem)
                approval.issue_challenge(card)
            to = "review"
    card.column = to
    card.position = position if position is not None else _next_position(s, to)
    card.updated_at = _now()
    return card


# ----------------------------------------------------------------------------- dependencies


def dependency_ids(s: Session, card_id: int) -> list[int]:
    return list(s.execute(select(CardDependency.depends_on_id).where(CardDependency.card_id == card_id)
                          .order_by(CardDependency.depends_on_id)).scalars())


def _reaches(s: Session, start: int, target: int) -> bool:
    """True when `target` is reachable from `start` by following depends-on edges."""
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(dependency_ids(s, node))
    return False


def add_dependency(s: Session, card: Card, depends_on_id: int) -> None:
    import projects
    projects.protect(s, card)
    if depends_on_id == card.id:
        raise HTTPException(status_code=422, detail="A task cannot depend on itself")
    if s.get(Card, depends_on_id) is None:
        raise HTTPException(status_code=422, detail=f"Task #{depends_on_id} does not exist")
    if s.get(CardDependency, (card.id, depends_on_id)) is not None:
        return
    if _reaches(s, depends_on_id, card.id):
        raise HTTPException(status_code=422, detail=f"That would create a cycle: #{depends_on_id} already "
                            f"depends on #{card.id}")
    s.add(CardDependency(card_id=card.id, depends_on_id=depends_on_id))
    card.updated_at = _now()


def remove_dependency(s: Session, card: Card, depends_on_id: int) -> None:
    import projects
    projects.protect(s, card)
    dep = s.get(CardDependency, (card.id, depends_on_id))
    if dep is None:
        raise HTTPException(status_code=404, detail="No such dependency")
    s.delete(dep)
    card.updated_at = _now()


def approve(card: Card, challenge: str | None, pin: str | None, ttl_s: int) -> Card:
    """Approve the exact card version the operator was shown, once.

    A refused request raises approval.ApprovalRefused after recording it on the card; the
    caller commits that audit entry before returning 409.
    """
    if card.assignee_type == "human":
        raise HTTPException(status_code=409, detail="Human tasks do not need approval.")
    if card.column == "running":
        raise HTTPException(status_code=409, detail="Card is already running.")
    if not card.needs_approval:
        raise HTTPException(status_code=409, detail="This card does not need approval.")
    approval.grant(card, challenge, pin, _now(), ttl_s)
    if card.column in ("review", "backlog"):
        card.column = "queued"
    card.updated_at = _now()
    return card
