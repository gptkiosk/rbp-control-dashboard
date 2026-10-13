"""Configurable API-equivalent estimates, subscription comparison and source coverage."""

import json
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from sqlalchemy import select
from models import BillingConfig, UsageRecord, Run, Card, ChatThread

OPENAI_SOURCE = "https://developers.openai.com/api/docs/pricing"
CLAUDE_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"


# Verified 2026-10-09. USD / 1M tokens. Standard rates with published long-context
# tiers; older models without a verified tier have a conservative input cutoff.
def rate(i, o, c, w, source, w1=None):
    return dict(
        input=i,
        output=o,
        cached=c,
        write=w,
        write_1h=w1 if w1 is not None else w,
        max_input=200_000,
        source=source,
        verified="2026-10-09",
    )


DEFAULT_RATES = {
    "gpt-6.1-sol": rate(2, 10, 0.1, 2.5, OPENAI_SOURCE),
    "gpt-6-astra": rate(10, 50, 1, 12.5, OPENAI_SOURCE),
    "gpt-6-luna": rate(0.1, 0.5, 0.01, 0.125, OPENAI_SOURCE),
    "gpt-6-sol": rate(
        2, 10, 0.2, 2.5, "https://developers.openai.com/api/docs/models/gpt-6-sol"
    ),
    "gpt-5.6-terra": {
        **rate(
            2,
            12,
            0.2,
            2.5,
            "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        ),
        "max_input": 272_000,
    },
    "claude-opus-5": rate(5, 25, 0.5, 6.25, CLAUDE_SOURCE, 10),
    "gpt-5.3-codex": rate(1.75, 14, 0.175, 1.75, OPENAI_SOURCE),
    "claude-opus-5-5": rate(4, 20, 0.2, 5, CLAUDE_SOURCE, 8),
    "claude-sonnet-5-5": rate(2, 10, 0.1, 2.5, CLAUDE_SOURCE, 4),
    "claude-haiku-5-5": {
        **rate(0.1, 0.5, 0.01, 0.125, CLAUDE_SOURCE, 0.2),
        "max_input": 100_000,
    },
    "claude-opus-4-6": rate(5, 25, 0.5, 6.25, CLAUDE_SOURCE, 10),
    "claude-sonnet-4-6": rate(3, 15, 0.3, 3.75, CLAUDE_SOURCE, 6),
    "claude-sonnet-4-5": rate(3, 15, 0.3, 3.75, CLAUDE_SOURCE, 6),
    "claude-haiku-4-5": rate(1, 5, 0.1, 1.25, CLAUDE_SOURCE, 2),
}
# A long-context request is charged at the higher tier for the entire request.
for model in ("gpt-6.1-sol", "gpt-6-sol", "gpt-6-astra", "gpt-6-luna"):
    DEFAULT_RATES[model].update(
        max_input=None,
        long_after=272_000,
        long_input_multiplier=2,
        long_output_multiplier=1.5,
    )
for model in (
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-opus-5",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
):
    DEFAULT_RATES[model]["max_input"] = None
DEFAULT_RATES["claude-haiku-5-5"].update(
    max_input=None,
    long_after=100_000,
    long_input_multiplier=5,
    long_output_multiplier=5,
)

DEFAULT_ACCOUNTS = {
    a: {
        # Free-only by default: a subscription route exists only after the operator saves it.
        "mode": "api",
        "monthly_usd": 0.0,
    }
    for a in ("openclaw", "hermes", "claude", "codex")
}


def config(s):
    row = s.get(BillingConfig, 1)
    saved = json.loads(row.payload) if row else {}
    return {
        "accounts": {**DEFAULT_ACCOUNTS, **saved.get("accounts", {})},
        "rates": {**DEFAULT_RATES, **saved.get("rates", {})},
        "timezone": "America/Los_Angeles",
    }


def price(row, cfg):
    if row.get("reported_cost_usd") is not None:
        return (
            row["reported_cost_usd"],
            row.get("cost_kind") or "reported API equivalent",
        )
    model = row.get("model") or ""
    rates = cfg["rates"]
    r = rates.get(model) or rates.get(re.sub(r"-\d{8}$", "", model))
    if not r or row.get("input_tokens") is None or row.get("output_tokens") is None:
        return None, "unpriced"
    total = row["input_tokens"]
    cached = row.get("cached_input_tokens") or 0
    written = row.get("cache_write_tokens") or 0
    w1 = row.get("cache_write_1h_tokens") or 0
    if (
        (r.get("max_input") is not None and total > r["max_input"])
        or cached + written > total
        or w1 > written
    ):
        return None, "unpriced"
    tier = total > r.get("long_after", float("inf"))
    input_multiplier = r.get("long_input_multiplier", 1) if tier else 1
    output_multiplier = r.get("long_output_multiplier", 1) if tier else 1
    cost = (
        (
            (total - cached - written) * r["input"]
            + cached * r["cached"]
            + (written - w1) * r["write"]
            + w1 * r["write_1h"]
        )
        * input_multiplier
        + row["output_tokens"] * r["output"] * output_multiplier
    ) / 1e6
    return cost, (
        "configured rate"
        if r.get("source") == "custom"
        else ("standard long-context estimate" if tier else "standard API estimate")
    )


def summarize(rows, cfg):
    models = defaultdict(list)
    for r in rows:
        models[r.get("model") or "not reported"].append(r)

    def sums(items):
        priced = [price(r, cfg)[0] for r in items]
        known = [v for v in priced if v is not None]
        return {
            "responses": len(items),
            "input_tokens": (
                sum(
                    r["input_tokens"]
                    for r in items
                    if r.get("input_tokens") is not None
                )
                if not items or any(r.get("input_tokens") is not None for r in items)
                else None
            ),
            "output_tokens": (
                sum(
                    r["output_tokens"]
                    for r in items
                    if r.get("output_tokens") is not None
                )
                if not items or any(r.get("output_tokens") is not None for r in items)
                else None
            ),
            "cached_input_tokens": sum(
                r.get("cached_input_tokens") or 0 for r in items
            ),
            "cache_write_tokens": sum(r.get("cache_write_tokens") or 0 for r in items),
            "api_equivalent_usd": round(sum(known), 6) if known else None,
            "unpriced": len(items) - len(known),
            "sessions": len({r["session_id"] for r in items}),
            "last_active": max((r["ts"] for r in items), default=None),
        }

    return {
        **sums(rows),
        "models": [{"model": m, **sums(items)} for m, items in sorted(models.items())],
    }


def month_start(now):
    return (
        datetime.fromtimestamp(now, ZoneInfo("America/Los_Angeles"))
        .replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )


def selection_id(row):
    # OpenClaw IDs identify configured agents; CLI sub-agents use distinct session IDs.
    return (
        row.get("target") or row["session_id"]
        if row["agent"] == "openclaw"
        else row["session_id"]
    )


def dashboard(s, period="month", agent=None, target=None, now=None):
    now = now or time.time()
    month = month_start(now)
    start = (
        month if period == "month" else now - (86400 if period == "24h" else 7 * 86400)
    )
    cfg = config(s)
    rows = [
        json.loads(r.payload)
        for r in s.scalars(
            select(UsageRecord).where(
                UsageRecord.ts >= min(start, month), UsageRecord.ts <= now
            )
        )
    ]
    rows = [r for r in rows if r.get("model") != "delivery-mirror"]
    native_sessions = set(
        s.execute(select(UsageRecord.agent, UsageRecord.session_id).distinct())
    )
    for run in s.scalars(
        select(Run).where(Run.started_at >= min(start, month), Run.started_at <= now)
    ):
        if ((run.agent, run.session_id) in native_sessions
            or (run.agent, f"mcd-run-{run.id}") in native_sessions
            or run.stage == "running"):
            continue
        card = s.get(Card, run.card_id) if run.card_id else None
        thread = s.get(ChatThread, run.thread_id) if run.thread_id else None
        rows.append(
            {
                "id": f"run:{run.id}",
                "agent": run.agent,
                "session_id": run.session_id or f"mcd-run-{run.id}",
                "target": (
                    card.agent_target
                    if card
                    else thread.agent_target if thread else None
                ),
                "ts": run.started_at,
                "model": run.model_reported or run.model_requested,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "cached_input_tokens": run.cached_input_tokens,
                "cache_write_tokens": run.cache_write_tokens,
                "reported_cost_usd": run.cost_usd,
                "cost_kind": "reported API equivalent",
                "scope": "response",
                "source": "MCD",
                "stage": run.stage,
                "card_id": run.card_id,
                "thread_id": run.thread_id,
            }
        )

    def dated(r, boundary):
        return r["ts"] >= boundary and (
            r.get("scope") != "session lifetime"
            or (r.get("first_seen") or 0) >= boundary
        )

    overview = []
    for a, account in cfg["accounts"].items():
        ar = [r for r in rows if r["agent"] == a]
        monthly = summarize([r for r in ar if dated(r, month)], cfg)
        eq = monthly["api_equivalent_usd"]
        fee = account["monthly_usd"] if account["mode"] == "subscription" else None
        overview.append(
            {
                "agent": a,
                **summarize([r for r in ar if dated(r, start)], cfg),
                "billing": account,
                "month_api_equivalent_usd": eq,
                "month_unpriced": monthly["unpriced"],
                "month_subscription_usd": fee,
                "month_savings_usd": (
                    round(eq - fee, 6) if eq is not None and fee is not None else None
                ),
                "lifetime_sessions_excluded": len(
                    {
                        r["session_id"]
                        for r in ar
                        if r.get("scope") == "session lifetime"
                        and r["ts"] >= start
                        and not dated(r, start)
                    }
                ),
                "month_lifetime_sessions_excluded": len(
                    {
                        r["session_id"]
                        for r in ar
                        if r.get("scope") == "session lifetime"
                        and r["ts"] >= month
                        and not dated(r, month)
                    }
                ),
            }
        )
    agent_rows = [r for r in rows if not agent or r["agent"] == agent]
    selected = [r for r in agent_rows if not target or selection_id(r) == target]
    sessions = defaultdict(list)
    for r in agent_rows:
        if r["ts"] < start:
            continue
        sessions[(r["agent"], selection_id(r))].append(r)
    session_rows = [
        {
            "agent": a,
            "id": ident,
            "name": items[-1].get("target"),
            "parent": items[-1].get("parent"),
            "scope": (
                "session lifetime"
                if any(r.get("scope") == "session lifetime" for r in items)
                else "selected interval"
            ),
            **summarize(
                (
                    [r for r in items if dated(r, start)]
                    if all(r.get("scope") != "session lifetime" for r in items)
                    else items
                ),
                cfg,
            ),
        }
        for (a, ident), items in sessions.items()
    ]
    activity = []
    for r in sorted(
        (r for r in selected if r["ts"] >= start), key=lambda r: r["ts"], reverse=True
    )[:80]:
        cost, basis = price(r, cfg)
        activity.append({**r, "api_equivalent_usd": cost, "cost_basis": basis})
    return {
        "period": period,
        "start": start,
        "end": now,
        "month_start": month,
        "timezone": cfg["timezone"],
        "overview": overview,
        "summary": summarize([r for r in selected if dated(r, start)], cfg),
        "sessions": sorted(
            session_rows, key=lambda r: r["last_active"] or 0, reverse=True
        ),
        "activity": activity,
        "note": "Token API equivalents are estimates, not invoices. Standard API rates include verified context tiers and exclude tools, taxes and speed/residency surcharges. Unknown rates stay unpriced. Missing cache breakdowns use uncached input for estimates. Monthly savings compare captured calendar-month usage with the full monthly subscription; negative means below break-even. Native sessions replace matching MCD runs. Hermes lifetime counters crossing the period boundary are excluded from period totals.",
    }
