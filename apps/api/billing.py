"""Configurable API-equivalent estimates, subscription comparison and source coverage."""

import json
import re
from pathlib import Path
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from sqlalchemy import select
from agents import BILLED_AGENTS
from models import BillingConfig, UsageRecord, Run, Card, ChatThread

CATALOG_FILE = Path(__file__).with_name("pricing_catalog.json")
RATE_FIELDS = ("input", "output", "cached", "write", "write_1h", "max_input", "long_after",
               "long_input_multiplier", "long_output_multiplier", "changes", "verified", "platform", "agents", "status")


def load_catalog(path=CATALOG_FILE):
    """Published prices by model id, from pricing_catalog.json. Keep that file current with
    scripts/pricing/check.py; nothing here is typed by hand."""
    catalog = json.loads(Path(path).read_text())
    pages = {name: spec["page"] for name, spec in catalog["sources"].items()}
    rates = {}
    for model, entry in catalog["models"].items():
        rates[model] = {k: entry[k] for k in RATE_FIELDS if k in entry}
        rates[model].setdefault("max_input", None)
        rates[model]["source"] = pages[entry["source"]]
    return catalog, rates


CATALOG, DEFAULT_RATES = load_catalog()

DEFAULT_ACCOUNTS = {
    a: {
        # Free-only by default: a subscription route exists only after the operator saves it.
        "mode": "api",
        "monthly_usd": 0.0,
    }
    # Grok starts as an API account: it is refused until the operator saves a subscription for it
    # (Billing & rates), which is also the moment they accept that it sends work to xAI.
    for a in BILLED_AGENTS
}


# Spending limits are off unless the operator turns them on, in one place: Agents, Billing & rates, Spending & limits. Without a limit MCD only discloses that a route can cost money.
DEFAULT_LIMITS = {"require_reviewed_pricing": False, "per_run_cap_usd": None, "paid_needs_runtime_limit": False, "allow_subscription_in_free_only": False, "allow_paid_in_free_only": False}


def limits(s, settings=None):
    """The effective spending limits. Defaults are all off. A saved value wins; an older explicit MAC_CONTROL_DISPATCH_MAX_BUDGET_USD is used as the per-run cap until one is saved."""
    row = s.get(BillingConfig, 1)
    saved = (json.loads(row.payload) if row else {}).get("limits") or {}
    out = dict(DEFAULT_LIMITS)
    if settings is not None and "dispatch_max_budget_usd" in getattr(settings, "model_fields_set", set()) and (settings.dispatch_max_budget_usd or 0) > 0:
        out["per_run_cap_usd"] = float(settings.dispatch_max_budget_usd)
    for key in ("require_reviewed_pricing", "paid_needs_runtime_limit", "allow_subscription_in_free_only", "allow_paid_in_free_only"):
        if isinstance(saved.get(key), bool):
            out[key] = saved[key]
    if "per_run_cap_usd" in saved:
        cap = saved["per_run_cap_usd"]
        out["per_run_cap_usd"] = float(cap) if isinstance(cap, (int, float)) and not isinstance(cap, bool) and cap > 0 else None
    return out


def config(s):
    row = s.get(BillingConfig, 1)
    saved = json.loads(row.payload) if row else {}
    return {
        "accounts": {**DEFAULT_ACCOUNTS, **saved.get("accounts", {})},
        "rates": {**DEFAULT_RATES, **saved.get("rates", {})},
        "timezone": "America/Los_Angeles",
        "limits": limits(s),
        "media_rates": {k: float(v) for k, v in (saved.get("media_rates") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
    }


FREE_SUFFIX = ":free"


def is_free(model):
    """OpenRouter free variants and the exact free router aliases have zero list price."""
    return (model or "").endswith(FREE_SUFFIX) or model in {"openrouter/free", "openrouter/openrouter/free"}


def find_rate(model, rates):
    """The rate for a model id, also when a gateway or vendor prefix is in front of it
    ('openrouter/google/gemini-2.5-flash') or a build date is behind it."""
    parts = (model or "").split("/")
    for i in range(len(parts)):
        name = "/".join(parts[i:])
        found = rates.get(name) or rates.get(re.sub(r"-\d{8}$", "", name))
        if found:
            return found
    return None


def effective(r, ts):
    """The rate in force on the day of the usage: a catalog entry can list dated price changes
    (a published rise on a known date) that apply to usage on or after that date."""
    changes = [c for c in r.get("changes") or [] if ts is not None and date_of(ts) >= c["from"]]
    if not changes:
        return r
    merged = dict(r)
    for change in sorted(changes, key=lambda c: c["from"]):
        merged.update({k: v for k, v in change.items() if k != "from"})
    return merged


def date_of(ts):
    return datetime.fromtimestamp(ts, ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def price(row, cfg):
    if row.get("reported_cost_usd") is not None:
        return (
            row["reported_cost_usd"],
            row.get("cost_kind") or "reported API equivalent",
        )
    model = row.get("model") or ""
    rates = cfg["rates"]
    r = find_rate(model, rates)
    if not r and is_free(model):
        return 0.0, "free model"
    if not r or row.get("input_tokens") is None or row.get("output_tokens") is None:
        return None, "unpriced"
    r = effective(r, row.get("ts"))
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

    result = {
        **sums(rows),
        "models": [{"model": m, **sums(items)} for m, items in sorted(models.items())],
    }
    # Models that were used and have no recorded price: the signal that the price catalog is behind.
    result["unpriced_models"] = [m["model"] for m in result["models"] if m["unpriced"]]
    return result


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
    native_sessions = {
        (r.agent, r.session_id) for r in s.scalars(select(UsageRecord))
        if json.loads(r.payload).get("source") != "retained accounting"
    }
    # A late native scan supersedes a deletion-time accounting snapshot too.
    rows = [r for r in rows if r.get("source") != "retained accounting"
            or ((r["agent"], r["session_id"]) not in native_sessions
                and (r["agent"], r.get("receipt_session_id")) not in native_sessions)]
    for run in s.scalars(
        select(Run).where(Run.started_at >= min(start, month), Run.started_at <= now)
    ):
        # A usage record means a model was used. Monitor jobs never call one, and a run that recorded
        # no tokens and no cost (refused at the price gate, turned away at a usage limit, cut off before
        # the model answered) has no usage to price, so it is not a record at all, priced or unpriced.
        if (run.agent not in cfg["accounts"] or (run.agent, run.session_id) in native_sessions
                or (run.agent, f"mcd-run-{run.id}") in native_sessions or run.stage == "running"):
            continue
        if run.input_tokens is None and run.output_tokens is None and run.cost_usd is None:
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
        "note": "Token API equivalents are estimates, not invoices. Standard API rates include verified context tiers and exclude tools, taxes and speed/residency surcharges. A model whose name ends in :free costs 0. Other unknown rates stay unpriced. Missing cache breakdowns use uncached input for estimates. Monthly savings compare captured calendar-month usage with the full monthly subscription; negative means below break-even. Native sessions replace matching MCD runs. Hermes lifetime counters crossing the period boundary are excluded from period totals.",
    }
