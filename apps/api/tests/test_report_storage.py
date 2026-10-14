import json
import os
from pathlib import Path

import pytest
from report_storage import ReportStorage
from reports import ReportsReader
from settings import Settings


def install(tmp_path, **kwargs):
    data = tmp_path / "runtime"
    data.mkdir(exist_ok=True)
    return Settings(_env_file=None, data_dir=data, **kwargs)


def test_defaults_follow_installation_and_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("MAC_CONTROL_OPS_REPORTS_DIR", raising=False)
    settings = install(tmp_path)
    assert settings.reports_path == settings.data_dir / "reports"
    monkeypatch.setenv("MAC_CONTROL_OPS_REPORTS_DIR", str(tmp_path / "explicit"))
    assert Settings(_env_file=None, data_dir=tmp_path).reports_path == tmp_path / "explicit"
    monkeypatch.setenv("MAC_CONTROL_HERMES_REPORTS_DIR", str(tmp_path / "archive"))
    assert Settings(_env_file=None).hermes_reports_dir == tmp_path / "archive"


def test_configure_persist_reset_and_read_only(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    (approved / "status.md").write_text("Safe report")
    settings = install(tmp_path, reports_allowed_roots=(approved,))
    storage = ReportStorage(settings)
    assert storage.status()["sources"][0]["mode"] == "default"
    assert storage.status()["sources"][0]["state"] == "unavailable"
    storage.configure(str(approved), "")
    restored = ReportStorage(settings)
    assert restored.status()["sources"][0]["mode"] == "configured"
    row = restored.catalog()["reports"][0]
    assert restored.read(row["id"])["content"] == "Safe report"
    assert sorted(p.name for p in approved.iterdir()) == ["status.md"]
    assert (settings.data_dir / "report-storage.json").stat().st_mode & 0o777 == 0o600
    restored.configure("", "", reset=True)
    assert ReportStorage(settings).status()["sources"][0]["mode"] == "default"


def test_rejects_unapproved_secrets_and_symlink_ancestors(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    settings = install(tmp_path, reports_allowed_roots=(approved,))
    storage = ReportStorage(settings)
    for name in (".ssh", ".aws", ".codex", ".openclaw", "credentials", "secrets", "config", "agent-tokens"):
        (approved / name).mkdir()
        with pytest.raises(ValueError):
            storage.configure(str(approved / name), "")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("DO NOT READ")
    (approved / "alias").symlink_to(outside, target_is_directory=True)
    for path in (outside, approved / "alias", approved / "alias" / "absent", approved / ".." / "outside", Path("relative")):
        with pytest.raises(ValueError):
            storage.configure(str(path), "")
    (outside / "nested").mkdir()
    assert not ReportsReader(approved / "alias" / "nested").catalog()["available"]
    assert not (settings.data_dir / "report-storage.json").exists()


def test_secret_entries_and_post_save_replacement_are_blocked(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    (approved / "credentials.txt").write_text("DO NOT READ")
    (approved / "secrets").mkdir()
    (approved / "secrets" / "private.md").write_text("DO NOT READ")
    (approved / "safe.md").write_text("okay")
    settings = install(tmp_path, reports_allowed_roots=(approved,))
    storage = ReportStorage(settings)
    storage.configure(str(approved), "")
    assert [r["name"] for r in storage.catalog()["reports"]] == ["safe.md"]
    approved.rename(tmp_path / "renamed")
    approved.symlink_to(tmp_path / "renamed", target_is_directory=True)
    assert storage.catalog()["reports"] == []


def test_invalid_saved_configuration_fails_closed(tmp_path):
    settings = install(tmp_path)
    (settings.data_dir / "reports").mkdir()
    (settings.data_dir / "reports" / "safe.md").write_text("okay")
    (settings.data_dir / "report-storage.json").write_text(json.dumps({"ops": "/unapproved"}))
    storage = ReportStorage(settings)
    assert storage.catalog()["reports"] == [] and storage.status()["error"]
    storage.configure("", "", reset=True)
    assert storage.catalog()["reports"]


def test_operator_only_endpoint_and_sanitized_errors(make_client):
    client = make_client()
    signed_in = False
    agent = False
    @client.app.middleware("http")
    async def operator_session(request, call_next):
        if signed_in:
            request.state.user = {"email": "operator@example.invalid"}
        if agent:
            request.state.agent_grant = {"id": "test"}
        return await call_next(request)
    with client:
        assert client.get("/api/report-storage").status_code == 403
        assert client.put("/api/report-storage", json={"ops": "/secret", "hermes": "", "reset": False}).status_code == 403
        signed_in = True
        assert client.get("/api/report-storage").status_code == 200
        response = client.put("/api/report-storage", json={"ops": "/credential-secret-value", "hermes": "", "reset": False})
        assert response.status_code == 422
        assert "credential-secret-value" not in response.text
        assert client.put("/api/report-storage", json={"ops": [], "hermes": "", "reset": False}).status_code == 422
        assert client.put("/api/report-storage", json={"ops": "", "hermes": "", "reset": True}).status_code == 200
        agent = True
        assert client.get("/api/report-storage").status_code == 403
        assert client.put("/api/report-storage", json={"ops": "", "hermes": "", "reset": True}).status_code == 403
