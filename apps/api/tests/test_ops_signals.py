import json
import os
import time

from ops_collectors import OpsCollectors, load_config
from settings import Settings


def build(tmp_path, sessions, sources, clock=None):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "ops-collectors.json").write_text(json.dumps({"sources": sources}))
    settings = Settings(_env_file=None, data_dir=data)
    return OpsCollectors(settings, sessions, lambda: data / "reports", clock or time.time), data


def one(runner):
    return runner.run(force=True)["events"][0]


def test_dir_age_reports_stale_backup_folder_and_ignores_symlinks(tmp_path, sessions):
    folder = tmp_path / "backups"
    folder.mkdir()
    now = [5_000_000]
    runner, _ = build(tmp_path, sessions, [{"id": "backup", "kind": "dir_age", "path": str(folder), "warn_s": 60, "crit_s": 600}],
                      clock=lambda: now[0])
    assert one(runner)["summary"] == "no files"
    (folder / "link").symlink_to(tmp_path)
    assert runner.run(force=True)["events"] == []  # unchanged; a symlink is never followed or counted
    fresh = folder / "db.bak"
    fresh.write_text("x")
    os.utime(fresh, (now[0] - 120, now[0] - 120))
    event = one(runner)
    assert event["status"] == "warn" and "2 min" in event["summary"]


def test_dir_age_missing_folder_is_critical(tmp_path, sessions):
    runner, _ = build(tmp_path, sessions, [{"id": "backup", "kind": "dir_age", "path": str(tmp_path / "nope")}])
    assert one(runner)["status"] == "crit"


def test_load_probe_grades_by_core_ratio(tmp_path, sessions, monkeypatch):
    monkeypatch.setattr(os, "getloadavg", lambda: (8.0, 4.0, 2.0))
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    runner, _ = build(tmp_path, sessions, [{"id": "cpu", "kind": "load", "warn_ratio": 1.5, "crit_ratio": 3}])
    assert one(runner)["status"] == "warn"


def test_waits_probe_counts_retry_and_old_approvals(tmp_path, sessions):
    from models import Card
    now = 7_000_000
    with sessions.begin() as session:
        session.add(Card(title="a", body="b", column="review", needs_approval=True, timeout_s=60,
                         created_at=now - 9000, updated_at=now - 9000))
        session.add(Card(title="c", body="d", column="queued", retry_after=now + 600, timeout_s=60,
                         created_at=now, updated_at=now))
    runner, _ = build(tmp_path, sessions, [{"id": "waits", "kind": "waits", "warn_s": 3600, "crit_s": 86400}],
                      clock=lambda: now)
    event = one(runner)
    assert event["status"] == "warn" and event["summary"] == "1 approvals, 1 in rate-limit or retry wait"


def test_agents_probe_flags_running_row_with_dead_runner(tmp_path, sessions):
    from models import Run
    now = int(time.time())
    with sessions.begin() as session:
        session.add(Run(agent="claude", stage="running", started_at=now - 600, working_dir="/", command="[]",
                        log_path=str(tmp_path / "none.log"), pid=2 ** 22 + 12345))
    runner, _ = build(tmp_path, sessions, [{"id": "agents", "kind": "agents"}])
    event = one(runner)
    assert event["status"] == "warn" and event["summary"] == "1 unresponsive runs"


def test_release_probe_unconfigured_is_silent_and_interrupted_update_is_flagged(tmp_path, sessions):
    runner, _ = build(tmp_path, sessions, [{"id": "release", "kind": "release", "stuck_s": 60}])
    assert runner.run(force=True)["events"] == []
    root = tmp_path / "update"
    (root / "state").mkdir(parents=True)
    state = root / "state" / "install.json"
    state.write_text(json.dumps({"tx": {"kind": "switch", "phase": "switching", "target": "v2",
                                        "started_at": int(time.time()) - 500}}))
    state.chmod(0o600)
    runner.settings = runner.settings.model_copy(update={"update_root": root})
    event = one(runner)
    assert event["status"] == "crit" and event["summary"] == "update switching"


def test_service_probe_validates_name_and_missing_service_never_crashes(tmp_path, sessions):
    data = tmp_path / "data"
    data.mkdir()
    (data / "ops-collectors.json").write_text(json.dumps({"sources": [{"id": "s", "kind": "service", "name": "../x; rm"}]}))
    assert load_config(data)[1]
    runner, _ = build(tmp_path, sessions, [{"id": "svc", "kind": "service", "name": "no.such.service.invalid"}])
    event = one(runner)  # absent under launchd or systemd; a missing systemctl is a failed check, not a crash
    assert event["status"] in ("crit", "warn")
