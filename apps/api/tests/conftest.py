"""Test fixtures: every test gets its own data dir and web build dir."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))


@pytest.fixture(autouse=True)
def isolated_auth_default(monkeypatch):
    """Live auth configuration must not change test defaults; secured fixtures opt in."""
    monkeypatch.setenv("MAC_CONTROL_AUTH_ENABLED", "false")
    from settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    """Build a fresh app against temporary paths. `built` controls whether a web build exists."""

    def _make(built: bool = True) -> TestClient:
        data_dir = tmp_path / "data"
        dist = tmp_path / "dist"
        if built:
            (dist / "assets").mkdir(parents=True)
            (dist / "index.html").write_text("<!doctype html><title>mac-control</title>")
            (dist / "assets" / "app.js").write_text("console.log('ok')")
            (dist / "favicon.svg").write_text("<svg/>")
        monkeypatch.setenv("MAC_CONTROL_ENVIRONMENT", "test")
        monkeypatch.setenv("MAC_CONTROL_DATA_DIR", str(data_dir))
        monkeypatch.setenv("MAC_CONTROL_WEB_DIST", str(dist))
        monkeypatch.setenv("MAC_CONTROL_COLLECTOR_ENABLED", "false")
        monkeypatch.setenv("MAC_CONTROL_DISPATCHER_ENABLED", "false")
        # The operator's own ~/.rcd-control/.env is read by Settings; pin what tests assert on so it cannot leak in.
        monkeypatch.setenv("MAC_CONTROL_ORGANIZATION_NAME", "RCD")
        monkeypatch.setenv("MAC_CONTROL_PRODUCT_NAME", "Raspberry Pi Control Dashboard")
        monkeypatch.setenv("MAC_CONTROL_ALLOWED_HOSTS_EXTRA", '["testserver"]')
        workspace = tmp_path / "ws"
        (workspace / "proj").mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("MAC_CONTROL_WORKDIR_ROOTS", f'["{workspace}"]')

        import settings

        settings.get_settings.cache_clear()
        import main

        return TestClient(main.create_app(), headers={"X-Mac-Control": "1"})

    yield _make

    import settings

    settings.get_settings.cache_clear()


@pytest.fixture
def sessions(tmp_path):
    """A migrated temporary database and its session factory."""
    from db import make_engine, make_session_factory
    from migrate import upgrade_to_head

    engine = make_engine(tmp_path / "test.db")
    upgrade_to_head(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def subscriptions(monkeypatch):
    """RCD ships free-only: no Claude or Codex subscription exists until the operator saves one.
    Tests of subscription flows opt in with this fixture."""
    import billing
    monkeypatch.setattr(billing, "DEFAULT_ACCOUNTS", {**billing.DEFAULT_ACCOUNTS,
                        "claude": {"mode": "subscription", "monthly_usd": 20.0},
                        "codex": {"mode": "subscription", "monthly_usd": 20.0}})
