"""Approval rules for cards (operator decision 4, 2026-10-09).

A card needs the operator's approval before it can run when it:
  - edits a git repo whose current branch is main or master, or
  - asks for something that leaves this Mac: pushing, merging, deploying, publishing, or
    contacting a person (email, text, call, posting to a channel).
Working directories outside the allowed roots are rejected outright (not approvable).

The prompt check is a keyword screen, not a guarantee; agent sandboxes and blocked tools are
the second line of defence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import subprocess
import time
from pathlib import Path
from adapter_contract import AdapterError

logger = logging.getLogger("mac_control.approval")


def checkpoint_request(request: dict, capabilities: dict, heartbeat: dict) -> dict:
    """Only an exited, durable runtime can enter the Pi decision gate.

    The adapter owns the opaque checkpoint and the completed-tool journal. RCD never
    reconstructs a prompt or starts a fresh execution to emulate a resume.
    """
    if (request.get("resume_mode") != "checkpoint"
            or "checkpoint" not in capabilities.get("suspend_modes", [])
            or heartbeat.get("alive") is not False or heartbeat.get("pid") is not None):
        raise AdapterError("RUNTIME_INCOMPATIBLE", "Human decisions require a durable checkpoint and an exited runtime")
    checkpoint = request.get("checkpoint") or {}
    if not (checkpoint.get("state_ref") or checkpoint.get("session_id")):
        raise AdapterError("RESULT_INVALID", "Approval has no durable checkpoint reference")
    if not request.get("approval_id") or not str(request.get("question") or "").strip():
        raise AdapterError("RESULT_INVALID", "Approval requires an identity and question")
    # A decision cannot authorize a new budget or mutate the approved execution scope.
    if request.get("kind") == "budget_increase":
        raise AdapterError("BUDGET_EXCEEDED", "Budget changes require a separate project scope review")
    return request


def validate_decision(request: dict, decision: dict) -> None:
    if decision.get("approval_id") != request.get("approval_id"):
        raise AdapterError("DECISION_CONFLICT", "The displayed approval is no longer current")
    if decision.get("verdict") not in {"approve", "answer", "reject"}:
        raise AdapterError("INVALID_TRANSITION", "Unknown decision verdict")
    if decision["verdict"] == "reject":
        return  # refusing is always allowed, even after expiry
    expires_at = request.get("expires_at")
    if expires_at is not None and int(time.time()) >= int(expires_at):
        raise AdapterError("DECISION_CONFLICT", "This approval expired. Reject it and review a new run.")
    if decision["verdict"] == "answer" and not (decision.get("answer_text") or decision.get("option_id")):
        raise AdapterError("INVALID_TRANSITION", "A human answer is required")
    options = request.get("options", [])
    if decision.get("option_id") and decision["option_id"] not in {o["id"] for o in options}:
        raise AdapterError("DECISION_CONFLICT", "Choose an option from the displayed decision")
    output = request.get("proposed_output")
    if output and decision.get("approved_output_sha256") != output["sha256"]:
        raise AdapterError("DECISION_CONFLICT", "Review the current proposed output before approving")

OUTWARD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pushes or merges code", re.compile(r"\b(git\s+push|push\s+(to|the|this|it)|merge\s+(to|into|the|this|pr)|force[- ]push)\b", re.I)),
    ("deploys or releases", re.compile(r"\b(deploy|release|roll\s+(to\s+)?prod|terraform\s+apply|publish)\w*\b", re.I)),
    ("contacts a person", re.compile(r"\b(send\s+(an?\s+)?(email|e-mail|text|sms|message|invite)|e-?mail\s+(to|the)|text\s+(him|her|them|me)|call\s+(him|her|them|me|the)|post\s+(to|on|in)\s+\w+|tweet|reply\s+to\s+(the\s+)?(email|customer|user))\b", re.I)),
)

PROTECTED_BRANCHES = {"main", "master"}


def resolve_workdir(path: str, roots: tuple[Path, ...]) -> Path | None:
    """The real path when it is an existing directory inside an allowed root, else None."""
    try:
        real = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not real.is_dir():
        return None
    for root in roots:
        try:
            root_real = root.expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if real == root_real or root_real in real.parents:
            return real
    return None


def current_branch(workdir: Path) -> str | None:
    """The checked-out branch, or None outside a repo or on a detached HEAD.

    `symbolic-ref` works in a new repo before its first commit, where `rev-parse
    --abbrev-ref HEAD` fails; that gap would have let edits to a fresh main branch skip approval.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(workdir), "symbolic-ref", "-q", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def reasons_for(prompt: str, mode: str, branch: str | None) -> list[str]:
    reasons: list[str] = []
    if mode == "edit" and branch in PROTECTED_BRANCHES:
        reasons.append(f"edits a repo on its {branch} branch")
    text = prompt or ""
    for label, pattern in OUTWARD_PATTERNS:
        if pattern.search(text):
            reasons.append(f"prompt {label}")
    return reasons


# ----------------------------------------------------------------------------- approval grants
#
# A standalone card's approval is a single-use grant, kept as JSON in `card.approval_grant`:
#   pending   {"challenge": <nonce>}                 issued when the card needs approval
#   approved  {"nonce", "card_id", "pin", "approved_at", "expires_at", "run_id": None}
#   used      run_id set when the dispatcher claims it; it never authorizes another execution
# The operator's approve request must echo the challenge and the route pin it was shown, so a
# replayed request, or one made against a card whose route or content has since changed, is
# refused. The dispatcher checks the grant again at claim time. Refusals are kept on the card.
# Project stories are authorized by their approved, revision-bound project manifest instead.

AUDIT_KEEP = 20
PIN_FIELDS = ("assignee_type", "agent", "agent_target", "model", "mode", "working_dir", "body")


def route_pin(card) -> str:
    """Hash of the card identity and everything its approval covers."""
    fields = {"card_id": card.id, **{k: getattr(card, k) or None for k in PIN_FIELDS}}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def load_grant(card) -> dict:
    try:
        grant = json.loads(card.approval_grant or "{}")
    except ValueError:
        return {}
    return grant if isinstance(grant, dict) else {}


def _store(card, grant: dict) -> None:
    grant["audit"] = grant.get("audit", [])[-AUDIT_KEEP:]
    card.approval_grant = json.dumps(grant, sort_keys=True)


def audit(card, now: int, event: str, reason: str) -> None:
    grant = load_grant(card)
    grant.setdefault("audit", []).append({"ts": now, "event": event, "reason": reason})
    _store(card, grant)
    logger.warning("card %s approval %s: %s", card.id, event, reason)


def issue_challenge(card) -> str:
    """Start a fresh approval: any earlier grant is retired; the audit trail is kept."""
    old = load_grant(card)
    grant = {"challenge": secrets.token_urlsafe(18), "audit": old.get("audit", [])}
    if old.get("nonce"):
        grant["last"] = {k: old.get(k) for k in ("nonce", "pin", "run_id", "approved_at")}
    _store(card, grant)
    card.approved_at = None
    return grant["challenge"]


def challenge(card) -> str | None:
    return load_grant(card).get("challenge") if card.needs_approval and card.approved_at is None else None


class ApprovalRefused(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def grant(card, shown_challenge: str | None, shown_pin: str | None, now: int, ttl_s: int) -> None:
    """Record the operator's approval of exactly the card version they were shown.

    Raises ApprovalRefused (already audited on the card) for a stale, replayed or swapped request.
    """
    current = load_grant(card)
    if card.approved_at is None and not current.get("challenge"):
        # A card from before approval grants: issue its first challenge; the next view shows it.
        audit(card, now, "refused", "no approval challenge had been issued")
        issue_challenge(card)
        raise ApprovalRefused("This task needs a fresh review before approval. Refresh the task and review it again.")
    if not shown_challenge or not current.get("challenge") or not hmac.compare_digest(
            str(shown_challenge), str(current["challenge"])):
        audit(card, now, "refused", "stale or replayed approval request")
        raise ApprovalRefused("This approval request is stale or was already used. Refresh the task and review it again.")
    if not shown_pin or not hmac.compare_digest(str(shown_pin), route_pin(card)):
        audit(card, now, "refused", "route or content changed since it was shown")
        raise ApprovalRefused("The task's route or content changed since you reviewed it. Refresh and review it again.")
    approved = {"nonce": current["challenge"], "card_id": card.id, "pin": route_pin(card),
                "approved_at": now, "expires_at": now + ttl_s, "run_id": None,
                "audit": current.get("audit", [])}
    approved["audit"].append({"ts": now, "event": "approved", "reason": f"pin {approved['pin'][:12]}"})
    _store(card, approved)
    card.approved_at = now


def grant_problem(card, now: int, execution_key: str | None = None) -> str | None:
    """Why the card's approval cannot authorize a dispatch now, or None when it can.

    `execution_key` lets an interrupted or automatically retried attempt of the SAME execution
    reuse its grant; a new execution always needs a new approval.
    """
    g = load_grant(card)
    if card.approved_at is None or not g.get("nonce"):
        return "no current approval grant"
    if g.get("card_id") != card.id:
        return "approval belongs to another task"
    if g.get("run_id") is not None and not (execution_key and g.get("execution_key") == execution_key):
        return f"approval was already used by run #{g['run_id']}"
    if not hmac.compare_digest(str(g.get("pin") or ""), route_pin(card)):
        return "route or content changed since approval"
    if g.get("run_id") is None and now >= int(g.get("expires_at") or 0):
        return "approval expired before dispatch"
    return None


def consume(card, run_id: int, now: int, execution_key: str | None = None) -> str:
    """Bind the grant to the run that uses it. Returns a short note for the run's events."""
    g = load_grant(card)
    first = g.get("run_id") is None
    if first:
        g["run_id"], g["used_at"] = run_id, now
        if execution_key:
            g["execution_key"] = execution_key
        g.setdefault("audit", []).append({"ts": now, "event": "used", "reason": f"run #{run_id}"})
        _store(card, g)
    return (f"operator approval {g['nonce'][:8]} (route pin {g['pin'][:12]}) "
            + ("bound to this run" if first else f"of run #{g['run_id']} reused for the same execution"))


def revoke(card, now: int, reason: str) -> None:
    """Refuse a dispatch: audit it, send the card back to Review and require a new approval."""
    audit(card, now, "dispatch_refused", reason)
    issue_challenge(card)
    card.column = "review"
    card.updated_at = now


# ----------------------------------------------------------------------------- checkpoint decisions


def decision_pin(run, card) -> str:
    """The route a paused run was approved to resume on: run, execution, agent and model."""
    fields = {"run_id": run.id, "card_id": run.card_id, "execution_key": run.idempotency_key,
              "agent": run.agent, "model": run.model_requested or None,
              "card_agent": card.agent if card else None, "card_model": (card.model or None) if card else None,
              "card_target": (card.agent_target or None) if card else None}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
