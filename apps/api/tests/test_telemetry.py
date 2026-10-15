"""Jobs and telemetry: assignee (person or agent), agent and model on every record, job, kind and tier cuts, cost and API-equivalent cost."""
from __future__ import annotations

import json

import pytest

import telemetry as tm
from models import Card, Project, ProjectTask, Run
from tests.test_auth import secured  # noqa: F401
from tests.test_profiles import signed

NOW = 1_800_000_000
DAY = 86400


def card(s, title, column="done", **kw):
    base = dict(title=title, body="b", column=column, timeout_s=60, created_at=NOW - 10 * DAY, updated_at=NOW - DAY, assignee_type="agent", agent="codex")
    base.update(kw)
    c = Card(**base)
    s.add(c)
    s.flush()
    return c


def run(s, c, stage="succeeded", model="gpt-6.1-sol", requested=None, started=NOW - 2 * DAY, secs=120.0, inp=1_000_000, out=100_000, cost=None, agent=None):
    r = Run(card_id=c.id, agent=agent or c.agent or "codex", model_requested=requested or model, model_reported=model, stage=stage, started_at=started,
            ended_at=started + int(secs), duration_s=secs, input_tokens=inp, output_tokens=out, cost_usd=cost, working_dir="/tmp", command="[]", log_path="/tmp/x")
    s.add(r)
    s.flush()
    return r


def job(s, cards, title="Ship the thing", revision=1):
    p = Project(document=json.dumps({"title": title}), state="active", created_by="op", created_at=0, updated_at=0)
    s.add(p)
    s.flush()
    for i, c in enumerate(cards):
        s.add(ProjectTask(card_id=c.id, project_id=p.id, revision=revision, node_key=f"n{i}", role="story"))
    s.commit()
    return p


def test_each_record_carries_assignee_agent_and_model_and_the_tiles_match_the_board(sessions):
    with sessions() as s:
        a = card(s, "A", kind="implement", size="m", risk="low", estimate_minutes=60, route_tier="subscription"); run(s, a)
        b = card(s, "B", "running", assignee_type="human", agent=None, assignee_user="jamie@example.com", route_tier="human", estimate_minutes=30)
        c = card(s, "C", "backlog", assignee_type="human", agent=None, route_tier="human")                        # a human task nobody has
        d = card(s, "D", "review", kind="review", route_tier="subscription")
        e = card(s, "E", "failed", kind="test", route_tier="subscription"); run(s, e, "failed")
        s.commit()
        out = tm.overview(s, NOW, 30)
    t = out["tiles"]
    assert t["unassigned"] == 1 and t["in_progress"] == 1 and t["waiting_for_you"] == 1 and t["completed"] == 1 and t["failed"] == 1
    assert t["estimates_missing"] == 2                                              # C and D are open without an estimate (B has one)
    people = {(p["name"], p["type"]): p for p in out["by_assignee"]}
    assert people[("codex", "agent")]["done"] == 1 and people[("jamie@example.com", "human")]["open"] == 1 and people[("Unassigned", "human")]["open"] == 1
    assert {m["agent"] for m in out["models"]} == {"codex"} and out["models"][0]["model"] == "gpt-6.1-sol"
    assert {x["column"]: x["count"] for x in out["by_status"]} == {"backlog": 1, "queued": 0, "running": 1, "review": 1, "done": 1, "failed": 1}
    assert {x["tier"]: x["count"] for x in out["by_tier"]} == {"free": 0, "subscription": 3, "api": 0, "human": 2}   # the donut's numbers


def test_cost_is_reported_and_api_equivalent_apart_and_free_and_unpriced_are_not_guessed(sessions):
    with sessions() as s:
        paid = card(s, "paid"); run(s, paid, model="gpt-6.1-sol", inp=1_000_000, out=100_000)                         # priced from the catalog
        free = card(s, "free", agent="hermes", route_tier="free"); run(s, free, model="openrouter/google/gemma-4-31b-it:free", agent="hermes")
        mystery = card(s, "mystery"); run(s, mystery, model="some-unlisted-model-9", inp=500, out=50)
        s.commit()
        out = tm.overview(s, NOW, 30)
    import billing
    with sessions() as s:
        expected = billing.price({"model": "gpt-6.1-sol", "input_tokens": 1_000_000, "output_tokens": 100_000, "ts": NOW - 2 * DAY}, billing.config(s))[0]
    assert expected and expected > 0                                                   # the catalog prices this model
    models = {m["model"]: m for m in out["models"]}
    assert models["gpt-6.1-sol"]["api_equivalent_usd"] == pytest.approx(expected, rel=1e-3)
    assert models["openrouter/google/gemma-4-31b-it:free"]["api_equivalent_usd"] == 0 and models["openrouter/google/gemma-4-31b-it:free"]["tier"] == "free"
    assert out["totals"]["unpriced_runs"] == 1 and models["some-unlisted-model-9"]["api_equivalent_usd"] == 0   # counted, never guessed
    assert out["totals"]["api_equivalent_usd"] == pytest.approx(expected, rel=1e-3)


def test_a_fallback_is_visible_as_the_model_that_served_not_the_one_requested(sessions):
    with sessions() as s:
        c = card(s, "fell back", agent="hermes", route_tier="free")
        run(s, c, stage="failed", model="openrouter/free", agent="hermes")
        run(s, c, stage="succeeded", model="google/gemini-2.5-flash", requested="openrouter/free", agent="hermes")
        s.commit()
        out = tm.overview(s, NOW, 30)
    served = {m["model"]: m for m in out["models"]}
    assert served["google/gemini-2.5-flash"]["served_instead_of_requested"] == 1 and served["openrouter/free"]["success_rate"] == 0.0


def test_jobs_group_a_plan_revisions_stories_with_estimate_against_actual_and_cost(sessions):
    with sessions() as s:
        one = card(s, "one", kind="implement", estimate_minutes=10); run(s, one, secs=600.0, cost=0.5)
        two = card(s, "two", "running", kind="test", estimate_minutes=20)
        p = job(s, [one, two], "Ship the thing")
        card(s, "loose", kind="docs")
        s.commit()
        out = tm.overview(s, NOW, 30)
        filtered = tm.overview(s, NOW, 30, {"job": f"p{p.id}r1"})
    j = out["jobs"][0]
    assert j["job"] == f"p{p.id}r1" and j["title"] == "Ship the thing" and (j["stories"], j["done"], j["open"]) == (2, 1, 1)
    assert j["estimate_minutes"] == 30 and j["actual_minutes"] == 10.0 and j["cost_usd"] == 0.5
    assert filtered["tiles"]["completed"] == 1 and filtered["totals"]["cards"] == 2           # the filter narrows every view
    assert filtered["filters"] == {"job": f"p{p.id}r1"} and f"p{p.id}r1" in out["options"]["job"]


def test_kinds_show_time_first_pass_rate_and_estimate_accuracy(sessions):
    with sessions() as s:
        a = card(s, "a", kind="implement", estimate_minutes=10); run(s, a, secs=1200.0)                         # twice the estimate, first pass
        b = card(s, "b", kind="implement", estimate_minutes=10); run(s, b, stage="failed", secs=60.0); run(s, b, secs=600.0)   # a retry
        s.commit()
        out = tm.overview(s, NOW, 30)
    k = next(x for x in out["by_kind"] if x["kind"] == "implement")
    assert k["stories"] == 2 and k["done"] == 2 and k["first_pass_rate"] == 0.5 and k["median_actual_over_estimate"] is not None


def test_velocity_counts_completions_per_week_and_the_window_limits_completed(sessions):
    with sessions() as s:
        recent = card(s, "recent", updated_at=NOW - DAY); run(s, recent, started=NOW - DAY)
        old = card(s, "old", updated_at=NOW - 60 * DAY); run(s, old, started=NOW - 60 * DAY)
        s.commit()
        out = tm.overview(s, NOW, 30)
        wide = tm.overview(s, NOW, 90)
    assert out["tiles"]["completed"] == 1 and wide["tiles"]["completed"] == 2
    assert sum(w["done"] for w in out["velocity"]) == 1


def test_the_route_is_operator_only_and_returns_the_bundle(secured):  # noqa: F811
    signed(secured)
    body = secured.get("/api/telemetry?days=14&kind=implement").json()
    assert body["days"] == 14 and body["filters"] == {"kind": "implement"} and {"tiles", "jobs", "models", "by_assignee", "velocity", "options"} <= set(body)
    assert secured.get("/api/telemetry?days=0").status_code == 422


def test_cards_made_before_the_envelope_still_show_their_route_tier(sessions):
    with sessions() as s:
        old = card(s, "old subscription card"); run(s, old)                                  # route_tier was never stored
        free = card(s, "old free card", agent="hermes", model="openrouter/free"); run(s, free, agent="hermes", model="openrouter/free")
        s.commit()
        out = tm.overview(s, NOW, 30)
    assert {m["tier"] for m in out["models"]} == {"subscription", "free"} and "untagged" not in {m["tier"] for m in out["models"]}


def test_work_is_cut_by_the_property_the_plan_was_approved_under(sessions):
    with sessions() as s:
        a = card(s, "A"); run(s, a)
        b = card(s, "B"); run(s, b)
        c = card(s, "C", "running")                                   # not in any project
        job(s, [a], title="Money work")
        p2 = Project(document=json.dumps({"title": "Docs"}), state="active", created_by="op", created_at=0, updated_at=0,
                     approved_manifest=json.dumps({"standards": {"state": "ok", "property": "upubhub", "sha256": "x" * 64, "areas": 3, "checks": 2}}))
        s.add(p2)
        s.flush()
        s.add(ProjectTask(card_id=b.id, project_id=p2.id, revision=1, node_key="n0", role="story"))
        s.commit()
        everything = tm.overview(s, NOW, 30)
        only = tm.overview(s, NOW, 30, {"property": "upubhub"})
    rows = {r["property"]: r for r in everything["by_property"]}
    assert rows["upubhub"]["stories"] == 1 and rows["upubhub"]["done"] == 1 and rows["none"]["stories"] == 2
    assert "upubhub" in everything["options"]["property"]
    assert only["tiles"]["completed"] == 1 and only["totals"]["cards"] == 1
