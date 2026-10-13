import json
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from billing import config, dashboard, price
from models import UsageRecord, Run
from usage import UsageScanner, parse_line, put, record

NOW = datetime(2026, 10, 9, 12, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()


def test_cache_rates_and_unknown_not_zero(sessions):
    with sessions() as s:
        cfg = config(s)
        r = {
            "model": "claude-sonnet-5-5",
            "input_tokens": 1_000_000,
            "output_tokens": 100_000,
            "cached_input_tokens": 800_000,
            "cache_write_tokens": 100_000,
            "cache_write_1h_tokens": 40_000,
        }
        # Custom rate permits a large prompt; category counts are disjoint.
        cfg["rates"]["claude-sonnet-5-5"] = {
            **cfg["rates"]["claude-sonnet-5-5"],
            "max_input": None,
        }
        assert round(price(r, cfg)[0], 6) == 1.59
        assert price({**r, "model": "unknown"}, cfg) == (None, "unpriced")
        assert price({**r, "reported_cost_usd": 0}, cfg)[0] == 0
        assert price({**r, "cached_input_tokens": 2_000_000}, cfg)[0] is None


def test_incremental_codex_canonical_replay_and_restart(sessions, tmp_path):
    root = tmp_path / ".codex/sessions"
    root.mkdir(parents=True)
    path = root / "one.jsonl"
    docs = [
        {
            "type": "session_meta",
            "payload": {"id": "sid", "base_instructions": "private secret"},
        },
        {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        {
            "type": "event_msg",
            "timestamp": NOW,
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 100,
                        "output_tokens": 2,
                        "total_tokens": 102,
                    }
                },
            },
        },
        {
            "type": "token_usage_record",
            "timestamp": NOW,
            "payload": {
                "response_id": "response1",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 80,
                    "output_tokens": 2,
                },
            },
        },
        {
            "type": "event_msg",
            "timestamp": NOW,
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 100,
                        "output_tokens": 2,
                        "total_tokens": 102,
                    }
                },
            },
        },
    ]
    path.write_text("".join(json.dumps(d) + "\n" for d in docs))
    scanner = UsageScanner(sessions, tmp_path)
    scanner.scan_jsonl("codex", root)
    scanner = UsageScanner(sessions, tmp_path)
    scanner.scan_jsonl("codex", root)
    with path.open("a") as f:
        f.write(json.dumps(docs[3]) + "\n")
    scanner.scan_jsonl("codex", root)
    with sessions() as s:
        rows = list(s.scalars(select(UsageRecord)))
        assert len(rows) == 1
        payload = json.loads(rows[0].payload)
        assert payload["input_tokens"] == 100
        assert "private secret" not in rows[0].payload
        assert payload["model"] == "gpt-6.1-sol"


def test_partial_jsonl_tail_and_budget(sessions, tmp_path):
    root = tmp_path / ".openclaw/agents/main/sessions"
    root.mkdir(parents=True)
    p = root / "sid.jsonl"
    doc = {
        "type": "message",
        "id": "event",
        "timestamp": NOW,
        "message": {
            "role": "assistant",
            "model": "some-model",
            "usage": {
                "input": 20,
                "output": 2,
                "cacheRead": 5,
                "cost": {"total": 0.02},
            },
            "content": [{"text": "private"}],
        },
    }
    text = json.dumps(doc)
    p.write_text(text)
    scanner = UsageScanner(sessions, tmp_path, byte_budget=1)
    scanner.scan_jsonl("openclaw", tmp_path / ".openclaw/agents")
    with sessions() as s:
        assert not list(s.scalars(select(UsageRecord)))
    with p.open("a") as f:
        f.write("\n")
    scanner.scan_jsonl("openclaw", tmp_path / ".openclaw/agents")
    with sessions() as s:
        row = s.scalar(select(UsageRecord))
        payload = json.loads(row.payload)
        assert payload["input_tokens"] == 25 and payload["target"] == "main"
        assert "private" not in row.payload
        assert price(payload, config(s))[0] == 0.02


def test_claude_chunks_deduplicate_and_preserve_subagent(sessions):
    ctx = {}
    doc = {
        "type": "assistant",
        "sessionId": "parent",
        "agentId": "child",
        "isSidechain": True,
        "timestamp": NOW,
        "message": {
            "id": "message1",
            "model": "claude-sonnet-5-5",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 1,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 20,
            },
        },
    }
    with sessions.begin() as s:
        put(s, parse_line("claude", doc, ctx, "fallback"))
        doc["message"]["usage"]["output_tokens"] = 8
        put(s, parse_line("claude", doc, ctx, "fallback"))
    with sessions() as s:
        rows = list(s.scalars(select(UsageRecord)))
        assert len(rows) == 1
        r = json.loads(rows[0].payload)
        assert r["session_id"] == "child" and r["parent"] == "parent"
        assert r["output_tokens"] == 8 and r["input_tokens"] == 60


def test_month_savings_negative_and_native_supersedes_mcd(sessions, subscriptions):
    with sessions.begin() as s:
        put(
            s,
            record(
                "codex",
                "native",
                "response",
                NOW,
                "gpt-6.1-sol",
                {"input_tokens": 100, "output_tokens": 20},
            ),
        )
        s.add(
            Run(
                agent="codex",
                session_id="native",
                stage="succeeded",
                started_at=int(NOW),
                input_tokens=999,
                output_tokens=999,
                working_dir="/ws",
                command="[]",
                log_path="",
            )
        )
    with sessions() as s:
        result = dashboard(s, now=NOW + 1)
        codex = next(a for a in result["overview"] if a["agent"] == "codex")
        assert codex["input_tokens"] == 100 and codex["responses"] == 1
        assert codex["month_subscription_usd"] == 20
        assert codex["month_savings_usd"] == -0.0 - 19.9996


def test_lifetime_not_attributed_to_recent_period(sessions):
    with sessions.begin() as s:
        row = record(
            "hermes",
            "old-session",
            "m",
            NOW,
            "some-model",
            {"input_tokens": 1000000, "output_tokens": 1},
            scope="session lifetime",
            cost=10,
        )
        row["first_seen"] = NOW - 20 * 86400
        put(s, row)
    with sessions() as s:
        r = dashboard(s, period="24h", agent="hermes", now=NOW + 1)
        assert r["summary"]["input_tokens"] == 0
        assert r["sessions"][0]["input_tokens"] == 1000000
        assert r["sessions"][0]["scope"] == "session lifetime"
        assert r["overview"][1]["lifetime_sessions_excluded"] == 1


def test_target_selection_keeps_full_picker_and_overview(sessions):
    with sessions.begin() as s:
        for target in ["main", "developer"]:
            put(
                s,
                record(
                    "openclaw",
                    target,
                    "r",
                    NOW,
                    "model",
                    {"input_tokens": 10, "output_tokens": 1},
                    target=target,
                    cost=1,
                ),
            )
    with sessions() as s:
        r = dashboard(s, agent="openclaw", target="main", now=NOW + 1)
        assert r["summary"]["responses"] == 1 and len(r["sessions"]) == 2
        assert r["overview"][0]["responses"] == 2
        assert [a["target"] for a in r["activity"]] == ["main"]


def test_billing_preferences_validation_and_persistence(make_client):
    with make_client() as client:
        cfg = client.get("/api/billing").json()
        # Free-only by default: no subscription exists until the operator saves one.
        assert cfg["accounts"]["claude"] == {"mode": "api", "monthly_usd": 0.0}
        response = client.patch(
            "/api/billing",
            json={
                "accounts": {"codex": {"mode": "subscription", "monthly_usd": 42}},
                "rates": {
                    "custom-model": {
                        "input": 2,
                        "output": 5,
                        "cached": 0.1,
                        "write": 3,
                        "write_1h": 4,
                    }
                },
            },
        )
        assert response.status_code == 200
        cfg = client.get("/api/billing").json()
        assert cfg["accounts"]["codex"]["monthly_usd"] == 42
        assert cfg["rates"]["custom-model"]["source"] == "custom"
        assert (
            client.patch(
                "/api/billing",
                json={
                    "accounts": {"codex": {"mode": "subscription", "monthly_usd": -1}}
                },
            ).status_code
            == 422
        )
        assert client.get("/api/agents/usage?period=invalid").status_code == 422
        assert client.get("/api/agents/usage?agent=codex").status_code == 200


def test_published_context_tiers(sessions):
    with sessions() as s:
        cfg = config(s)

        def row(model, n):
            return {
                "model": model,
                "input_tokens": n,
                "output_tokens": 100,
                "cached_input_tokens": 0,
            }

        assert price(row("gpt-6.1-sol", 272_000), cfg)[0] == 0.545
        assert round(price(row("gpt-6.1-sol", 272_001), cfg)[0], 6) == 1.089504
        assert round(price(row("claude-haiku-5-5", 100_001), cfg)[0], 7) == 0.0502505
        assert round(price(row("claude-opus-5-5", 900_000), cfg)[0], 6) == 3.602


def test_hermes_reads_disjoint_token_buckets(sessions, tmp_path):
    import sqlite3

    root = tmp_path / ".hermes"
    root.mkdir()
    with sqlite3.connect(root / "state.db") as db:
        db.execute("CREATE TABLE sessions (id TEXT, parent_session_id TEXT)")
        db.execute(
            "CREATE TABLE session_model_usage (session_id TEXT,model TEXT,task TEXT,billing_provider TEXT,billing_mode TEXT,input_tokens INTEGER,output_tokens INTEGER,cache_read_tokens INTEGER,cache_write_tokens INTEGER,estimated_cost_usd REAL,actual_cost_usd REAL,cost_status TEXT,first_seen REAL,last_seen REAL)"
        )
        db.execute("INSERT INTO sessions VALUES ('s','parent')")
        db.execute(
            "INSERT INTO session_model_usage VALUES ('s','model','child','provider','api',10,2,30,40,.2,.3,'actual',?,?)",
            (NOW, NOW),
        )
    UsageScanner(sessions, tmp_path).scan_hermes()
    with sessions() as s:
        r = json.loads(s.scalar(select(UsageRecord)).payload)
        assert r["input_tokens"] == 80 and r["cached_input_tokens"] == 30
        assert r["reported_cost_usd"] == 0.3 and r["parent"] == "parent"


def test_same_subagent_nickname_keeps_distinct_sessions(sessions):
    with sessions.begin() as s:
        for sid in ["child-1", "child-2"]:
            put(
                s,
                record(
                    "codex",
                    sid,
                    "response",
                    NOW,
                    "gpt-6.1-sol",
                    {"input_tokens": 10, "output_tokens": 1},
                    target="explorer",
                    parent="parent",
                ),
            )
    with sessions() as s:
        d = dashboard(s, agent="codex", target="child-1", now=NOW + 1)
        assert d["summary"]["responses"] == 1
        assert {r["id"] for r in d["sessions"]} == {"child-1", "child-2"}
        assert all(r["name"] == "explorer" for r in d["sessions"])


def test_run_with_no_usage_is_not_a_usage_record(sessions):
    with sessions.begin() as s:
        s.add(Run(agent="codex", stage="failed", started_at=int(NOW), working_dir="/ws", command="[]", log_path=""))
    with sessions() as s:
        d = dashboard(s, agent="codex", now=NOW + 1)
        # Nothing recorded means no model usage to price: not shown as unpriced either.
        assert d["summary"]["responses"] == 0 and d["summary"]["unpriced"] == 0
        assert d["summary"]["input_tokens"] == 0 and d["summary"]["api_equivalent_usd"] is None


def test_published_rates_for_models_seen_in_use(sessions):
    with sessions() as s:
        cfg = config(s)

        def cost(model, n_in, n_out=1_000_000):
            return price({"model": model, "input_tokens": n_in, "output_tokens": n_out}, cfg)[0]

        # Standard tier, then the long-context tier above 272K input (2x input, 1.5x output).
        assert round(cost("gpt-5.6-sol", 200_000), 6) == 20.8
        assert round(cost("gpt-5.6-sol", 300_000, 1_000_000), 6) == 8 * 0.3 + 30
        assert round(cost("gpt-5.6-terra", 300_000, 1_000_000), 6) == 4 * 0.3 + 18
        assert round(cost("gpt-5.6-luna", 100_000), 6) == 1.22
        assert round(cost("gemini-2.5-flash", 1_000_000), 6) == 2.8
        # A gateway or vendor prefix does not hide the rate.
        assert round(cost("google/gemini-2.5-flash", 1_000_000), 6) == 2.8
        assert round(cost("openrouter/google/gemini-2.5-flash", 1_000_000), 6) == 2.8


def test_free_models_cost_zero_even_without_token_counts(sessions):
    with sessions() as s:
        cfg = config(s)
        for model in (
            "thinkingmachines/inkling:free",
            "openrouter/cohere/north-mini-code:free",
            "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        ):
            assert price({"model": model}, cfg) == (0.0, "free model")
            assert price({"model": model, "input_tokens": 5, "output_tokens": 5}, cfg)[0] == 0.0
        # Only the :free suffix counts, and a reported cost still wins.
        assert price({"model": "openrouter/cohere/north-mini-code"}, cfg) == (None, "unpriced")
        assert price({"model": "x:free", "reported_cost_usd": 0.01}, cfg)[0] == 0.01
        # An explicit rate the operator saved for a free-named model is respected.
        cfg["rates"]["x:free"] = {**cfg["rates"]["gpt-6-luna"], "input": 1, "output": 1, "source": "custom"}
        assert price({"model": "x:free", "input_tokens": 100_000, "output_tokens": 0}, cfg)[0] == 0.1


def test_published_rates_for_older_models_in_history(sessions):
    with sessions() as s:
        cfg = config(s)
        row = {"input_tokens": 100_000, "output_tokens": 100_000, "cached_input_tokens": 50_000,
               "cache_write_tokens": 10_000}
        # (50k uncached x input + 50k cached x cache-hit + 10k... ) written tokens are part of input here.
        def cost(model):
            return round(price({**row, "model": model}, cfg)[0], 6)

        assert cost("claude-opus-4-8") == cost("claude-opus-4-7") == round((40_000 * 5 + 50_000 * 0.5 + 10_000 * 6.25 + 100_000 * 25) / 1e6, 6)
        assert cost("claude-fable-5") == round((40_000 * 10 + 50_000 * 1 + 10_000 * 12.5 + 100_000 * 50) / 1e6, 6)
        assert cost("claude-fable-5-1") == round((40_000 * 10 + 50_000 * 0.25 + 10_000 * 12.5 + 100_000 * 50) / 1e6, 6)
        assert cost("claude-sonnet-5") == round((40_000 * 2 + 50_000 * 0.2 + 10_000 * 2.5 + 100_000 * 10) / 1e6, 6)
        assert price({"model": "gpt-5.4", "input_tokens": 131_210, "output_tokens": 372, "cached_input_tokens": 128_384}, cfg)[0] is not None
        assert price({"model": "gpt-5.5", "input_tokens": 55_058, "output_tokens": 26, "cached_input_tokens": 54_144}, cfg)[0] is not None


def test_only_used_models_without_a_price_are_unpriced(sessions):
    def run(**kw):
        return Run(agent="codex", started_at=int(NOW), working_dir="/ws", command="[]", log_path="", **kw)

    with sessions.begin() as s:
        s.add(run(stage="failed", error="PRICE_UNKNOWN: route has no reviewed pricing class", model_requested="gpt-6-sol"))
        s.add(run(stage="failed", error='{"message": "You\\u2019ve hit your usage limit."}', model_requested="gpt-6-sol"))
        s.add(run(stage="interrupted", error="service stopped while the run was in progress", model_requested="gpt-6-sol"))
        s.add(run(stage="succeeded", model_requested="gpt-6-sol", input_tokens=1000, output_tokens=100))
        s.add(run(stage="succeeded", model_requested="brand-new-model", input_tokens=1000, output_tokens=100))
    with sessions() as s:
        d = dashboard(s, agent="codex", now=NOW + 1)
        assert d["summary"]["responses"] == 2 and d["summary"]["unpriced"] == 1   # only the model with no recorded price
        assert [m["model"] for m in d["summary"]["models"] if m["unpriced"]] == ["brand-new-model"]


def test_jobs_that_call_no_model_are_not_usage_records(sessions):
    with sessions.begin() as s:
        s.add(Run(agent="mcd-monitor", stage="succeeded", started_at=int(NOW), working_dir="/ws", command="[]", log_path=""))
    with sessions() as s:
        d = dashboard(s, now=NOW + 1)
        assert all(a["responses"] == 0 for a in d["overview"])
