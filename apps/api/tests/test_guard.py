from __future__ import annotations

from fastapi.testclient import TestClient


def _raw(make_client) -> TestClient:
    """A client without the guard header, to exercise refusals."""
    client = make_client()
    return TestClient(client.app)


def test_foreign_host_refused_even_for_get(make_client):
    client = make_client()
    r = client.get("/healthz", headers={"host": "evil.example"})
    assert r.status_code == 403
    assert "host" in r.json()["detail"]


def test_loopback_host_allowed_for_get(make_client):
    client = make_client()
    assert client.get("/healthz", headers={"host": "127.0.0.1:8800"}).status_code == 200


def test_state_change_needs_header(make_client):
    raw = _raw(make_client)
    r = raw.post("/api/cards", json={}, headers={"host": "127.0.0.1:8800"})
    assert r.status_code == 403
    assert "X-Mac-Control" in r.json()["detail"]


def test_cross_origin_post_refused_even_with_header(make_client):
    client = make_client()
    r = client.post("/api/cards", json={}, headers={
        "host": "127.0.0.1:8800", "origin": "https://evil.example", "X-Mac-Control": "1"})
    assert r.status_code == 403
    assert "origin" in r.json()["detail"]


def test_same_origin_post_passes_guard(make_client):
    client = make_client()
    r = client.post("/api/cards", json={}, headers={
        "host": "127.0.0.1:8800", "origin": "http://127.0.0.1:8800", "X-Mac-Control": "1"})
    assert r.status_code == 422  # reached validation: the guard let it through


def test_dev_server_origin_allowed(make_client):
    client = make_client()
    r = client.post("/api/cards", json={}, headers={
        "host": "127.0.0.1:5173", "origin": "http://127.0.0.1:5173", "X-Mac-Control": "1"})
    assert r.status_code == 422
