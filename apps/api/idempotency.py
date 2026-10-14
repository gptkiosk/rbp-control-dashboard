"""Durable, fail-closed timeout retry admission shared by MCD and RCD."""
from sqlalchemy import select

from models import Run, RunEvent


def refuse_timeout_retry(session, card, now) -> bool:
    """Called under the dispatcher's claim transaction, before creating another Run.

    A timeout does not prove remote work stopped or that partial edits can be
    repeated. Neither platform has a verified resume protocol for that outcome.
    Retain the original identity/result and require review instead of relaunching.
    MCD's legacy identity is its existing Run ID; RCD also stores an execution key.
    """
    prior = session.scalar(select(Run).where(Run.card_id == card.id)
                           .order_by(Run.id.desc()).limit(1))
    if prior is None or prior.stage != "timeout":
        return False
    key = getattr(prior, "idempotency_key", None) or f"mcd:run:{prior.id}"
    card.column, card.updated_at = "failed", now
    if hasattr(card, "idempotency_key"):
        card.idempotency_key, card.retry_after = key, None
    message = (f"RETRY_REQUIRES_REVIEW: original run #{prior.id} ({key}) timed out; "
               "safe resume is unavailable. No new attempt was dispatched. "
               "Review partial work and upstream execution state before authorizing new work.")
    if not session.scalar(select(RunEvent.id).where(
            RunEvent.run_id == prior.id, RunEvent.kind == "note", RunEvent.text == message).limit(1)):
        session.add(RunEvent(run_id=prior.id, ts=now, kind="note", text=message))
    return True
