"""Model watch: a weekly, deterministic look at OpenRouter's public model list that leaves a Backlog card when something needs a person.

The job reads the public list (the same fixed read as the Models section's Refresh), compares it with the price catalog and the last snapshot,
and, when there is something new, writes ONE card in the Backlog with the sources and exactly what differs. It changes nothing else: it never
edits the price catalog or any route, because a model that is wrongly priced at zero can spend money and adopting a model is a reviewed
change. It is off by default (it reads the network on a schedule), runs at most once per interval, and a failed read is recorded and tried
again next time rather than reported as a change. A model that is in the catalog as free but is no longer listed as free is called out first:
that is the one that matters for spending.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import cards
import model_profiles as mp

STATE = "watch.json"
SOURCES = ("https://openrouter.ai/api/v1/models", "https://openrouter.ai/models?max_price=0")
BODY_MAX = 6000


def _state(data_dir) -> dict:
    got = mp._read_json(mp._folder(data_dir) / STATE)
    return got if isinstance(got, dict) else {}


def _save(data_dir, state: dict) -> None:
    mp._write_json(mp._folder(data_dir) / STATE, state)


def status(settings, now: int | None = None) -> dict:
    now = int(now if now is not None else time.time())
    st = _state(settings.data_dir)
    interval = settings.model_watch_interval_days * 86400
    last = st.get("last_run") or 0
    return {"enabled": bool(settings.model_watch_enabled), "interval_days": settings.model_watch_interval_days, "last_run": st.get("last_run"), "last_ok": st.get("last_ok"),
            "last_error": st.get("last_error"), "last_summary": st.get("last_summary"), "last_card_id": st.get("last_card_id"),
            "due": bool(settings.model_watch_enabled) and now - last >= interval}


def _facts(data_dir) -> dict:
    snap = mp.snapshot(data_dir) or {"models": []}
    return {m["id"]: m for m in snap["models"]}


def proposal(result: dict, data_dir, now: int) -> tuple[str, str]:
    """Title and body for the card: sources first, then what differs, then what to do and what not to."""
    diff = result["diff"]
    facts = _facts(data_dir)
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    parts = []
    if diff["no_longer_free"]:
        parts.append("**Check first: in the price catalog as free, but not listed as free on OpenRouter now.** A model priced at zero that is no longer free can spend money. "
                     "Do not route work to these until the catalog is reviewed:\n" + "\n".join(f"- `{i}`" for i in diff["no_longer_free"]))
    if diff["new_free"]:
        rows = []
        for i in diff["new_free"]:
            f = facts.get(i, {})
            bits = [b for b in (f"context {f['context']:,}" if f.get("context") else "", "tools" if f.get("tools") else "", "structured output" if f.get("structured") else "", "reasoning" if f.get("reasoning") else "") if b]
            rows.append(f"- `{i}`" + (f" ({', '.join(bits)})" if bits else ""))
        parts.append("**Listed as free on OpenRouter but not in the price catalog:**\n" + "\n".join(rows))
    if diff["changed"]:
        parts.append("**Changed since the last read:**\n" + "\n".join(f"- `{c['id']}`: {', '.join(c['fields'])}" for c in diff["changed"]))
    parts.append("**Sources**\n" + "\n".join(f"- {u}" for u in SOURCES) + f"\n- Read {result['count']} models ({result['free']} free) on {day}.")
    parts.append("**What to do.** Nothing was changed. To add a model to the catalog, or to remove one that is no longer free, make a normal reviewed change to "
                 "`free_models` in the price catalog (see docs/configuration/pricing-catalog.md and scripts/pricing/check.py). Model facts and your own runs are in the Models "
                 "section of Telemetry. Do not adopt a model on this note alone: try it on low-risk work first and add a note with where it came from.")
    title = f"Model watch {day}: " + ", ".join(x for x in (f"{len(diff['no_longer_free'])} no longer free" if diff["no_longer_free"] else "", f"{len(diff['new_free'])} new free" if diff["new_free"] else "",
                                                          f"{len(diff['changed'])} changed" if diff["changed"] else "") if x)
    return title[:180], "\n\n".join(parts)[:BODY_MAX]


def run(s, settings, now: int | None = None, fetch=None) -> dict:
    """One watch: read, compare, and (only when there is something new since the last card) leave a Backlog card. Records the outcome either way."""
    now = int(now if now is not None else time.time())
    st = _state(settings.data_dir)
    try:
        result = mp.refresh(settings.data_dir, now, fetch, enabled=settings.model_refresh_enabled)
    except mp.ModelError as error:
        _save(settings.data_dir, {**st, "last_run": now, "last_ok": False, "last_error": str(error)})
        return {"ok": False, "error": str(error), "card_id": None}
    diff = result["diff"]
    findings = {"new": diff["new_free"], "gone": diff["no_longer_free"], "changed": [c["id"] + ":" + ",".join(c["fields"]) for c in diff["changed"]]}
    fingerprint = hashlib.sha256(json.dumps(findings, sort_keys=True).encode()).hexdigest()[:16]
    card_id, summary = None, f"{result['count']} models, {result['free']} free; nothing new"
    if any(findings.values()):
        summary = f"{len(findings['new'])} new free, {len(findings['gone'])} no longer free, {len(findings['changed'])} changed"
        if fingerprint != st.get("last_fingerprint"):
            title, body = proposal(result, settings.data_dir, now)
            card = cards.create(s, {"title": title, "body": body, "assignee_type": "human", "kind": "triage", "size": "xs", "risk": "low", "area": "model-watch",
                                    "priority": "low", "tags": ["model watch"], "estimate_minutes": 15,
                                    "route_reason": "A person decides whether to adopt or drop a model; the watch only reports."}, settings, "model-watch")
            card_id = card.id
    _save(settings.data_dir, {"last_run": now, "last_ok": True, "last_error": None, "last_summary": summary, "last_fingerprint": fingerprint if any(findings.values()) else st.get("last_fingerprint"),
                              "last_card_id": card_id or st.get("last_card_id")})
    return {"ok": True, "summary": summary, "card_id": card_id, "findings": {k: len(v) for k, v in findings.items()}}


def tick(sessions, settings, now: int | None = None, fetch=None) -> dict | None:
    """What the collector calls every few hours: run the watch only when it is switched on and due."""
    now = int(now if now is not None else time.time())
    if not status(settings, now)["due"]:
        return None
    with sessions.begin() as s:
        return run(s, settings, now, fetch)
