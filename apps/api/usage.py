"""Incremental local telemetry. Never persist transcript bodies, prompts, tool arguments or credentials.

JSONL cursors survive restarts; canonical response IDs prevent streaming chunks and replay from
inflating totals. Codex response records supersede its cumulative compatibility events. Native
sessions supersede matching MCD runs. Hermes supplies lifetime per-model session counters, which
are kept separately from dated response usage rather than attributed to today's spending.
"""

from __future__ import annotations
import hashlib
import math
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from models import UsageCursor, UsageRecord

AGENTS = ("openclaw", "hermes", "claude", "codex", "grok")


def timestamp(v):
    if isinstance(v, (int, float)):
        return v / 1000 if v > 10**11 else float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def number(v):
    return max(0, int(v)) if isinstance(v, (int, float)) and math.isfinite(v) else 0


def record(
    agent,
    sid,
    key,
    ts,
    model,
    usage,
    *,
    target=None,
    parent=None,
    cost=None,
    cost_kind=None,
    scope="response",
    cached=0,
    written=0,
    write_1h=0,
    input_total=None,
):
    return {
        "id": hashlib.sha256(f"{agent}:{sid}:{key}".encode()).hexdigest(),
        "agent": agent,
        "session_id": sid,
        "ts": ts,
        "model": model,
        "target": target,
        "parent": parent,
        "input_tokens": (
            input_total
            if input_total is not None
            else number(usage.get("input_tokens"))
        ),
        "output_tokens": number(usage.get("output_tokens")),
        "cached_input_tokens": cached,
        "cache_write_tokens": written,
        "cache_write_1h_tokens": write_1h,
        "reported_cost_usd": cost,
        "cost_kind": cost_kind,
        "scope": scope,
        "source": "native",
    }


def parse_line(agent, doc, ctx, fallback_sid, target=None):
    """Return usage metadata only; context is a small allowlist, not the source event."""
    typ = doc.get("type")
    p = doc.get("payload") or {}
    if not isinstance(p, dict):
        return None
    ts = timestamp(doc.get("timestamp"))
    if agent == "codex":
        if typ == "session_meta":
            ctx["sid"] = p.get("id") or p.get("session_id") or fallback_sid
            source = p.get("source")
            if isinstance(source, dict):
                sub = source.get("subagent") or {}
                spawn = sub.get("thread_spawn", {}) if isinstance(sub, dict) else {}
                if isinstance(spawn, dict):
                    ctx["parent"] = spawn.get("parent_thread_id")
                    ctx["target"] = spawn.get("agent_nickname") or spawn.get(
                        "agent_role"
                    )
        if typ == "turn_context":
            ctx["model"] = p.get("model")
        u = None
        key = None
        if typ == "token_usage_record":
            ctx["modern"] = True
            u = p.get("usage")
            key = p.get("response_id")
        elif (
            typ == "event_msg"
            and p.get("type") == "token_count"
            and not ctx.get("modern")
        ):
            total = (p.get("info") or {}).get("total_token_usage")
            if total:
                prev = ctx.get("total") or {}
                ctx["total"] = total
                u = {
                    k: max(0, number(v) - number(prev.get(k))) for k, v in total.items()
                }
                if not any(u.values()):
                    return None
                key = "legacy:" + str(total.get("total_tokens"))
        if isinstance(u, dict) and key and ts:
            return record(
                agent,
                ctx.get("sid", fallback_sid),
                key,
                ts,
                ctx.get("model"),
                u,
                target=ctx.get("target"),
                parent=ctx.get("parent"),
                cached=number(u.get("cached_input_tokens")),
                written=number(u.get("cache_write_input_tokens")),
            )
    elif agent == "claude":
        m = doc.get("message") or {}
        if not isinstance(m, dict):
            return None
        u = m.get("usage")
        if u is not None and not isinstance(u, dict):
            return None
        if (
            typ == "assistant"
            and u
            and m.get("id")
            and ts
            and m.get("model") != "<synthetic>"
        ):
            cached = number(u.get("cache_read_input_tokens"))
            written = number(u.get("cache_creation_input_tokens"))
            return record(
                agent,
                (
                    (doc.get("agentId") or fallback_sid)
                    if doc.get("isSidechain")
                    else doc.get("sessionId") or fallback_sid
                ),
                m["id"],
                ts,
                m.get("model"),
                u,
                target=doc.get("agentId")
                or (fallback_sid if doc.get("isSidechain") else None),
                parent=doc.get("sessionId") if doc.get("isSidechain") else None,
                cached=cached,
                written=written,
                write_1h=number(
                    (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens")
                ),
                input_total=number(u.get("input_tokens")) + cached + written,
            )
    elif agent == "openclaw":
        if typ == "session":
            ctx["sid"] = doc.get("id") or fallback_sid
        m = doc.get("message") or {}
        if not isinstance(m, dict):
            return None
        u = m.get("usage")
        if u is not None and not isinstance(u, dict):
            return None
        if typ == "message" and m.get("role") == "assistant" and u and ts:
            cached = number(u.get("cacheRead"))
            written = number(u.get("cacheWrite"))
            cost = (u.get("cost") or {}).get("total")
            return record(
                agent,
                ctx.get("sid", fallback_sid),
                doc.get("id") or str(ts),
                ts,
                m.get("model"),
                {"output_tokens": u.get("output")},
                target=target,
                input_total=number(u.get("input")) + cached + written,
                cached=cached,
                written=written,
                cost=float(cost) if isinstance(cost, (int, float)) else None,
                cost_kind="source estimate" if cost is not None else None,
            )
    return None


def put(s, row):
    payload = json.dumps(row, separators=(",", ":"))
    values = dict(
        id=row["id"],
        agent=row["agent"],
        ts=row["ts"],
        session_id=row["session_id"],
        payload=payload,
    )
    stmt = insert(UsageRecord).values(**values)
    s.execute(
        stmt.on_conflict_do_update(
            index_elements=["id"], set_={k: v for k, v in values.items() if k != "id"}
        )
    )


class UsageScanner:
    def __init__(self, sessions, home=None, byte_budget=64 * 1024 * 1024):
        self.sessions = sessions
        self.home = Path(home or Path.home())
        self.byte_budget = byte_budget
        self.status = {a: {"state": "starting", "checked_at": None} for a in AGENTS}

    def scan(self):
        for agent, root in [
            ("openclaw", ".openclaw/agents"),
            ("claude", ".claude/projects"),
            ("codex", ".codex/sessions"),
        ]:
            try:
                self.scan_jsonl(agent, self.home / root)
            except (OSError, ValueError, sqlite3.Error):
                self.status[agent] = {"state": "unavailable", "checked_at": time.time()}
        try:
            self.scan_hermes()
        except (OSError, ValueError, sqlite3.Error):
            self.status["hermes"] = {"state": "unavailable", "checked_at": time.time()}

    def scan_jsonl(self, agent, root):
        if not root.is_dir():
            self.status[agent] = {"state": "not found", "checked_at": time.time()}
            return
        # Include archived Codex sessions. All historical records are indexed once, then only tails.
        files = list(root.rglob("*.jsonl"))
        if agent == "codex":
            files += list((self.home / ".codex/archived_sessions").glob("*.jsonl"))
        files = sorted(
            (p for p in files if ".trajectory." not in p.name),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        budget = self.byte_budget
        remaining = 0
        malformed = 0
        with self.sessions.begin() as s:
            for path in files:
                stat = path.stat()
                ident = f"{stat.st_dev}:{stat.st_ino}"
                cur = s.get(UsageCursor, str(path))
                if cur is None:
                    cur = UsageCursor(
                        path=str(path), offset=0, identity=ident, context="{}"
                    )
                    s.add(cur)
                if cur.identity != ident or cur.offset > stat.st_size:
                    cur.offset = 0
                    cur.identity = ident
                    cur.context = "{}"
                if cur.offset == stat.st_size:
                    continue
                if budget <= 0:
                    remaining += 1
                    continue
                ctx = json.loads(cur.context)
                target = (
                    path.relative_to(root).parts[0] if agent == "openclaw" else None
                )
                sid = path.stem
                with path.open("rb") as f:
                    f.seek(cur.offset)
                    while budget > 0:
                        start = f.tell()
                        line = f.readline()
                        if not line:
                            break
                        if not line.endswith(b"\n"):
                            f.seek(start)
                            break
                        budget -= len(line)
                        # Skip large content/tool events without decoding their JSON.
                        wanted = (
                            [
                                b'"session_meta"',
                                b'"turn_context"',
                                b'"token_usage_record"',
                                b'"token_count"',
                            ]
                            if agent == "codex"
                            else [b'"usage"', b'"type":"session"', b'"type": "session"']
                        )
                        if not any(w in line for w in wanted):
                            continue
                        try:
                            doc = json.loads(line)
                        except (ValueError, UnicodeError):
                            malformed += 1
                            continue
                        if not isinstance(doc, dict):
                            continue
                        was_modern = ctx.get("modern")
                        row = parse_line(agent, doc, ctx, sid, target)
                        if agent == "codex" and ctx.get("modern") and not was_modern:
                            # Remove cumulative compatibility records once canonical responses appear.
                            for old in s.scalars(
                                select(UsageRecord).where(
                                    UsageRecord.agent == "codex",
                                    UsageRecord.session_id == ctx.get("sid", sid),
                                )
                            ):
                                if json.loads(old.payload).get("legacy"):
                                    s.delete(old)
                        if row:
                            if agent == "codex" and not ctx.get("modern"):
                                row["legacy"] = True
                            put(s, row)
                    cur.offset = f.tell()
                    cur.context = json.dumps(ctx)
                if cur.offset < stat.st_size:
                    remaining += 1
        self.status[agent] = {
            "state": "indexing" if remaining else "ready",
            "checked_at": time.time(),
            "files": len(files),
            "pending_files": remaining,
            "malformed_lines": malformed,
        }

    def scan_hermes(self):
        path = self.home / ".hermes/state.db"
        if not path.exists():
            self.status["hermes"] = {"state": "not found", "checked_at": time.time()}
            return
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            # Explicit columns: no prompts, message bodies, API keys, URLs or model_config.
            rows = db.execute(
                """SELECT u.session_id,u.model,u.task,u.billing_provider,u.billing_mode,u.input_tokens,u.output_tokens,
                u.cache_read_tokens,u.cache_write_tokens,u.estimated_cost_usd,u.actual_cost_usd,
                u.cost_status,u.first_seen,u.last_seen,s.parent_session_id
                FROM session_model_usage u JOIN sessions s ON s.id=u.session_id"""
            ).fetchall()
        with self.sessions.begin() as s:
            for r in rows:
                cost = (
                    r["actual_cost_usd"]
                    if r["cost_status"] == "actual"
                    else (
                        r["estimated_cost_usd"]
                        if r["cost_status"] == "estimated"
                        else None
                    )
                )
                row = record(
                    "hermes",
                    r["session_id"],
                    r["model"]
                    + ":"
                    + (r["task"] or "")
                    + ":"
                    + (r["billing_provider"] or "")
                    + ":"
                    + (r["billing_mode"] or ""),
                    r["last_seen"] or r["first_seen"] or 0,
                    r["model"],
                    dict(r),
                    input_total=number(r["input_tokens"])
                    + number(r["cache_read_tokens"])
                    + number(r["cache_write_tokens"]),
                    cached=number(r["cache_read_tokens"]),
                    written=number(r["cache_write_tokens"]),
                    parent=r["parent_session_id"],
                    target=r["task"] or None,
                    cost=cost,
                    cost_kind=(
                        "reported charge"
                        if r["cost_status"] == "actual"
                        else "source estimate" if cost is not None else None
                    ),
                    scope="session lifetime",
                )
                row["first_seen"] = r["first_seen"]
                put(s, row)
        self.status["hermes"] = {
            "state": "ready",
            "checked_at": time.time(),
            "sessions": len({r["session_id"] for r in rows}),
            "note": "Per-model session lifetime counters; shown separately from dated response totals.",
        }


def put_provider_receipt(s, agent, sid, receipt):
    """Persist one independent Pi provider receipt without prompt/response bodies."""
    from openrouter_costs import amount
    cost = amount(receipt.get('cost_usd'))
    if cost is None or not receipt.get('response_id') or not receipt.get('model'):
        raise ValueError('Provider receipt is incomplete')
    row = record(agent, sid, receipt['response_id'], receipt['ts'], receipt['model'],
                 receipt['usage'], cost=cost, cost_kind=receipt.get('cost_source', 'reported'))
    row['source'] = 'OpenRouter provider boundary'
    put(s, row)
    return row
