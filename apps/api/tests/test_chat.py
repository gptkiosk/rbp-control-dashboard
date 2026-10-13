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
