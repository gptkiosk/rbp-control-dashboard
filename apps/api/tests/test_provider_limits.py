"""Subscription limits: reset-time parsing, events, same-grade alternates, rerouting and Discord control."""
import json
import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import provider_limits as pl
from models import Card, ProviderLimit, Run
from dispatcher import Dispatcher
from tests.test_projects import app, active, node          # noqa: F401  (fixtures and helpers)

LA = ZoneInfo("America/Los_Angeles")


def at(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=LA).timestamp())


NOW = at(2026, 10, 12, 15, 30)     # Mon 12 Oct 2026, 3:30 PM Pacific


# ------------------------------------------------------------------ parsing (real wording from MCD runs)


@pytest.mark.parametrize("text,expected", [
    ("You've hit your session limit · resets 4pm (America/Los_Angeles)", at(2026, 10, 12, 16)),
    ("You've hit your session limit · resets 7:40pm (America/Los_Angeles)", at(2026, 10, 12, 19, 40)),
    ("You've hit your session limit · resets 11am (America/Los_Angeles)", at(2026, 10, 13, 11)),   # already past today
    ("You've hit your session limit · resets 12am (America/Los_Angeles)", at(2026, 10, 13, 0)),
    ("You've hit your session limit · resets 12pm (America/Los_Angeles)", at(2026, 10, 13, 12)),
    ("You’ve hit your usage limit. Upgrade to Pro (https://x). Or try again at 10:03 PM.", at(2026, 10, 12, 22, 3)),
    ("try again at 8:08 AM.", at(2026, 10, 13, 8, 8)),
    ("try again at Oct 13th, 2026 3:04 AM.", at(2026, 10, 13, 3, 4)),
    ("resets Oct 14, 3pm", at(2026, 10, 14, 15)),
    ('{"message": "You\\u2019ve hit your usage limit. try again at 4:30 PM."}', at(2026, 10, 12, 16, 30)),
])
def test_parse_real_messages(text, expected):
    assert pl.parse_reset(text, NOW, LA) == expected


@pytest.mark.parametrize("text", [
    "", "something failed", "resets soon", "try again later", "resets 13pm", "resets 0am", "try again at 9:75 AM",
    "try again at Oct 40th, 2026 3:04 AM", "try again at Foo 3, 2026 3:04 AM",
    "resets Dec 30, 3pm",                          # more than eight days away is implausible
])
def test_unparseable_or_implausible_reset_is_none(text):
    assert pl.parse_reset(text, NOW, LA) is None


def test_unknown_time_zone_falls_back_to_the_local_one():
    assert pl.parse_reset("resets 4pm (Mars/Olympus_Mons)", NOW, LA) == at(2026, 10, 12, 16)


def test_clock_label_marks_other_days():
    assert pl.clock_label(NOW + 60, NOW).count(":") == 1
    assert "," in pl.clock_label(NOW + 2 * 86400, NOW)


# ------------------------------------------------------------------ grades and alternates


@pytest.mark.parametrize("model,expected", [
    ("claude-haiku-5-5", "light"), ("gpt-6-luna", "light"), ("claude-sonnet-5-5", "mid"), ("gpt-5.6-terra", "mid"),
    ("claude-opus-5-5", "top"), ("gpt-6.1-sol", "top"), ("gpt-6-astra", "top"), (None, "mid"), ("mystery", "mid"),
])
def test_tiers(model, expected):
    assert pl.tier(model) == expected


ROUTES = [{"agent": "claude", "model": "claude-haiku-5-5"}, {"agent": "codex", "model": "gpt-5.6-terra"},
          {"agent": "codex", "model": "gpt-6-luna"}, {"agent": "openclaw", "model": "openrouter/x:free"}]


def test_alternate_prefers_the_same_grade_and_never_a_limited_or_non_subscription_route():
    assert pl.alternate(ROUTES, "claude", "claude-haiku-5-5", set()) == {"agent": "codex", "model": "gpt-6-luna"}
    assert pl.alternate(ROUTES, "claude", "claude-sonnet-5-5", set()) == {"agent": "codex", "model": "gpt-5.6-terra"}
    assert pl.alternate(ROUTES, "claude", "claude-opus-5-5", set()) == {"agent": "codex", "model": "gpt-5.6-terra"}   # closest approved
    assert pl.alternate(ROUTES, "claude", "claude-haiku-5-5", {"codex"}) is None
    assert pl.alternate(ROUTES[:1] + ROUTES[3:], "claude", "claude-haiku-5-5", set()) is None
    assert pl.alternate([], "codex", "gpt-6-luna", set()) is None


# ------------------------------------------------------------------ events


def run_row(agent="claude", stage="failed", error=None, result=None, started=NOW, rid=1):
    return SimpleNamespace(id=rid, agent=agent, stage=stage, error=error, result_text=result, started_at=started)


def db(app):
    return app[1]


def test_observe_records_one_event_per_provider_and_extends_the_lift_time(app):
    s = db(app)
    msg = "You've hit your session limit · resets 4pm (America/Los_Angeles)"
    with s.begin() as d:
        r1 = run_row(error=msg)
        row = pl.observe(d, r1, NOW)
        assert row.provider == "claude" and row.lift_at == at(2026, 10, 12, 16) and row.rerouting is False
        assert "Limit lifts about" in r1.error                                        # the failed run itself says when
        r2 = run_row(error="You've hit your session limit · resets 5pm (America/Los_Angeles)", rid=2)
        pl.observe(d, r2, NOW + 60)
        assert d.scalar(select(ProviderLimit.id).where(ProviderLimit.provider == "claude")) is not None
        assert len(pl.active(d, NOW + 60)) == 1 and pl.active(d, NOW + 60)[0].lift_at == at(2026, 10, 12, 17)


def test_events_are_per_provider_and_end_by_themselves(app):
    s = db(app)
    with s.begin() as d:
        pl.observe(d, run_row("claude", error="session limit · resets 4pm (America/Los_Angeles)"), NOW)
        pl.observe(d, run_row("codex", error="You've hit your usage limit. try again at 8:08 PM.", rid=2), NOW)
        assert pl.limited_providers(d, NOW) == {"claude", "codex"}
        assert pl.limited_providers(d, at(2026, 10, 12, 16, 1)) == {"codex"}          # claude lifted at 4pm
        assert pl.limited_providers(d, at(2026, 10, 12, 21)) == set()


def test_a_later_success_ends_the_event(app):
    s = db(app)
    with s.begin() as d:
        pl.observe(d, run_row(error="session limit · resets 4pm (America/Los_Angeles)"), NOW)
        pl.observe(d, run_row(stage="succeeded", started=NOW - 600, rid=2), NOW + 5)      # started before: proves nothing
        assert pl.limited_providers(d, NOW + 5) == {"claude"}
        pl.observe(d, run_row(stage="succeeded", started=NOW + 10, rid=3), NOW + 20)
        assert pl.limited_providers(d, NOW + 20) == set()


def test_no_reset_time_expires_after_hours_and_plain_429_is_not_an_event(app):
    s = db(app)
    with s.begin() as d:
        assert pl.observe(d, run_row(error="HTTP 429 too many requests"), NOW) is None            # transient, no reset time
        assert pl.observe(d, run_row(error="rate limit, try again at 4:10 PM"), NOW) is not None   # a reset time makes it real
        pl.observe(d, run_row("codex", error="You've hit your usage limit.", rid=2), NOW)           # no reset time reported
        row = pl.active_row(d, "codex", NOW)
        assert row.lift_at is None and "Limit lifts" not in "You've hit your usage limit."
        assert pl.active_row(d, "codex", NOW + 5 * 3600) is not None
        assert pl.active_row(d, "codex", NOW + 7 * 3600) is None


def test_other_agents_and_stages_are_ignored(app):
    with db(app).begin() as d:
        assert pl.observe(d, run_row("openclaw", error="usage limit"), NOW) is None
        assert pl.observe(d, run_row(stage="cancelled", error="usage limit"), NOW) is None
        assert pl.observe(d, run_row(error="some other failure"), NOW) is None


# ------------------------------------------------------------------ rerouting through the dispatcher


def fallback_story(key="a", **kw):
    return dict(node(key), assignee="claude", model="claude-haiku-5-5", fallbacks=["codex"], **kw)


def story_ids(p):
    return [t["card_id"] for t in p["tasks"] if t["role"] == "story"]


def start_limit(app, rerouting, lift=None):
    with app[1].begin() as d:
        d.add(ProviderLimit(provider="claude", detected_at=int(time.time()) - 5, last_seen_at=int(time.time()) - 5,
                            lift_at=lift or int(time.time()) + 3600, rerouting=rerouting, handoffs=0, rerouted=0))


def test_story_is_rerouted_to_the_approved_same_grade_alternate_while_a_limit_lasts(app):
    p = active(app, [fallback_story("a")])
    c, s, wd, settings = app
    cid = story_ids(p)[0]
    start_limit(app, rerouting=True)
    assert len(Dispatcher(s, settings)._claim(1)) == 1
    with s() as d:
        card, run = d.get(Card, cid), d.scalar(select(Run).where(Run.card_id == cid))
        assert card.agent == "codex" and card.model                                        # an approved fallback, not a guess
        assert json.loads(run.checkpoint)["rerouted_from"]["agent"] == "claude"
        assert d.scalar(select(ProviderLimit)).rerouted == 1


def test_without_the_operator_choice_the_story_keeps_its_route(app):
    p = active(app, [fallback_story("a")])
    c, s, wd, settings = app
    cid = story_ids(p)[0]
    start_limit(app, rerouting=False)
    assert len(Dispatcher(s, settings)._claim(1)) == 1
    with s() as d:
        assert d.get(Card, cid).agent == "claude"
        checkpoint = json.loads(d.scalar(select(Run).where(Run.card_id == cid)).checkpoint)
        assert "rerouted_from" not in checkpoint and checkpoint["context_bytes"] > 1000        # the prompt size is recorded


def test_a_story_with_no_approved_alternate_stays_put(app):
    p = active(app, [dict(node("a"), assignee="claude", model="claude-haiku-5-5")])      # no fallbacks approved
    c, s, wd, settings = app
    cid = story_ids(p)[0]
    start_limit(app, rerouting=True)
    assert len(Dispatcher(s, settings)._claim(1)) == 1
    with s() as d:
        assert d.get(Card, cid).agent == "claude"


def test_an_expired_limit_no_longer_reroutes(app):
    p = active(app, [fallback_story("a")])
    c, s, wd, settings = app
    start_limit(app, rerouting=True, lift=int(time.time()) - 10)
    assert len(Dispatcher(s, settings)._claim(1)) == 1
    with s() as d:
        assert d.get(Card, story_ids(p)[0]).agent == "claude"


def test_automatic_handoff_on_a_limit_failure_is_counted(app):
    from tests.test_projects import finish
    p = active(app, [fallback_story("a")])
    c, s, wd, settings = app
    cid = story_ids(p)[0]
    assert len(Dispatcher(s, settings)._claim(1)) == 1
    rid = finish(app, cid, result="", stage="failed", error="You've hit your session limit · resets 11pm (America/Los_Angeles)")
    with s.begin() as d:                                                                    # the dispatcher records the event first
        pl.observe(d, d.get(Run, rid), int(time.time()))
        pl.note_handoff(d, "claude", int(time.time()))
    with s() as d:
        assert d.scalar(select(ProviderLimit)).handoffs == 1


# ------------------------------------------------------------------ API and payload


def test_limits_api_status_and_reroute_toggle(app):
    c, s, wd, settings = app
    assert c.get("/api/limits").json()["active"] == []
    assert c.post("/api/limits/claude/reroute", json={"enabled": True}).status_code == 404
    p = active(app, [fallback_story("a"), fallback_story("b")])
    start_limit(app, rerouting=False)
    item = c.get("/api/limits").json()["active"][0]
    assert item["provider"] == "claude" and item["name"] == "Claude Code" and item["alternate_name"] == "Codex"
    assert item["lift_at"] and 0 < item["seconds_left"] <= 3600 and item["lift_label"]
    assert item["rerouting"] is False and item["waiting"] >= 1 and item["can_reroute"] is True
    r = c.post("/api/limits/claude/reroute", json={"enabled": True})
    assert r.status_code == 200 and r.json()["active"][0]["rerouting"] is True
    assert c.post("/api/limits/claude/reroute", json={"enabled": False}).json()["active"][0]["rerouting"] is False
    assert c.post("/api/limits/gemini/reroute", json={"enabled": True}).status_code == 422
    assert c.post("/api/limits/claude/reroute", json={"enabled": True, "extra": 1}).status_code == 422


def test_cannot_reroute_to_a_limited_alternate(app):
    c, s, wd, settings = app
    now = int(time.time())
    with s.begin() as d:
        for prov in ("claude", "codex"):
            d.add(ProviderLimit(provider=prov, detected_at=now, last_seen_at=now, lift_at=now + 600,
                                rerouting=False, handoffs=0, rerouted=0))
    items = {i["provider"]: i for i in c.get("/api/limits").json()["active"]}
    assert items["claude"]["alternate_limited"] is True and items["claude"]["can_reroute"] is False


# ------------------------------------------------------------------ Hermes and Discord (identity comes from the gateway)

from tests.test_profiles import secured, paired, call, bridge, pref, signed, CHANNEL, USER      # noqa: E402,F401


def seed_limit(secured, rerouting=False):
    now = int(time.time())
    with secured.app.state.sessions.begin() as d:
        d.add(ProviderLimit(provider="claude", detected_at=now, last_seen_at=now, lift_at=now + 3000,
                            rerouting=rerouting, handoffs=2, rerouted=0))


def test_discord_can_read_limits_once_paired_but_not_change_them_by_default(secured, tmp_path):
    b, code = paired(secured, tmp_path)
    seed_limit(secured)
    r = call(b, "limits")
    assert r.status_code == 200 and r.json()["limits"]["active"][0]["provider"] == "claude"
    assert "once" in r.json()["instructions"]
    denied = call(b, "limits_reroute", provider="claude", enabled=True)
    assert denied.status_code == 403 and "Discord control" in denied.json()["detail"]


def test_discord_control_switch_allows_the_reroute_and_validates_input(secured, tmp_path):
    b, code = paired(secured, tmp_path, allow_discord_control=True)
    seed_limit(secured)
    assert call(b, "limits_reroute", provider="claude").status_code == 422             # on or off is required
    assert call(b, "limits_reroute", enabled=True).status_code == 422                  # so is the provider
    r = call(b, "limits_reroute", provider="claude", enabled=True)
    assert r.status_code == 200 and r.json()["limits"]["active"][0]["rerouting"] is True
    assert call(b, "limits_reroute", provider="codex", enabled=True).status_code == 404   # no active codex limit
    assert call(b, "limits_reroute", provider="gemini", enabled=True).status_code == 422


def test_another_discord_account_gets_nothing(secured, tmp_path):
    b, code = paired(secured, tmp_path, allow_discord_control=True)
    seed_limit(secured)
    stranger = {"discord_user_id": "999999999999999999", "discord_channel_id": CHANNEL, "source_message_id": "345678901234567890"}
    assert b.post("/api/hermes-projects", json={"action": "limits", **stranger}).status_code == 403
    assert b.post("/api/hermes-projects", json={"action": "limits_reroute", "provider": "claude", "enabled": True, **stranger}).status_code == 403
