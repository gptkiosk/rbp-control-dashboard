import json
import os
import sys
import threading
import time

import pytest

import ops_collectors
from ops_collectors import Busy, ConfigError, OpsCollectors, load_config
from settings import Settings


def build(tmp_path, sessions, sources, commands=(), clock=None, **extra):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "ops-collectors.json").write_text(json.dumps({"sources": sources, **extra}))
    settings = Settings(_env_file=None, data_dir=data, ops_collector_commands=tuple(commands))
    return OpsCollectors(settings, sessions, lambda: data / "reports", clock or time.time), data


def reports(data):
    folder = data / "reports" / "fleet-health"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_healthy_unchanged_writes_no_report(tmp_path, sessions):
    runner, data = build(tmp_path, sessions, [{"id": "disk", "kind": "disk", "path": str(tmp_path), "warn_pct": 100, "crit_pct": 100}])
    first = runner.run()
    assert first["events"] == [] and reports(data) == []
    second = runner.run(force=True)
    assert second["changed"] == [] and reports(data) == []


def test_change_reports_once_then_recovery(tmp_path, sessions):
    target = tmp_path / "backup.txt"
    now = [1_000_000]
    runner, data = build(tmp_path, sessions, [{"id": "backup", "kind": "file_age", "path": str(target), "warn_s": 60, "crit_s": 600}],
                         clock=lambda: now[0])
    assert runner.run()["changed"] == ["backup"]  # missing file is critical on the first look
    assert len(reports(data)) == 1
    now[0] += 120
    assert runner.run(force=True)["changed"] == []  # unchanged problem: deduplicated, no new report
    assert len(reports(data)) == 1
    target.write_text("x")
    os.utime(target, (now[0], now[0]))
    result = runner.run(force=True)
    assert result["events"][0]["reason"] == "recovered"
    body = (data / "reports" / "fleet-health" / reports(data)[-1]).read_text()
    assert "backup - ok (recovered)" in body and "/reports" in body


def test_reminder_after_renotify_interval(tmp_path, sessions):
    now = [2_000_000]
    runner, data = build(tmp_path, sessions, [{"id": "gone", "kind": "file_age", "path": str(tmp_path / "none")}],
                         clock=lambda: now[0], renotify_s=300)
    runner.run()
    now[0] += 301
    again = runner.run(force=True)
    assert again["events"][0]["reason"] == "reminder"


def test_cache_skips_recent_sources_unless_forced(tmp_path, sessions):
    runner, _ = build(tmp_path, sessions, [{"id": "mem", "kind": "memory", "warn_pct": 100, "crit_pct": 100}], cache_ttl_s=3600)
    assert runner.run()["checked"] == ["mem"]
    assert runner.run()["checked"] == []
    assert runner.run(force=True)["checked"] == ["mem"]


def test_allowlist_rejects_unknown_kind_command_and_private_paths(tmp_path, sessions):
    data = tmp_path / "data"
    data.mkdir()
    def attempt(source, commands=()):
        (data / "ops-collectors.json").write_text(json.dumps({"sources": [source]}))
        return load_config(data, commands)[1]
    assert attempt({"id": "x", "kind": "shell", "cmd": "ls"})
    assert attempt({"id": "x", "kind": "command", "argv": ["/bin/echo", "hi"]})  # not allowlisted by the host
    assert attempt({"id": "x", "kind": "command", "argv": ["/bin/echo", "hi"], "extra": 1}, ("/bin/echo",))
    assert attempt({"id": "x", "kind": "file_age", "path": "/Users/me/.ssh/id"})
    assert attempt({"id": "x", "kind": "file_age", "path": "relative"})
    assert attempt({"id": "x", "kind": "command", "argv": ["/bin/echo", "hi"]}, ("/bin/echo",)) is None


def test_broken_config_fails_closed_and_refresh_rejects_unknown_sources(tmp_path, sessions):
    runner, data = build(tmp_path, sessions, [{"id": "mem", "kind": "memory"}])
    with pytest.raises(ConfigError):
        runner.run(["not-configured"])
    (data / "ops-collectors.json").write_text("{not json")
    with pytest.raises(ConfigError):
        runner.run()
    assert runner.status()["error"]


def test_command_source_uses_scrubbed_environment_and_kills_on_timeout(tmp_path, sessions):
    probe = tmp_path / "probe.py"
    probe.write_text("import os,sys\nprint('secret' if 'MAC_CONTROL_DATA_DIR' in os.environ else 'clean')\nsys.exit(0)\n")
    sleeper = tmp_path / "sleep.py"
    sleeper.write_text("import time\ntime.sleep(60)\n")
    os.environ["MAC_CONTROL_DATA_DIR"] = "leak"
    try:
        runner, _ = build(tmp_path, sessions, [
            {"id": "env", "kind": "command", "argv": [sys.executable, str(probe)]},
            {"id": "slow", "kind": "command", "argv": [sys.executable, str(sleeper)]}],
            commands=(sys.executable,), source_timeout_s=1)
        started = time.monotonic()
        result = runner.run(force=True)
        assert time.monotonic() - started < 8
    finally:
        del os.environ["MAC_CONTROL_DATA_DIR"]
    by_id = {e["id"]: e for e in result["events"]}
    assert "env" not in by_id  # ok on first run, so no event
    assert by_id["slow"]["summary"] == "timed out"
    assert runner.status()["sources"][0]["summary"] == "clean"


def test_single_invocation_lock(tmp_path, sessions):
    runner, _ = build(tmp_path, sessions, [{"id": "mem", "kind": "memory"}])
    assert runner.mutex.acquire(blocking=False)
    try:
        with pytest.raises(Busy):
            runner.run()
    finally:
        runner.mutex.release()


def test_disk_lock_blocks_a_second_process_style_runner(tmp_path, sessions):
    runner, data = build(tmp_path, sessions, [{"id": "mem", "kind": "memory"}])
    other = OpsCollectors(runner.settings, sessions, runner.root_provider)
    import fcntl
    fd = os.open(data / "ops-collectors.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(Busy):
            other.run()
    finally:
        os.close(fd)


def test_retention_by_count_size_and_age_keeps_newest(tmp_path, sessions):
    now = [3_000_000_000]
    runner, data = build(tmp_path, sessions, [{"id": "gone", "kind": "file_age", "path": str(tmp_path / "none")}],
                         clock=lambda: now[0], renotify_s=300,
                         retention={"max_reports": 3, "max_age_days": 365, "max_total_bytes": 64 * 1024 * 1024, "max_report_bytes": 1024})
    for _ in range(6):
        runner.run(force=True)
        now[0] += 301
    names = reports(data)
    assert len(names) == 3 and names == sorted(names)
    folder = data / "reports" / "fleet-health"
    (folder / "keep-me.md").write_text("not ours")
    (folder / "19990101-000000.md").write_text("old")
    runner.run(force=True)
    assert (folder / "keep-me.md").exists() and not (folder / "19990101-000000.md").exists()
    assert all(p.stat().st_size <= 1024 for p in folder.glob("2*.md"))


def test_job_collector_counts_failures_from_database(tmp_path, sessions):
    from models import Card
    now = int(time.time())
    with sessions.begin() as session:
        session.add(Card(title="t", body="b", column="failed", timeout_s=60, created_at=now, updated_at=now))
    runner, data = build(tmp_path, sessions, [{"id": "jobs", "kind": "jobs"}])
    event = runner.run()["events"][0]
    assert event["status"] == "warn" and event["summary"].startswith("1 failed")


def test_refresh_endpoint_is_operator_only_and_bounded(make_client, tmp_path):
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
        data = tmp_path / "data"
        (data / "ops-collectors.json").write_text(json.dumps({"sources": [{"id": "mem", "kind": "memory", "warn_pct": 100, "crit_pct": 100}]}))
        assert client.get("/api/ops-collectors").json()["enabled"] is False
        assert client.post("/api/ops-collectors/refresh", json={"force": True}).status_code == 403
        signed_in = True
        ok = client.post("/api/ops-collectors/refresh", json={"sources": ["mem"], "force": True})
        assert ok.status_code == 200 and ok.json()["checked"] == ["mem"]
        assert client.post("/api/ops-collectors/refresh", json={"sources": ["../x"]}).status_code == 422
        assert client.post("/api/ops-collectors/refresh", json={"argv": ["ls"]}).status_code == 422
        assert client.get("/api/ops-collectors").json()["sources"][0]["status"] == "ok"
        agent = True
        assert client.post("/api/ops-collectors/refresh", json={}).status_code == 403
