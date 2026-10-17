"""Chat tests with a fake agent (tests only). The fake replies with the session id it was given,
so we can prove the second turn resumes the first turn's session."""

from __future__ import annotations

import json
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

import agents
from dispatcher import Dispatcher
from tests.test_dispatcher import FakeParser


class SessionParser(FakeParser):
    def feed(self, line):
        ev = agents._json(line)
        if ev and ev.get("type") == "result":
            self.meta.session_id = ev.get("session")
        return super().feed(line)


def _build(ctx, prompt, model, budget, binary, session_id=None):
    # The prompt is either "sleep" or plain text. The fake reports session S1 on a new session
    # and echoes back whatever session it was asked to resume.
    if prompt == "sleep":
        return [sys.executable, "-c", "import time;time.sleep(60)"]
    session = session_id or "S1"
    payload = json.dumps({"type": "result", "model": "fake-model", "in": 7, "out": 2,
                          "text": f"resumed={session_id}", "session": session})
    return [sys.executable, "-c", f"print({payload!r})"]


@pytest.fixture
def tc(make_client, tmp_path, monkeypatch):
    """A client whose dispatcher runs the fake agent; registry and client are restored after."""
    client = make_client()
    from settings import get_settings   # RCD ships free-only; the fake agent runs through the paid path
    for name, value in (("dispatch_free_only", False), ("default_budget_usd", 1.0), ("dispatch_max_budget_usd", 1.0)):
        monkeypatch.setattr(get_settings(), name, value)
    spec = agents.AgentSpec("fake", "Fake", "worker", "claude_path", _build, SessionParser)
    import routes.chat as chat_routes
    monkeypatch.setattr(chat_routes, "REGISTRY", {**agents.REGISTRY, "fake": spec})
    with TestClient(client.app, headers={"X-Mac-Control": "1"}) as test_client:
        client.app.state.dispatcher = Dispatcher(client.app.state.sessions, _settings(tmp_path),
                                                 registry={"fake": spec})
        yield test_client


def _settings(tmp_path):
    from types import SimpleNamespace
    # The price gate (SEC-013) needs an explicit model with a reviewed route class, as for any real agent.
    return SimpleNamespace(runs_dir=tmp_path / "runs", max_concurrent_runs=2, default_budget_usd=1.0,
                           claude_path=sys.executable, run_retention_days=90, dispatch_free_only=False,
                           dispatch_max_budget_usd=1.0, dispatch_route_classes={"fake||fake-model": "free"})


def _wait(tc, tid, pred, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        data = tc.get(f"/api/chat/threads/{tid}").json()
        if pred(data):
            return data
        time.sleep(0.2)
    raise AssertionError(f"timed out: {data}")


def _thread(tc, tmp_path, **kw):
    body = {"agent": "fake", "model": "fake-model", "working_dir": str(tmp_path / "ws" / "proj"), **kw}
    r = tc.post("/api/chat/threads", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _idle(d):
    return not d["busy"] and all(m["status"] != "running" for m in d["messages"])


def test_two_turns_resume_the_same_session(tc, tmp_path):
    t = _thread(tc, tmp_path)
    assert t["session_id"] is None
    assert tc.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "hello"}).status_code == 201
    d = _wait(tc, t["id"], lambda d: _idle(d) and len(d["messages"]) == 2)
    assert d["session_id"] == "S1"
    assert d["messages"][1]["text"] == "resumed=None"
    assert d["messages"][1]["model"] == "fake-model" and d["messages"][1]["input_tokens"] == 7
    tc.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "again"})
    d = _wait(tc, t["id"], lambda d: _idle(d) and len(d["messages"]) == 4)
    assert d["messages"][3]["text"] == "resumed=S1"  # second turn resumed the first session


def test_message_needing_approval_waits(tc, tmp_path):
    t = _thread(tc, tmp_path)
    m = tc.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "then git push the fix"}).json()
    assert m["status"] == "pending_approval" and m["approval_reasons"] == ["prompt pushes or merges code"]
    time.sleep(0.5)
    assert len(tc.get(f"/api/chat/threads/{t['id']}").json()["messages"]) == 1  # nothing ran
    assert tc.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "x"}).status_code == 409
    tc.post(f"/api/chat/messages/{m['id']}/approve")
    d = _wait(tc, t["id"], lambda d: _idle(d) and len(d["messages"]) == 2)
    assert d["messages"][0]["status"] == "done"


def test_background_sent_with_a_message_is_not_the_operators_words(tc, tmp_path):
    """The project consultant opens with long guidance that mentions releases and deploys. That background must reach the agent and must not
    put the operator's own first message behind an approval that nobody knows to give."""
    t = _thread(tc, tmp_path)
    background = "Guidance for the consultant: describe how the app is released, deployed and published. Ask about the release model."
    m = tc.post(f"/api/chat/threads/{t['id']}/messages", json={"context": background, "text": "Project: Notes app. Goal: a small notes app."}).json()
    assert m["status"] == "running" and m["approval_reasons"] == []
    assert m["text"] == "Project: Notes app. Goal: a small notes app." and m["context_chars"] == len(background)
    d = _wait(tc, t["id"], lambda d: _idle(d) and len(d["messages"]) == 2)
    assert d["messages"][0]["text"] == "Project: Notes app. Goal: a small notes app."     # the bubble shows only the operator's words
    # the operator's own words are still checked
    pushed = tc.post(f"/api/chat/threads/{t['id']}/messages", json={"context": background, "text": "then git push the fix"}).json()
    assert pushed["status"] == "pending_approval"


def test_a_route_nobody_reviewed_is_refused_up_front_with_a_way_forward(tc, tmp_path):
    """With "Require a reviewed price" on in Spending & limits, a chat on a model nobody reviewed is refused up front. Off (the default) it is accepted."""
    off = tc.post("/api/chat/threads", json={"agent": "fake", "model": "unreviewed-model", "working_dir": str(tmp_path / "ws" / "proj")})
    assert off.status_code == 201                                                     # the default: no spending check, the chat starts
    tc.delete(f"/api/chat/threads/{off.json()['id']}")
    tc.patch("/api/billing", json={"limits": {"require_reviewed_pricing": True}})
    r = tc.post("/api/chat/threads", json={"agent": "fake", "model": "unreviewed-model", "working_dir": str(tmp_path / "ws" / "proj")})
    assert r.status_code == 409 and "not been reviewed for pricing" in r.json()["detail"] and "AI defaults" in r.json()["detail"]
    assert tc.get("/api/chat/threads").json()["threads"] == []                      # no empty thread is left behind
    t = _thread(tc, tmp_path)
    tc.app.state.dispatcher.settings.dispatch_route_classes.clear()                  # the review is revoked after the thread exists
    r = tc.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "hello"})
    assert r.status_code == 409 and "cannot run fake-model" in r.json()["detail"]
    assert tc.get(f"/api/chat/threads/{t['id']}").json()["messages"] == []


def test_the_generic_free_alias_becomes_the_model_the_agent_is_set_up_with(tc, tmp_path):
    """Hermes lists thinkingmachines/inkling:free, not openrouter/free. The dashboard default used to be refused with PRICE_UNKNOWN."""
    cfg = tmp_path / "hermes.yaml"
    cfg.write_text("model:\n  default: thinkingmachines/inkling:free\nfallback_providers:\n  - model: google/gemini-2.5-flash\n")
    st = tc.app.state.dispatcher.settings
    st.environment, st.hermes_config_path, st.openclaw_config_path = "prod", str(cfg), None
    st.dispatch_route_classes = {}
    tc.patch("/api/billing", json={"limits": {"require_reviewed_pricing": True}})
    import routes.chat as chat
    from types import SimpleNamespace
    req = SimpleNamespace(app=tc.app)
    with tc.app.state.sessions() as s:
        assert chat.resolve_model(s, req, "hermes", None, "openrouter/free") == "thinkingmachines/inkling:free"
        assert chat.resolve_model(s, req, "hermes", None, None) == "thinkingmachines/inkling:free"
        assert chat.resolve_model(s, req, "hermes", None, "google/gemini-2.5-flash") == "google/gemini-2.5-flash"   # a named model is never swapped
        assert chat.resolve_model(s, req, "claude", None, "openrouter/free") == "openrouter/free"                    # only hermes and openclaw
        assert chat.route_problem(s, req, "hermes", None, "thinkingmachines/inkling:free") is None
        assert "not been reviewed" in chat.route_problem(s, req, "hermes", None, "openrouter/free")
        cfg.write_text("model:\n  default: google/gemini-2.5-flash\n")                                              # a paid default is never chosen for you
        assert chat.resolve_model(s, req, "hermes", None, "openrouter/free") == "openrouter/free"


def test_reject_pending_message(tc, tmp_path):
    t = _thread(tc, tmp_path)
    m = tc.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "deploy it"}).json()
    assert tc.post(f"/api/chat/messages/{m['id']}/reject").json()["status"] == "cancelled"


def test_busy_and_stop(tc, tmp_path):
    t = _thread(tc, tmp_path)
    tc.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "sleep"})
    _wait(tc, t["id"], lambda d: d["busy"])
    assert tc.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "x"}).status_code == 409
    assert tc.delete(f"/api/chat/threads/{t['id']}").status_code == 409
    assert tc.post(f"/api/chat/threads/{t['id']}/stop").status_code == 200
    d = _wait(tc, t["id"], lambda d: _idle(d) and len(d["messages"]) == 2)
    assert d["messages"][0]["status"] == "cancelled"
    assert d["messages"][1]["role"] == "assistant" and "cancelled" in d["messages"][1]["text"]


def test_preassigned_session_for_openclaw(tc, tmp_path):
    t = tc.post("/api/chat/threads", json={"agent": "openclaw", "working_dir": str(tmp_path / "ws" / "proj")}).json()
    assert t["session_id"] and len(t["session_id"]) == 36


def test_thread_validation(tc, tmp_path):
    assert tc.post("/api/chat/threads", json={"agent": "fake", "working_dir": "/etc"}).status_code == 422
    assert tc.post("/api/chat/threads", json={"agent": "nope", "working_dir": str(tmp_path)}).status_code == 422


def test_delete_thread_removes_logs(tc, tmp_path):
    t = _thread(tc, tmp_path)
    tc.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "hello"})
    d = _wait(tc, t["id"], lambda d: _idle(d) and len(d["messages"]) == 2)
    run_id = d["messages"][1]["run_id"]
    log = tmp_path / "runs" / f"run-{run_id}.log"
    assert log.exists()
    assert tc.delete(f"/api/chat/threads/{t['id']}").status_code == 204
    assert not log.exists() and not os.path.exists(str(log).replace(".log", ".raw.log"))


def test_a_task_or_planner_on_the_free_default_is_resolved_where_it_is_created_and_where_it_starts(tc, tmp_path):
    """The plan run for a project failed with PRICE_UNKNOWN because its card carried openrouter/free, not a model Hermes lists."""
    import cards
    from dispatch_gate import resolve_free_alias
    cfg = tmp_path / "hermes.yaml"
    cfg.write_text("model:\n  default: thinkingmachines/inkling:free\n")
    st = tc.app.state.dispatcher.settings
    st.environment, st.hermes_config_path, st.openclaw_config_path = "prod", str(cfg), None
    st.dispatch_route_classes = {}
    st.workdir_roots, st.default_timeout_s = (tmp_path / "ws",), 600
    with tc.app.state.sessions.begin() as s:
        card = cards.create(s, {"title": "plan", "body": "Plan it.", "agent": "hermes", "model": "openrouter/free", "working_dir": str(tmp_path / "ws" / "proj")}, st)
        assert card.model == "thinkingmachines/inkling:free" and card.route_tier == "free"
        named = cards.create(s, {"title": "named", "body": "Do it.", "agent": "hermes", "model": "google/gemini-2.5-flash", "working_dir": str(tmp_path / "ws" / "proj")}, st)
        assert named.model == "google/gemini-2.5-flash"
        cards.edit(s, named, {"model": "openrouter/free"}, st)
        assert named.model == "thinkingmachines/inkling:free"
        assert resolve_free_alias(s, st, "claude", None, "openrouter/free") == "openrouter/free"
