"""How well did the coordinator plan? A deterministic scorer for a plan, plus the signals that say how it went afterwards.

The scorer checks the plan, never the model: schema, the standard envelope, estimates that fit the size class, acceptance criteria that can be
checked, bounded scope, dependencies that exist and do not loop, routes with reasons, the standards' floors, a human review where the work is high
risk, and nothing too big to run. A brief can add expectations (areas, kinds, a minimum number of stories). Every check is pass or fail with a
plain detail, and the score is the share of applicable checks that passed.

Live signals (how many of the plan's edits a person made, first-pass completion, estimate error) are computed elsewhere from records the app
already keeps; the signature helpers here let a returned plan be compared with the approved one without storing either whole.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import ValidationError

import job_envelope
import standards
from project_schemas import Node
from settings import REPO_ROOT

BRIEFS_FILE = Path(REPO_ROOT) / "packs" / "evaluation" / "briefs.json"
SIZE_FACTOR = 3.0                       # an estimate within a factor of three of the size class is sane
MIN_ACCEPTANCE_CHARS = 30
MIN_SCOPE_CHARS = 15
CHECKABLE = re.compile(r"\b(tests?|pass(es|ed)?|fail(s|ed)?|returns?|shows?|displays?|exists?|verif(y|ied)|confirm(s|ed)?|no more than|at least|exactly|\d+|command|output|error|log|receipt|diff|screenshot|passes|recorded|published|nonempty|non-empty|matches?|maps?|linked|documented|\d+(?:px|ms|em|rem|s))\b", re.I)
SIGNATURE_FIELDS = ("title", "description", "scope", "acceptance", "assignee", "model", "risk", "size", "estimate_minutes", "depends_on", "work_kind", "area", "mode", "host_action", "media_stage", "media_batch", "verification_stage")


def briefs() -> list[dict]:
    try:
        return json.loads(BRIEFS_FILE.read_text("utf-8")).get("briefs", [])
    except (OSError, ValueError):
        return []


def _stories(nodes):
    return [n for n in nodes if n.get("kind", "story") == "story"]


def _check(cid, label, ok, detail="", applicable=True):
    return {"id": cid, "label": label, "passed": bool(ok), "detail": detail, "applicable": applicable}


def _cycle(stories) -> bool:
    deps = {n["key"]: list(n.get("depends_on") or []) for n in stories}
    state: dict[str, int] = {}

    def visit(key) -> bool:
        if state.get(key) == 1:
            return True
        if state.get(key) == 2 or key not in deps:
            return False
        state[key] = 1
        found = any(visit(d) for d in deps[key])
        state[key] = 2
        return found
    return any(visit(k) for k in deps)


def score_plan(nodes: list[dict], expect: dict | None = None, found: dict | None = None, tier_of=None) -> dict:
    """Score a plan (a list of node dicts). ``found`` is the standards that apply (see standards.resolve); ``tier_of(node)`` gives a route tier."""
    expect = expect or {}
    checks = []
    bad = []
    for n in nodes:
        try:
            Node.model_validate(n)
        except (ValidationError, TypeError):
            bad.append(str(n.get("key", "?")) if isinstance(n, dict) else "?")
    checks.append(_check("schema", "Every node fits the plan schema", not bad, f"does not fit: {', '.join(bad[:5])}" if bad else ""))
    if bad:
        return _finish(checks)            # nothing else can be judged on a plan that does not parse
    stories = _stories(nodes)
    keys = [n["key"] for n in nodes]
    checks.append(_check("keys", "Node keys are unique and the plan has stories", len(set(keys)) == len(keys) and bool(stories), "" if stories else "no stories"))
    gaps = job_envelope.story_problems(nodes)
    checks.append(_check("envelope", "Every story has kind, size, risk, estimate and a route reason", not gaps, "; ".join(gaps[:4])))
    off = []
    for n in stories:
        hint, est = job_envelope.SIZE_HINT_MINUTES.get(n.get("size") or ""), n.get("estimate_minutes")
        if hint and est and not (hint / SIZE_FACTOR <= est <= hint * SIZE_FACTOR):
            off.append(f"{n['key']} ({n.get('size')} but {est} min)")
    checks.append(_check("estimates", "Estimates fit the size class", not off, "; ".join(off[:4])))
    vague = [n["key"] for n in stories if len((n.get("acceptance") or "").strip()) < MIN_ACCEPTANCE_CHARS or not CHECKABLE.search(n.get("acceptance") or "")]
    checks.append(_check("acceptance", "Acceptance criteria name observable evidence", not vague, f"vague: {', '.join(vague[:5])}" if vague else ""))
    unbounded = [n["key"] for n in stories if len((n.get("scope") or "").strip()) < MIN_SCOPE_CHARS]
    checks.append(_check("scope", "Every story has a bounded scope", not unbounded, f"no scope: {', '.join(unbounded[:5])}" if unbounded else ""))
    story_keys = {n["key"] for n in stories}
    dangling = [f"{n['key']}->{d}" for n in stories for d in (n.get("depends_on") or []) if d not in story_keys or d == n["key"]]
    checks.append(_check("dependencies", "Dependencies exist and do not loop", not dangling and not _cycle(stories),
                         ("loop in the plan" if not dangling and _cycle(stories) else "; ".join(dangling[:4]))))
    unreasoned = [n["key"] for n in stories if n.get("assignee") != "human" and not (n.get("route_reason") or "").strip()]
    checks.append(_check("routes", "Every agent route has a reason", not unreasoned, f"no reason: {', '.join(unreasoned[:5])}" if unreasoned else ""))
    big = [n["key"] for n in stories if n.get("size") == "xl"]
    checks.append(_check("size", "Nothing is too big to run (no xl stories)", not big, f"split: {', '.join(big[:5])}" if big else ""))
    empty = [n["key"] for n in nodes if n.get("kind") == "phase" and not any(c.get("parent") == n["key"] for c in nodes)]
    checks.append(_check("phases", "Every phase has stories", not empty, f"empty: {', '.join(empty[:5])}" if empty else "", applicable=any(n.get("kind") == "phase" for n in nodes)))
    high = [n for n in stories if n.get("risk") == "high"]
    reviewed = any(n.get("assignee") == "human" or n.get("work_kind") == "review" for n in stories)
    checks.append(_check("review", "High-risk work has a human or review story", not high or reviewed, "no review story" if high and not reviewed else "", applicable=bool(high)))
    if found and found.get("state") == "ok" and tier_of is not None:
        broken = standards.floor_problems(found, nodes, tier_of)
        checks.append(_check("standards", "The plan respects the standards' risk floors and routes", not broken, "; ".join(broken[:3])))
    # What this brief wanted
    if expect:
        if "min_stories" in expect:
            checks.append(_check("brief_size", f"At least {expect['min_stories']} stories", len(stories) >= expect["min_stories"], f"{len(stories)} stories"))
        if expect.get("needs_human_review"):
            checks.append(_check("brief_review", "Includes a human decision or review", reviewed, "" if reviewed else "none"))
        want_areas = expect.get("areas") or []
        if want_areas:
            used = {n.get("area") for n in stories}
            checks.append(_check("brief_areas", "Uses the standards areas this work falls under", all(a in used for a in want_areas), f"missing: {', '.join(a for a in want_areas if a not in used)}"))
        want_kinds = expect.get("kinds") or []
        if want_kinds:
            used = {n.get("work_kind") for n in stories}
            checks.append(_check("brief_kinds", "Includes the kinds of work it needs", all(k in used for k in want_kinds), f"missing: {', '.join(k for k in want_kinds if k not in used)}"))
        if expect.get("no_free_for_high") and tier_of is not None:
            wrong = [n["key"] for n in high if tier_of(n) == "free"]
            checks.append(_check("brief_free_high", "No high-risk story on a free-only route", not wrong, f"free: {', '.join(wrong[:5])}" if wrong else ""))
    return _finish(checks)


def _finish(checks: list[dict]) -> dict:
    counted = [c for c in checks if c["applicable"]]
    passed = sum(1 for c in counted if c["passed"])
    return {"score": round(passed / len(counted), 3) if counted else 0.0, "passed": passed, "total": len(counted), "failed": [c["id"] for c in counted if not c["passed"]], "checks": checks}


# ------------------------------------------------------------------------------------------------ comparing a returned plan with the approved one
def signatures(nodes: list[dict]) -> dict[str, str]:
    """A short fingerprint per node, so a returned plan can be compared with the approved one without keeping either whole."""
    out = {}
    for n in nodes:
        body = {k: n.get(k) for k in SIGNATURE_FIELDS}
        out[n["key"]] = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return out


def edits(returned: dict[str, str], approved: dict[str, str]) -> dict:
    """What a person changed between the coordinator's plan and the approved one."""
    added = sorted(set(approved) - set(returned))
    removed = sorted(set(returned) - set(approved))
    changed = sorted(k for k in set(returned) & set(approved) if returned[k] != approved[k])
    return {"added": len(added), "removed": len(removed), "changed": len(changed), "total": len(added) + len(removed) + len(changed), "nodes_returned": len(returned)}
