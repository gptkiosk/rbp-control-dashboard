"""The coordinator's scorecard: what it returned, what a person changed, and how the work went. Built from records the app already keeps.

* When the Delegator returns a plan, the plan is scored by fixed checks and a short fingerprint of each node is kept (as a project memory
  note), so no copy of the plan is stored twice.
* When a plan revision is approved, the approved plan is scored, compared with what the coordinator returned (how many nodes a person
  added, removed or changed), and recorded on the manifest with the planner, the Delegator and the coordinator wording in effect.
* The report joins those with telemetry: first-pass completion, rework and estimate error of that plan's stories, grouped by planner and by
  wording, so a change to the wording can be compared with the version before it.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict

from sqlalchemy import select

import billing
import coordinator_score as cs
import job_envelope
import standards
import telemetry
from models import Project, ProjectMemory
from role_pack import RoleStore

KIND = "scorecard"


def _tier(node: dict) -> str:
    human = node.get("assignee") == "human"
    return job_envelope.tier_for("human" if human else "agent", None if human else node.get("assignee"), node.get("model") or None)


def _label(route: dict | None) -> str:
    if not route:
        return "unknown"
    return f"{route.get('agent') or 'unknown'} · {route.get('model') or 'agent default'}"


def score(nodes: list[dict], settings, workdir) -> dict:
    found = standards.resolve(workdir, settings.data_dir) if workdir else None
    return cs.score_plan(nodes, found=found, tier_of=_tier)


def record_returned(s, project, nodes: list[dict], settings, planner: dict | None, delegator: dict | None, now: int | None = None) -> None:
    """Score the plan the Delegator just returned and keep its fingerprints for the approval-time comparison."""
    from projects import document
    result = score(nodes, settings, document(project).get("working_dir"))
    body = {"revision": project.revision, "planner": planner, "delegator": delegator, "score": result["score"], "passed": result["passed"],
            "total": result["total"], "failed": result["failed"], "sigs": cs.signatures(nodes)}
    s.add(ProjectMemory(project_id=project.id, kind=KIND, text=json.dumps(body, separators=(",", ":")), actor="mcd", created_at=int(now if now is not None else time.time())))


def at_approval(s, project, doc: dict, settings) -> dict:
    """What the manifest records about the approved plan: its score, the person's edits, who planned it and the wording in effect."""
    final = score(doc["nodes"], settings, doc.get("working_dir"))
    row = s.scalar(select(ProjectMemory).where(ProjectMemory.project_id == project.id, ProjectMemory.kind == KIND).order_by(ProjectMemory.id.desc()).limit(1))
    returned = json.loads(row.text) if row else None
    version = RoleStore(settings).version()
    return {"approved": {"score": final["score"], "passed": final["passed"], "total": final["total"], "failed": final["failed"]},
            "returned": {k: returned[k] for k in ("score", "passed", "total", "failed")} if returned else None,
            "edits": cs.edits(returned["sigs"], cs.signatures(doc["nodes"])) if returned else None,
            "planner": _label(returned.get("planner")) if returned else None, "delegator": _label(returned.get("delegator")) if returned else None,
            "wording": {"label": version["label"], "sha": version["sha"]}}


def report(s, now: int | None = None, days: int = 90) -> dict:
    now = int(now if now is not None else time.time())
    days = max(1, min(int(days), telemetry.MAX_DAYS))
    recs = telemetry.collect(s, now, days, billing.config(s))
    by_job: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        if r["job"]:
            by_job[r["job"]].append(r)
    plans = []
    for p in s.scalars(select(Project).where(Project.approved_manifest.is_not(None))):
        try:
            m = json.loads(p.approved_manifest)
        except ValueError:
            continue
        sc = m.get("scorecard")
        if not sc or (m.get("approved_at") or 0) < now - days * 86400:
            continue
        rows = by_job.get(f"p{p.id}r{m.get('revision')}", [])
        done = [r for r in rows if r["card"].column == "done"]
        ratios = [(r["exec_s"] / 60) / r["card"].estimate_minutes for r in done if r["card"].estimate_minutes and r["exec_s"]]
        try:
            title = json.loads(p.document).get("title") or f"Project {p.id}"
        except ValueError:
            title = f"Project {p.id}"
        plans.append({"project_id": p.id, "revision": m.get("revision"), "title": title, "approved_at": m.get("approved_at"), "planner": sc.get("planner"), "delegator": sc.get("delegator"),
                      "wording": sc.get("wording"), "score": sc["approved"]["score"], "failed": sc["approved"]["failed"], "returned_score": (sc.get("returned") or {}).get("score"),
                      "edits": sc.get("edits"), "stories": len(rows), "done": len(done), "first_pass": sum(1 for r in done if r["attempts"] == 1),
                      "failed_stories": sum(1 for r in rows if r["card"].column == "failed"), "estimate_ratio": round(statistics.median(ratios), 2) if ratios else None})
    plans.sort(key=lambda x: -(x["approved_at"] or 0))

    def group(key):
        out: dict[str, dict] = {}
        for pl in plans:
            k = key(pl)
            g = out.setdefault(k, {"label": k, "plans": 0, "score": [], "edits": [], "done": 0, "first_pass": 0, "ratios": []})
            g["plans"] += 1
            g["score"].append(pl["score"])
            if pl["edits"]:
                g["edits"].append(pl["edits"]["total"])
            g["done"] += pl["done"]
            g["first_pass"] += pl["first_pass"]
            if pl["estimate_ratio"] is not None:
                g["ratios"].append(pl["estimate_ratio"])
        return sorted(({"label": g["label"], "plans": g["plans"], "score": round(sum(g["score"]) / len(g["score"]), 3), "edits_per_plan": round(sum(g["edits"]) / len(g["edits"]), 1) if g["edits"] else None,
                        "first_pass_rate": round(g["first_pass"] / g["done"], 2) if g["done"] else None, "estimate_ratio": round(statistics.median(g["ratios"]), 2) if g["ratios"] else None,
                        "stories_done": g["done"]} for g in out.values()), key=lambda g: -g["plans"])
    return {"generated_at": now, "days": days, "plans": plans, "by_planner": group(lambda p: p["planner"] or "unknown"), "by_wording": group(lambda p: (p["wording"] or {}).get("label", "unknown")),
            "briefs": len(cs.briefs()), "note": "Scores check the plan, not the model. Edits are what a person changed between the coordinator's plan and the approved one. First pass and estimate ratio come from the work the plan led to."}
