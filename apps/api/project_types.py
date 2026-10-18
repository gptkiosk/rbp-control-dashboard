"""Project types: what each kind of project we deliver needs, where it fails, and where a person must look and sign off.

A type is a small data file (packs/project-types/<id>.json, or the operator's own copy in <data>/project-types/ which wins) holding planner text, known
failure points, the human sign-offs and visual checks, and a few named checks that run over a proposed plan. Checks only inspect the plan's stories;
they warn and never block, and they never run model output. Failure points are meant to grow: when a project fails for a reason that could have been
planned around, add it to the type so the next plan avoids it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CHECK_KINDS = {"has_story", "order", "not_agent_for"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_BYTES = 40_000


def _dirs(settings):
    from settings import REPO_ROOT
    mine = Path(settings.data_dir) / "project-types" if settings is not None else None
    return [d for d in (mine, Path(REPO_ROOT) / "packs" / "project-types") if d is not None]


def _valid(t):
    """A template is usable only if every part has the expected shape and every pattern compiles; a broken one is ignored, never half-used."""
    try:
        if not ID_RE.fullmatch(t["id"]) or not isinstance(t["label"], str) or not isinstance(t["summary"], str) or not isinstance(t["planner_text"], str):
            return False
        for key in ("suggest", "keys", "guides", "failure_points", "human_signoffs"):
            if not isinstance(t.get(key, []), list) or not all(isinstance(x, str) for x in t.get(key, [])):
                return False
        tiers = t.get("media_default_tiers", {})
        if not isinstance(tiers, dict) or not all(k in {"image", "video"} and v in {"draft", "standard", "premium"} for k, v in tiers.items()):
            return False
        for pattern in t.get("suggest", []):
            re.compile(pattern)
        seen = set()
        for c in t.get("checks", []):
            if c["kind"] not in CHECK_KINDS or c["id"] in seen or c.get("severity", "warn") not in {"warn", "info"} or not isinstance(c["message"], str):
                return False
            seen.add(c["id"])
            for field in ("match", "first", "then"):
                if field in c:
                    re.compile(c[field])
            if c["kind"] == "order" and not (c.get("first") and c.get("then")):
                return False
        return True
    except (KeyError, TypeError, re.error):
        return False


def load(settings=None):
    """All usable types by id, shipped ones first and the operator's own copies replacing them."""
    found = {}
    for directory in reversed(_dirs(settings)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                    continue
                t = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError, UnicodeError):
                continue
            if isinstance(t, dict) and _valid(t) and t["id"] == path.stem:
                found[t["id"]] = t
    return found


def listing(settings=None):
    return [{"id": t["id"], "label": t["label"], "summary": t["summary"], "keys": t.get("keys", []), "failure_points": t.get("failure_points", []),
             "human_signoffs": t.get("human_signoffs", []), "visual_checks": t.get("visual_checks", "")} for t in load(settings).values()]


def media_default_tiers(type_id, settings=None):
    """The quality tier the media panel starts each kind of slot on for a project type. A website's background clips start on the cheapest tier; other types on standard."""
    given = (load(settings).get(type_id or "") or {}).get("media_default_tiers", {})
    return {kind: given.get(kind, "standard") for kind in ("image", "video")}


def suggest(text, settings=None):
    """The type whose patterns match the text most often, or None. A suggestion only: the operator chooses."""
    lowered = (text or "").lower()
    best, score = None, 0
    for t in load(settings).values():
        n = sum(1 for p in t.get("suggest", []) if re.search(p, lowered))
        if n > score:
            best, score = t["id"], n
    return best if score >= 2 else None


def planner_section(type_id, settings=None):
    """The text added to the planner prompt for a typed project: how to plan it, where it fails, where a person looks and signs off."""
    t = load(settings).get(type_id or "")
    if not t:
        return ""
    lines = [f"Project type: {t['label']}.", t["planner_text"], "Known failure points for this type; plan around each one:"]
    lines += [f"- {fp}" for fp in t.get("failure_points", [])]
    if t.get("visual_checks"):
        lines.append("Visual checks: " + t["visual_checks"])
    if t.get("human_signoffs"):
        lines.append("Human sign-offs belong here: " + "; ".join(t["human_signoffs"]) + ".")
    return "\n".join(lines)


def _text(n, scope="title"):
    """What a check reads. A story's title says what it is for; its description and acceptance say what it will run. Gate checks (has_story, order)
    read the title so a passing mention in a long description is not mistaken for the gate; not_agent_for reads everything because the risky
    command is usually in the description."""
    keys = ("title", "description", "acceptance") if scope == "all" else ("title",)
    return " ".join(str(n.get(k) or "") for k in keys).lower()


def _ancestors(by_key, key):
    seen, stack = set(), list(by_key.get(key, {}).get("depends_on", []))
    while stack:
        k = stack.pop()
        if k in seen or k not in by_key:
            continue
        seen.add(k)
        stack.extend(by_key[k].get("depends_on", []))
    return seen


def _who(n, assignee):
    human = n.get("assignee") == "human"
    return human if assignee == "human" else (not human) if assignee == "agent" else True


def check(type_id, nodes, settings=None):
    """Findings for a plan: [{id, severity, message, stories}]. Empty when the plan fits the type or no type is chosen."""
    t = load(settings).get(type_id or "")
    if not t:
        return []
    stories = [n for n in nodes if n.get("kind", "story") == "story"]
    by_key = {n["key"]: n for n in stories if "key" in n}
    findings = []
    for c in t.get("checks", []):
        kind, bad = c["kind"], []
        if kind == "has_story":
            ok = any(re.search(c["match"], _text(n, c.get("scope", "title"))) and _who(n, c.get("assignee")) for n in stories) if c.get("match") else any(_who(n, c.get("assignee")) for n in stories)
            if not ok:
                findings.append({"id": c["id"], "severity": c.get("severity", "warn"), "message": c["message"], "stories": []})
            continue
        if kind == "not_agent_for":
            bad = [n["key"] for n in stories if n.get("assignee") != "human" and re.search(c["match"], _text(n, c.get("scope", "all")))]
        elif kind == "order":
            firsts = {n["key"] for n in stories if re.search(c["first"], _text(n, c.get("scope", "title")))}
            for n in stories:
                if re.search(c["then"], _text(n, c.get("scope", "title"))) and _who(n, c.get("assignee")) and n["key"] not in firsts and not (firsts & _ancestors(by_key, n["key"])):
                    bad.append(n["key"])
            if not any(re.search(c["then"], _text(n, c.get("scope", "title"))) and _who(n, c.get("assignee")) for n in stories):
                bad = []         # nothing to order
        if bad:
            findings.append({"id": c["id"], "severity": c.get("severity", "warn"), "message": c["message"], "stories": bad})
    return findings
