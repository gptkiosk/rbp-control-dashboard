"""Human tasks, tags, priority/due/estimate, dependencies and Hermes attribution."""

from __future__ import annotations

import asyncio

from sqlalchemy import update

from dispatcher import Dispatcher
from models import Card
from tests.test_dispatcher import SUCCESS, _drain, _registry, _settings


def _agent(client, tmp_path, **kw):
    data = {"title": "Agent task", "body": "Summarize", "agent": "claude",
            "working_dir": str(tmp_path / "ws" / "proj"), **kw}
    r = client.post("/api/cards", json=data)
    assert r.status_code == 201, r.text
    return r.json()


def _human(client, **kw):
    r = client.post("/api/cards", json={"title": "Review the PR", "assignee_type": "human", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_human_task_has_no_agent_and_needs_no_approval(make_client):
    client = make_client()
    c = _human(client, body="Deploy and email the team when done", acceptance="PR merged; team told",
               priority="high", due_date="2026-10-20", estimate_minutes=90, tags=["Release", "  ops  "])
    assert c["assignee_type"] == "human" and c["agent"] is None and c["working_dir"] is None
    assert c["needs_approval"] is False  # outward keywords only gate agent work
    assert c["tags"] == ["release", "ops"] and c["priority"] == "high" and c["due_date"] == "2026-10-20"
    assert c["acceptance"] == "PR merged; team told" and c["estimate_minutes"] == 90


def test_human_can_move_own_task_to_running_agent_cannot(make_client, tmp_path):
    client = make_client()
    h = _human(client)
    assert client.patch(f"/api/cards/{h['id']}", json={"column": "running"}).json()["column"] == "running"
    assert client.patch(f"/api/cards/{h['id']}", json={"column": "done"}).json()["column"] == "done"
    a = _agent(client, tmp_path)
    assert client.patch(f"/api/cards/{a['id']}", json={"column": "running"}).status_code == 409


def test_human_task_cannot_be_approved(make_client):
    client = make_client()
    h = _human(client)
    assert client.post(f"/api/cards/{h['id']}/approve").status_code == 409


def test_field_validation(make_client, tmp_path):
    client = make_client()
    for bad in ({"priority": "asap"}, {"due_date": "next week"}, {"estimate_minutes": 0},
                {"tags": ["bad/tag"]}, {"tags": [f"t{i}" for i in range(11)]}):
        r = client.post("/api/cards", json={"title": "x", "assignee_type": "human", **bad})
        assert r.status_code == 422, bad
    assert client.post("/api/cards", json={"title": "x", "assignee_type": "agent"}).status_code == 422


def test_tags_endpoint_counts(make_client):
    client = make_client()
    _human(client, tags=["ops", "release"])
    _human(client, tags=["ops"])
    assert client.get("/api/tags").json()["tags"] == [{"tag": "ops", "count": 2}, {"tag": "release", "count": 1}]


def test_dependencies_and_cycles(make_client, tmp_path):
    client = make_client()
    a = _human(client, title="A")
    b = _agent(client, tmp_path, title="B", depends_on=[a["id"]])
    assert b["depends_on"] == [a["id"]] and b["blocked_by"] == [a["id"]]
    assert client.get(f"/api/cards/{a['id']}").json()["dependents"] == [b["id"]]
    r = client.post(f"/api/cards/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    assert r.status_code == 422 and "cycle" in r.json()["detail"]
    assert client.post(f"/api/cards/{a['id']}/dependencies", json={"depends_on_id": a["id"]}).status_code == 422
    assert client.post(f"/api/cards/{a['id']}/dependencies", json={"depends_on_id": 9999}).status_code == 422
    client.patch(f"/api/cards/{a['id']}", json={"column": "done"})
    assert client.get(f"/api/cards/{b['id']}").json()["blocked_by"] == []
    out = client.delete(f"/api/cards/{b['id']}/dependencies/{a['id']}").json()
    assert out["depends_on"] == []


def test_longer_cycle_is_rejected(make_client):
    client = make_client()
    a, b, c = (_human(client, title=t) for t in "ABC")
    client.post(f"/api/cards/{b['id']}/dependencies", json={"depends_on_id": a["id"]})
    client.post(f"/api/cards/{c['id']}/dependencies", json={"depends_on_id": b["id"]})
    r = client.post(f"/api/cards/{a['id']}/dependencies", json={"depends_on_id": c["id"]})
    assert r.status_code == 422


def test_dispatcher_waits_for_dependencies_and_skips_human_tasks(make_client, tmp_path):
    client = make_client()
    sessions = client.app.state.sessions
    blocker = _human(client, title="Human prep")
    with sessions.begin() as s:
        s.execute(update(Card).where(Card.id == blocker["id"]).values(column="queued"))
    agent = _agent(client, tmp_path, title="Agent work", depends_on=[blocker["id"]])
    with sessions.begin() as s:
        s.execute(update(Card).where(Card.id == agent["id"]).values(agent="fake", body=SUCCESS, column="queued"))
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    assert asyncio.run(d.tick()) == 0  # human task never runs; agent task is blocked
    client.patch(f"/api/cards/{blocker['id']}", json={"column": "done"})
    asyncio.run(_drain(d))
    assert client.get(f"/api/cards/{agent['id']}").json()["column"] == "done"
    assert client.get(f"/api/cards/{blocker['id']}").json()["column"] == "done"


def test_hermes_attribution_header(make_client):
    client = make_client()
    r = client.post("/api/cards", json={"title": "From Hermes", "assignee_type": "human"},
                    headers={"X-MCD-Actor": "hermes"})
    assert r.json()["created_by"] == "hermes"
    assert _human(client)["created_by"] == "operator"


def test_switching_to_human_clears_agent_fields(make_client, tmp_path):
    client = make_client()
    a = _agent(client, tmp_path, body="git push it")
    assert a["needs_approval"] is True
    h = client.patch(f"/api/cards/{a['id']}", json={"assignee_type": "human"}).json()
    assert h["agent"] is None and h["working_dir"] is None and h["needs_approval"] is False
