"""The standard envelope every coordinator-submitted story carries, so work can be filtered and measured.

A *job* is one approved plan revision (project p, revision r): its stories are the job's work. The envelope adds controlled fields to
each story, stored as columns (not only free tags) so they can be filtered and aggregated:

  kind          what sort of work it is
  size          rough size class, with a defensible estimate_minutes beside it
  risk          how costly a wrong or failed result would be
  area          the component or topic, short and lowercase
  route_tier    free | subscription | api | human, derived from the route (never trusted from a model)
  route_reason  one sentence: why this agent and model, and why a free route is or is not enough

The server derives the tier and the job; a model supplies kind, size, risk, area, estimate and reason, and a plan is refused at
approval when a story lacks them. Cards made by hand keep working without an envelope and show as untagged in telemetry.
"""
from __future__ import annotations

import re

KINDS = ("research", "plan", "implement", "review", "test", "docs", "ops", "triage")
SIZES = ("xs", "s", "m", "l", "xl")
RISKS = ("low", "medium", "high")
TIERS = ("free", "subscription", "api", "human")
SIZE_HINT_MINUTES = {"xs": 15, "s": 45, "m": 120, "l": 300, "xl": 600}
AREA_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,119}$")   # an approved user's email or short name
SUBSCRIPTION_AGENTS = ("claude", "codex", "grok")
REQUIRED_FOR_A_PLANNED_STORY = ("kind", "size", "risk", "estimate_minutes", "route_reason")


def tier_for(assignee_type: str | None, agent: str | None, model: str | None) -> str:
    """free, subscription, api or human, from what the card will actually run."""
    if assignee_type == "human" or agent in (None, ""):
        return "human"
    if agent in SUBSCRIPTION_AGENTS:
        return "subscription"
    name = (model or "").strip()
    return "free" if not name or name == "openrouter/free" or name.endswith(":free") else "api"


def problems(fields: dict) -> list[str]:
    """Sentences for any envelope value that is present but not allowed. Absent values are fine here."""
    out = []
    for key, allowed in (("kind", KINDS), ("size", SIZES), ("risk", RISKS), ("route_tier", TIERS)):
        value = fields.get(key)
        if value not in (None, "") and value not in allowed:
            out.append(f"{key} must be one of {', '.join(allowed)}")
    area = fields.get("area")
    if area not in (None, "") and not AREA_RE.match(str(area)):
        out.append("area must be 1-40 lowercase letters, digits, dot, dash or underscore")
    user = fields.get("assignee_user")
    if user not in (None, "") and not USER_RE.match(str(user)):
        out.append("assignee_user must be an email or short name (letters, digits, . _ @ + -)")
    reason = fields.get("route_reason")
    if reason not in (None, "") and len(str(reason)) > 300:
        out.append("route_reason must be at most 300 characters")
    return out


def story_problems(nodes: list[dict]) -> list[str]:
    """What a plan is missing before it can be approved: every story needs kind, size, risk, an estimate and a route reason."""
    missing = []
    for node in nodes:
        if node.get("kind") != "story":
            continue
        # `kind` on a plan node is phase|story; the envelope's work kind is carried as work_kind
        gaps = [name for name in REQUIRED_FOR_A_PLANNED_STORY
                if not node.get("work_kind" if name == "kind" else name)]
        if gaps:
            missing.append(f"{node.get('key')}: {', '.join('work_kind' if g == 'kind' else g for g in gaps)}")
    return missing


def standard_tags(job: str | None, work_kind: str | None, size: str | None, risk: str | None, tier: str | None, area: str | None) -> list[str]:
    tags = []
    for prefix, value in (("job", job), ("kind", work_kind), ("size", size), ("risk", risk), ("tier", tier), ("area", area)):
        if value:
            tags.append(f"{prefix}:{value}"[:32])
    return tags
