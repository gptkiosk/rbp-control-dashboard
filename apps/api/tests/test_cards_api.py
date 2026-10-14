from __future__ import annotations

import subprocess

from sqlalchemy import update

from models import Card


def _workdir(tmp_path):
    return str(tmp_path / "ws" / "proj")


def _new(client, tmp_path, **kw):
    data = {"title": "Summarize", "body": "Summarize the README", "agent": "claude",
            "working_dir": _workdir(tmp_path), **kw}
    return client.post("/api/cards", json=data)


def test_create_card_lands_in_backlog(make_client, tmp_path):
    client = make_client()
    r = _new(client, tmp_path)
    assert r.status_code == 201
    card = r.json()
    assert card["column"] == "backlog"
    assert card["needs_approval"] is False
    assert card["mode"] == "read"
    assert card["timeout_s"] == 1800


def test_rejects_unknown_agent_and_outside_dir(make_client, tmp_path):
    client = make_client()
    assert _new(client, tmp_path, agent="skynet").status_code == 422
    assert _new(client, tmp_path, working_dir="/etc").status_code == 422
    assert _new(client, tmp_path, mode="root").status_code == 422


def test_queue_without_approval_needed(make_client, tmp_path):
    client = make_client()
    card = _new(client, tmp_path).json()
    r = client.patch(f"/api/cards/{card['id']}", json={"column": "queued"})
    assert r.json()["column"] == "queued"


def test_card_needing_approval_goes_to_review_then_queued(make_client, tmp_path):
    client = make_client()
    card = _new(client, tmp_path, body="Write the fix and git push it").json()
    assert card["needs_approval"] is True
    assert card["approval_reasons"] == ["prompt pushes or merges code"]
    moved = client.patch(f"/api/cards/{card['id']}", json={"column": "queued"}).json()
    assert moved["column"] == "review"
    shown = {"challenge": moved["approval_challenge"], "pin": moved["approval_pin"]}
    approved = client.post(f"/api/cards/{card['id']}/approve", json=shown).json()
    assert approved["column"] == "queued" and approved["approved_at"]


def test_editing_prompt_clears_approval(make_client, tmp_path):
    client = make_client()
    card = _new(client, tmp_path, body="deploy the site").json()
    client.post(f"/api/cards/{card['id']}/approve",
                json={"challenge": card["approval_challenge"], "pin": card["approval_pin"]})
    edited = client.patch(f"/api/cards/{card['id']}", json={"body": "deploy the site and email the team"}).json()
    assert edited["approved_at"] is None
    assert edited["column"] == "review"
    assert "prompt contacts a person" in edited["approval_reasons"]


def test_edit_mode_on_main_branch_needs_approval(make_client, tmp_path):
    client = make_client()
    subprocess.run(["git", "init", "-q", "-b", "main", _workdir(tmp_path)], check=True)
    card = _new(client, tmp_path, mode="edit", body="tidy up imports").json()
    assert card["approval_reasons"] == ["edits a repo on its main branch"]


def test_cannot_move_into_running(make_client, tmp_path):
    client = make_client()
    card = _new(client, tmp_path).json()
    assert client.patch(f"/api/cards/{card['id']}", json={"column": "running"}).status_code == 409


def test_running_card_is_locked(make_client, tmp_path):
    client = make_client()
    card = _new(client, tmp_path).json()
    with client.app.state.sessions.begin() as s:
        s.execute(update(Card).where(Card.id == card["id"]).values(column="running"))
    cid = card["id"]
    assert client.patch(f"/api/cards/{cid}", json={"column": "backlog"}).status_code == 409
    assert client.patch(f"/api/cards/{cid}", json={"body": "x"}).status_code == 409
    assert client.delete(f"/api/cards/{cid}").status_code == 409


def test_approve_rejects_card_that_needs_none(make_client, tmp_path):
    client = make_client()
    card = _new(client, tmp_path).json()
    assert client.post(f"/api/cards/{card['id']}/approve").status_code == 409


def test_delete_and_list(make_client, tmp_path):
    client = make_client()
    a = _new(client, tmp_path).json()
    _new(client, tmp_path, title="Second").json()
    assert len(client.get("/api/cards").json()["cards"]) == 2
    assert client.delete(f"/api/cards/{a['id']}").status_code == 204
    assert len(client.get("/api/cards").json()["cards"]) == 1


def test_subscription_routes_are_off_until_the_operator_saves_them(make_client):
    client = make_client()
    agents = client.get("/api/agents").json()["agents"]
    assert [a["id"] for a in agents if a["subscription_configured"]] == []


def test_agents_and_workdirs(make_client, tmp_path):
    client = make_client()
    agents = {a["id"]: a for a in client.get("/api/agents").json()["agents"]}
    assert set(agents) == {"claude", "codex", "grok", "hermes", "openclaw"}
    assert agents["hermes"]["role"] == "manager"
    paths = [w["path"] for w in client.get("/api/workdirs").json()["workdirs"]]
    assert any(p.endswith("/ws/proj") for p in paths)
