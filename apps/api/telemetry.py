"""Jobs and telemetry: how planned and hand-made work is going, by job, kind, risk, tier, assignee, agent and model.

Read-only. Everything is computed from the card, run and project tables the app already keeps; nothing new is stored, so there is no
second source of truth to drift. Every record carries the agent, the model requested and the model that actually served the run
(the run's reported model, which differs after a fallback), and the provider, so a fallback is visible instead of averaged away.

Cost is reported two ways and kept apart: the cost the agent reported (`cost_usd`), and an API-equivalent estimate from the price
catalog (`billing.price`), which is also what a flat membership is compared against. Unpriced usage is counted, not guessed.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import billing
import job_envelope
from models import Card, Project, ProjectTask, Run

OPEN = ("queued", "running", "review")
DAY = 86400
MAX_DAYS = 365
DIMENSIONS = ("job", "property", "kind", "risk", "size", "tier", "assignee", "agent", "model")


def _median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 1) if values else None


def _label(card: Card) -> tuple[str, str]:
    """Who the work is assigned to: a person (or Unassigned) for a human task, an agent otherwise."""
    if card.assignee_type == "human":
        return (card.assignee_user or "Unassigned"), "human"
    return (card.agent or "Unassigned"), "agent"


def _property(project: Project | None) -> str | None:
    """The repository standards' property the plan was approved under (recorded on the manifest), or None."""
    try:
        return (json.loads(project.approved_manifest).get("standards") or {}).get("property") or None
    except (AttributeError, TypeError, ValueError):
        return None


def _title(project: Project | None) -> str:
    try:
        return json.loads(project.document).get("title") or f"Project {project.id}"
    except (AttributeError, ValueError):
        return "Project"


def collect(s, now: int, days: int, cfg: dict | None = None) -> list[dict]:
    """One record per card with everything the views need. Small enough to hold in memory on a Raspberry Pi."""
    cfg = cfg or billing.config(s)
    links = {t.card_id: t for t in s.scalars(select(ProjectTask))}
    projects = {p.id: p for p in s.scalars(select(Project))}
    runs: dict[int, list[Run]] = defaultdict(list)
    for run in s.scalars(select(Run).where(Run.card_id.is_not(None)).order_by(Run.id)):
        runs[run.card_id].append(run)
    out = []
    for card in s.scalars(select(Card)):
        link = links.get(card.id)
        mine = runs.get(card.id, [])
        final = next((r for r in reversed(mine) if r.stage == "succeeded"), None)
        last = mine[-1] if mine else None
        who, who_type = _label(card)
        cost = equivalent = 0.0
        unpriced = 0
        tokens = 0
        for r in mine:
            cost += r.cost_usd or 0.0
            tokens += (r.input_tokens or 0) + (r.output_tokens or 0)
            eq, basis = billing.price({"model": r.model_reported or r.model_requested, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                                       "cached_input_tokens": r.cached_input_tokens, "cache_write_tokens": r.cache_write_tokens,
                                       "reported_cost_usd": r.cost_usd, "ts": r.started_at}, cfg)
            if eq is None and (r.input_tokens or r.output_tokens):
                unpriced += 1
            equivalent += eq or 0.0
        completed_at = (final.ended_at if final and final.ended_at else card.updated_at) if card.column == "done" else None
        out.append({
            "card": card, "job": f"p{link.project_id}r{link.revision}" if link and link.role == "story" else None,
            "project_id": link.project_id if link else None, "property": _property(projects.get(link.project_id)) if link else None, "project": _title(projects.get(link.project_id)) if link else None,
            "story": bool(link and link.role == "story"), "assignee": who, "assignee_type": who_type,
            "tier": card.route_tier or job_envelope.tier_for(card.assignee_type, card.agent, card.model), "runs": mine, "attempts": len(mine), "final": final, "last": last,
            "completed_at": completed_at,
            "exec_s": sum(r.duration_s or 0.0 for r in mine), "cost_usd": cost, "api_equivalent_usd": equivalent, "unpriced": unpriced, "tokens": tokens,
            "model": (last.model_reported or last.model_requested) if last else (card.model or None), "agent": card.agent,
        })
    return out


def _match(rec: dict, f: dict) -> bool:
    card = rec["card"]
    values = {"job": rec["job"], "property": rec["property"], "kind": card.kind, "risk": card.risk, "size": card.size, "tier": rec["tier"],
              "assignee": rec["assignee"], "agent": card.agent, "model": rec["model"]}
    return all(not f.get(k) or values[k] == f[k] for k in DIMENSIONS)


def _monday(ts: float) -> str:
    d = datetime.fromtimestamp(ts, timezone.utc).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def overview(s, now: int | None = None, days: int = 30, filters: dict | None = None) -> dict:
    now = int(now if now is not None else time.time())
    days = max(1, min(int(days), MAX_DAYS))
    f = {k: v for k, v in (filters or {}).items() if k in DIMENSIONS and v}
    since = now - days * DAY
    cfg = billing.config(s)
    everything = collect(s, now, days, cfg)
    recs = [r for r in everything if _match(r, f)]

    open_ = [r for r in recs if r["card"].column in OPEN or r["card"].column == "backlog"]
    done_in_window = [r for r in recs if r["completed_at"] and r["completed_at"] >= since]
    tiles = {
        "unassigned": sum(1 for r in open_ if r["assignee"] == "Unassigned"),
        "in_progress": sum(1 for r in recs if r["card"].column in ("queued", "running")),
        "waiting_for_you": sum(1 for r in recs if r["card"].column == "review"),
        "completed": len(done_in_window), "completed_days": days,
        "estimates_missing": sum(1 for r in open_ if r["card"].estimate_minutes is None),
        "failed": sum(1 for r in recs if r["card"].column == "failed"),
        "untagged": sum(1 for r in recs if r["story"] is False and r["card"].kind is None),
    }

    status = [{"column": c, "count": sum(1 for r in recs if r["card"].column == c)} for c in ("backlog", "queued", "running", "review", "done", "failed")]

    by_tier = [{"tier": t, "count": sum(1 for r in recs if r["tier"] == t)} for t in job_envelope.TIERS]

    people: dict[tuple[str, str], dict] = {}
    for r in recs:
        row = people.setdefault((r["assignee"], r["assignee_type"]), {"name": r["assignee"], "type": r["assignee_type"], "open": 0, "done": 0, "failed": 0})
        col = r["card"].column
        row["open" if col in OPEN or col == "backlog" else ("done" if col == "done" else "failed")] += 1
    by_assignee = sorted(people.values(), key=lambda p: -(p["open"] + p["done"] + p["failed"]))

    weeks: dict[str, int] = defaultdict(int)
    for r in recs:
        if r["completed_at"] and r["completed_at"] >= now - 8 * 7 * DAY:
            weeks[_monday(r["completed_at"])] += 1
    velocity = [{"week": w, "done": weeks[w]} for w in sorted(weeks)]

    jobs: dict[str, dict] = {}
    for r in recs:
        if not r["job"]:
            continue
        j = jobs.setdefault(r["job"], {"job": r["job"], "project_id": r["project_id"], "title": r["project"], "stories": 0, "done": 0, "failed": 0, "open": 0,
                                       "estimate_minutes": 0, "actual_minutes": 0.0, "cost_usd": 0.0, "api_equivalent_usd": 0.0, "last_activity": 0})
        col = r["card"].column
        j["stories"] += 1
        j["done" if col == "done" else ("failed" if col == "failed" else "open")] += 1
        j["estimate_minutes"] += r["card"].estimate_minutes or 0
        j["actual_minutes"] += r["exec_s"] / 60
        j["cost_usd"] += r["cost_usd"]
        j["api_equivalent_usd"] += r["api_equivalent_usd"]
        j["last_activity"] = max(j["last_activity"], r["completed_at"] or 0, (r["last"].ended_at or r["last"].started_at) if r["last"] else 0)
    job_rows = sorted(({**j, "actual_minutes": round(j["actual_minutes"], 1), "cost_usd": round(j["cost_usd"], 4), "api_equivalent_usd": round(j["api_equivalent_usd"], 4)}
                       for j in jobs.values()), key=lambda j: -j["last_activity"])

    props: dict[str, dict] = {}
    for r in recs:
        card = r["card"]
        p = props.setdefault(r["property"] or "none", {"property": r["property"] or "none", "stories": 0, "open": 0, "done": 0, "failed": 0, "first_pass": 0, "minutes": []})
        p["stories"] += 1
        p["done" if card.column == "done" else ("failed" if card.column == "failed" else "open")] += 1
        if card.column == "done":
            p["minutes"].append(r["exec_s"] / 60)
            p["first_pass"] += 1 if r["attempts"] == 1 else 0
    by_property = sorted(({"property": p["property"], "stories": p["stories"], "open": p["open"], "done": p["done"], "failed": p["failed"],
                           "first_pass_rate": round(p["first_pass"] / p["done"], 2) if p["done"] else None, "median_minutes": _median(p["minutes"])}
                          for p in props.values()), key=lambda p: -p["stories"])

    kinds: dict[str, dict] = {}
    for r in recs:
        card = r["card"]
        k = kinds.setdefault(card.kind or "untagged", {"kind": card.kind or "untagged", "stories": 0, "done": 0, "minutes": [], "first_pass": 0, "estimate_ratio": []})
        k["stories"] += 1
        if card.column == "done":
            k["done"] += 1
            k["minutes"].append(r["exec_s"] / 60)
            k["first_pass"] += 1 if r["attempts"] == 1 else 0
            if card.estimate_minutes and r["exec_s"]:
                k["estimate_ratio"].append((r["exec_s"] / 60) / card.estimate_minutes)
    by_kind = sorted(({"kind": k["kind"], "stories": k["stories"], "done": k["done"], "median_minutes": _median(k["minutes"]),
                       "first_pass_rate": round(k["first_pass"] / k["done"], 2) if k["done"] else None,
                       "median_actual_over_estimate": _median(k["estimate_ratio"])} for k in kinds.values()), key=lambda k: -k["stories"])

    models: dict[tuple, dict] = {}
    for r in recs:
        for run in r["runs"]:
            if run.started_at < since:
                continue
            served = run.model_reported or run.model_requested or "unknown"
            key = (run.agent, served, r["tier"])
            m = models.setdefault(key, {"agent": run.agent, "model": served, "tier": r["tier"], "requested": set(), "runs": 0, "succeeded": 0,
                                        "seconds": [], "tokens": 0, "cost_usd": 0.0, "api_equivalent_usd": 0.0, "fallbacks": 0})
            m["runs"] += 1
            m["succeeded"] += 1 if run.stage == "succeeded" else 0
            if run.duration_s:
                m["seconds"].append(run.duration_s)
            m["tokens"] += (run.input_tokens or 0) + (run.output_tokens or 0)
            m["cost_usd"] += run.cost_usd or 0.0
            eq, _ = billing.price({"model": served, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens, "cached_input_tokens": run.cached_input_tokens,
                                   "cache_write_tokens": run.cache_write_tokens, "reported_cost_usd": run.cost_usd, "ts": run.started_at}, cfg)
            m["api_equivalent_usd"] += eq or 0.0
            if run.model_requested and run.model_reported and run.model_requested.removeprefix("openrouter/") != run.model_reported.removeprefix("openrouter/"):
                m["fallbacks"] += 1
                m["requested"].add(run.model_requested)
    model_rows = sorted(({"agent": m["agent"], "model": m["model"], "tier": m["tier"], "runs": m["runs"], "succeeded": m["succeeded"],
                          "success_rate": round(m["succeeded"] / m["runs"], 2), "median_seconds": _median(m["seconds"]), "tokens": m["tokens"],
                          "cost_usd": round(m["cost_usd"], 4), "api_equivalent_usd": round(m["api_equivalent_usd"], 4),
                          "served_instead_of_requested": m["fallbacks"]} for m in models.values()), key=lambda m: -m["runs"])

    activity = []
    for r in sorted((x for x in recs if x["last"] and x["last"].ended_at), key=lambda x: -x["last"].ended_at)[:12]:
        run = r["last"]
        activity.append({"at": run.ended_at, "card_id": r["card"].id, "title": r["card"].title, "outcome": run.stage, "assignee": r["assignee"],
                         "agent": run.agent, "model": run.model_reported or run.model_requested, "job": r["job"]})

    options = {k: sorted({v for v in values if v}) for k, values in {
        "job": [r["job"] for r in everything], "property": [r["property"] for r in everything], "kind": [r["card"].kind for r in everything], "risk": [r["card"].risk for r in everything],
        "size": [r["card"].size for r in everything], "tier": [r["tier"] for r in everything], "assignee": [r["assignee"] for r in everything],
        "agent": [r["card"].agent for r in everything], "model": [r["model"] for r in everything]}.items()}
    return {
        "generated_at": now, "days": days, "filters": f, "options": options, "tiles": tiles, "by_status": status, "by_tier": by_tier, "by_property": by_property, "by_assignee": by_assignee,
        "velocity": velocity, "jobs": job_rows, "by_kind": by_kind, "models": model_rows, "activity": activity,
        "totals": {"cost_usd": round(sum(r["cost_usd"] for r in recs), 4), "api_equivalent_usd": round(sum(r["api_equivalent_usd"] for r in recs), 4),
                   "unpriced_runs": sum(r["unpriced"] for r in recs), "tokens": sum(r["tokens"] for r in recs), "cards": len(recs)},
        "note": "API-equivalent cost is an estimate from the price catalog, not an invoice. Unpriced runs are counted, never guessed.",
    }
