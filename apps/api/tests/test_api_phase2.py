from __future__ import annotations

import time

from sqlalchemy import insert

from models import MetricSample, ServiceSnapshot


def _app_sessions(client):
    return client.app.state.sessions


def test_release_envelope(make_client):
    body = make_client().get("/api/release").json()
    assert body["owner"] == "RCD"
    assert body["product"] == "Raspberry Pi Control Dashboard"
    assert body["owner"] == "Bamcio LLC"
    assert body["product_short"] == "RCD"
    assert body["environment"] == "test"
    assert body["has_migrations"] is False


def test_current_503_before_first_sample(make_client):
    assert make_client().get("/api/metrics/current").status_code == 503


def test_current_derives_percentages(make_client):
    client = make_client()
    with _app_sessions(client).begin() as s:
        s.execute(insert(MetricSample), [{
            "ts": int(time.time()), "cpu_pct": 20.0, "mem_used": 8.0, "mem_total": 16.0,
            "swap_used": 1.0, "swap_total": 4.0, "disk_used": 50.0, "disk_total": 200.0,
            "pressure_level": 2.0,
        }])
    body = client.get("/api/metrics/current").json()
    assert body["mem_used_pct"] == 50.0
    assert body["swap_used_pct"] == 25.0
    assert body["disk_used_pct"] == 25.0
    assert body["pressure_label"] == "warning"
    assert body["macmon_status"] == "disabled"
    assert body["disk_days_to_full"] is None  # needs a day of history


def test_series_rejects_unknown_fields(make_client):
    client = make_client()
    assert client.get("/api/metrics/series?fields=cpu_pct,rm_rf").status_code == 422
    assert client.get("/api/metrics/series?range=1h&fields=cpu_pct_max").status_code == 422
    assert client.get("/api/metrics/series?range=2w").status_code == 422


def test_series_returns_columns(make_client):
    client = make_client()
    now = int(time.time())
    with _app_sessions(client).begin() as s:
        s.execute(insert(MetricSample), [
            {"ts": now - 25, "cpu_pct": 10.0, "gpu_pct": 1.0},
            {"ts": now - 15, "cpu_pct": 30.0, "gpu_pct": 3.0},
        ])
    body = client.get("/api/metrics/series?range=1h&fields=cpu_pct,gpu_pct").json()
    assert body["step_s"] == 10
    assert len(body["series"]["ts"]) == len(body["series"]["cpu_pct"]) == len(body["series"]["gpu_pct"])
    assert set(body["series"]["cpu_pct"]) <= {10.0, 30.0, 20.0}


def test_services_flags_crash_loop_from_runs_growth(make_client):
    client = make_client()
    now = int(time.time())
    with _app_sessions(client).begin() as s:
        s.execute(insert(ServiceSnapshot), [
            {"ts": now - 80000, "label": "com.example.looper", "domain": "gui", "state": "running",
             "runs": 10, "last_exit": "2"},
            {"ts": now - 60, "label": "com.example.looper", "domain": "gui", "state": "running",
             "runs": 400, "last_exit": "2"},
            {"ts": now - 60, "label": "ai.hermes.gateway", "domain": "gui", "state": "running",
             "runs": 1, "last_exit": "(never exited)"},
        ])
    body = client.get("/api/services").json()
    first = body["services"][0]
    assert first["label"] == "com.example.looper"
    assert first["runs_24h"] == 390
    assert first["flags"] == ["crash_loop", "last_exit_nonzero"]
    assert first["severity"] == 2
    healthy = body["services"][1]
    assert healthy["flags"] == [] and healthy["severity"] == 0


def test_collector_endpoints_503_when_disabled(make_client):
    client = make_client()
    for path in ("/api/processes/top", "/api/tailscale", "/api/updates"):
        assert client.get(path).status_code == 503


def test_services_do_not_flag_scheduled_job(make_client):
    client = make_client()
    now = int(time.time())
    with _app_sessions(client).begin() as s:
        s.execute(insert(ServiceSnapshot), [
            {"ts": now - 86000, "label": "com.openclaw.health-check", "domain": "gui",
             "state": "not running", "runs": 6811, "last_exit": "0", "run_interval_s": 300,
             "calendar": False},
            {"ts": now - 60, "label": "com.openclaw.health-check", "domain": "gui",
             "state": "not running", "runs": 7099, "last_exit": "0", "run_interval_s": 300,
             "calendar": False},
        ])
    svc = client.get("/api/services").json()["services"][0]
    assert svc["runs_24h"] == 288
    assert svc["flags"] == []
    assert svc["schedule"] == "every 5 min"


def test_no_two_routes_share_a_method_and_path(make_client):
    """A later router silently shadowed /api/updates once; every method and path must be unique."""
    seen = {}
    for route in make_client().app.routes:
        for method in getattr(route, "methods", None) or ():
            key = (method, getattr(route, "path", ""))
            assert key not in seen, f"{key} is registered twice: {seen[key]} and {route.name}"
            seen[key] = route.name
