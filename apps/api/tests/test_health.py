from __future__ import annotations

from version import __version__


def test_healthz_reports_ok_and_version(make_client):
    client = make_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["data_dir_writable"] is True
    assert body["web_built"] is True


def test_healthz_reports_missing_build(make_client):
    body = make_client(built=False).get("/healthz").json()
    assert body["web_built"] is False


def test_security_headers_present(make_client):
    response = make_client().get("/healthz")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"


def test_data_dir_created_private(make_client, tmp_path):
    make_client()
    data_dir = tmp_path / "data"
    assert data_dir.is_dir()
    assert oct(data_dir.stat().st_mode & 0o777) == "0o700"
