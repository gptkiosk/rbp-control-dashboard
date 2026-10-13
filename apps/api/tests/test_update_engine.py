"""Update engine (s5-engine-core): staging, transactional state, atomic switch, drain refusal,
rollback and recovery after a killed helper.

Everything is synthetic and inside tmp_path: packages come from the verifier test builder,
the service is a recorder and readiness is injected. Crash cases run a real short-lived
process (update_crash_host.py) that dies with os._exit mid-operation.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

import release_verify as rv
import update_engine as ue
from tests.test_release_verify import PLATFORM, PRODUCT, make_release

CRASH_HOST = Path(__file__).with_name("update_crash_host.py")


class Service(ue.ServiceControl):
    def __init__(self):
        self.calls: list[str] = []

    def stop(self):
        self.calls.append("stop")

    def start(self):
        self.calls.append("start")


def ready(cfg, version, started):
    return True, f"version {version} healthy"


def no_blockers(path):
    return []


@pytest.fixture(autouse=True)
def this_host(monkeypatch):
    monkeypatch.setattr(rv, "host_platform", lambda: PLATFORM)


@pytest.fixture
def cfg(tmp_path):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    db = sqlite3.connect(data / "data.db")
    db.execute("CREATE TABLE marker (value TEXT)")
    db.execute("INSERT INTO marker VALUES ('before')")
    db.commit()
    db.close()
    config = ue.HelperConfig(product=PRODUCT, platform=PLATFORM, root=root, db_path=data / "data.db",
                             health_url="http://127.0.0.1:8899/healthz",
                             service={"kind": "launchd", "label": "test.dashboard", "plist": "/nonexistent.plist"},
                             python=sys.executable, trust={"kind": "pinned-digest"})
    ue.prepare_layout(config)
    return config


def put_in_inbox(cfg, tmp_path, version, name=None):
    release = make_release(tmp_path, version=version, name=name or f"pkg-{version}")
    for path in (release.manifest_path, release.artifact_path):
        shutil.copyfile(path, cfg.inbox / path.name)
    return release.base, hashlib.sha256(release.manifest_bytes).hexdigest()


def fake_builder(cfg, app_dir, release):
    (app_dir / ue.RUNTIME_DIR / "bin").mkdir(parents=True)
    (app_dir / ue.RUNTIME_DIR / "bin" / "python").write_text("synthetic")


def staged(cfg, tmp_path, version):
    name, digest = put_in_inbox(cfg, tmp_path, version)
    return ue.stage(cfg, name, digest, builder=fake_builder)["id"]


def installed(cfg, tmp_path):
    """A managed install running 1.1.0 with 1.2.0 staged."""
    old = staged(cfg, tmp_path, "1.1.0")
    ue.activate_initial(cfg, old)
    new = staged(cfg, tmp_path, "1.2.0")
    return old, new


def marker(cfg):
    con = sqlite3.connect(cfg.db_path)
    try:
        return con.execute("SELECT value FROM marker").fetchall()
    finally:
        con.close()


def set_marker(cfg, value):
    con = sqlite3.connect(cfg.db_path)
    con.execute("UPDATE marker SET value = ?", (value,))
    con.commit()
    con.close()


def crash(cfg, **args):
    raw = {k: str(v) if isinstance(v, Path) else v for k, v in asdict(cfg).items()}
    payload = json.dumps({"config": raw, "platform": PLATFORM, **args})
    result = subprocess.run([sys.executable, "-I", str(CRASH_HOST), payload], capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 9, result.stderr


# --- configuration -----------------------------------------------------------------------


def config_file(tmp_path, cfg, **changes):
    raw = {"schema": ue.CONFIG_SCHEMA, "product": cfg.product, "platform": cfg.platform, "root": str(cfg.root),
           "db_path": str(cfg.db_path), "health_url": cfg.health_url, "service": cfg.service,
           "python": cfg.python, "trust": cfg.trust, **changes}
    path = tmp_path / "helper.json"
    path.write_text(json.dumps(raw))
    path.chmod(0o600)
    return path


def test_config_loads_only_a_private_strict_file(tmp_path, cfg):
    assert ue.load_config(config_file(tmp_path, cfg)) == cfg
    path = config_file(tmp_path, cfg)
    path.chmod(0o640)
    with pytest.raises(ue.UpdateError, match="not readable by others"):
        ue.load_config(path)
    link = tmp_path / "link.json"
    link.symlink_to(config_file(tmp_path, cfg))
    with pytest.raises(ue.UpdateError):
        ue.load_config(link)
    for bad in ({"health_url": "http://example.com:8800/healthz"}, {"health_url": "http://127.0.0.1:8800/api"},
                {"root": "relative/root"}, {"extra": 1}, {"trust": {"kind": "none"}},
                {"service": {"kind": "launchd", "label": "x; rm -rf /", "plist": "/a.plist"}},
                {"product": "rcd" if PRODUCT == "mcd" else "mcd"}, {"readiness_timeout_s": 1}):
        with pytest.raises(ue.UpdateError):
            ue.load_config(config_file(tmp_path, cfg, **bad))


def test_layout_refuses_shared_or_symlinked_root(tmp_path, cfg):
    cfg.root.chmod(0o777)
    with pytest.raises(ue.UpdateError, match="not writable by group or others"):
        ue.prepare_layout(cfg)
    cfg.root.chmod(0o700)
    shutil.rmtree(cfg.versions)
    cfg.versions.symlink_to(tmp_path)
    with pytest.raises(ue.UpdateError, match="not a real directory"):
        ue.prepare_layout(cfg)


# --- staging -------------------------------------------------------------------------------


def test_stage_installs_a_sealed_immutable_version(tmp_path, cfg):
    name, digest = put_in_inbox(cfg, tmp_path, "1.2.0")
    result = ue.stage(cfg, name, digest, builder=fake_builder)
    vid = result["id"]
    assert vid.startswith("1.2.0-") and not result["already_staged"]
    receipt = ue.read_receipt(cfg, vid)
    assert receipt["version"] == "1.2.0" and receipt["authenticity"].startswith("pinned-digest")
    for path in (cfg.versions / vid).rglob("*"):
        if not path.is_symlink():
            assert path.lstat().st_mode & 0o222 == 0, path
    with pytest.raises(PermissionError):
        (cfg.versions / vid / "apps/api/main.py").write_text("tampered")
    state = ue.load_state(cfg)
    assert state["tx"] is None and state["last"]["outcome"] == "staged" and vid in state["staged"]
    assert ue.stage(cfg, name, digest, builder=fake_builder)["already_staged"]


def test_stage_refuses_unverified_packages_and_leaves_nothing(tmp_path, cfg):
    name, digest = put_in_inbox(cfg, tmp_path, "1.2.0")
    with pytest.raises(ue.UpdateError, match="manifest sha256"):
        ue.stage(cfg, name, None, builder=fake_builder)
    with pytest.raises(ue.UpdateError, match="package refused"):
        ue.stage(cfg, name, "0" * 64, builder=fake_builder)
    artifact = cfg.inbox / f"{name}.tar.gz"
    tampered = bytearray(artifact.read_bytes())
    tampered[len(tampered) // 2] ^= 0xFF
    artifact.write_bytes(tampered)
    with pytest.raises(ue.UpdateError, match="package refused"):
        ue.stage(cfg, name, digest, builder=fake_builder)
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(ue.UpdateError, match="plain release base name"):
            ue.stage(cfg, bad, digest, builder=fake_builder)
    assert os.listdir(cfg.versions) == [] and ue.load_state(cfg)["tx"] is None


def test_failed_runtime_build_removes_the_partial_version(tmp_path, cfg):
    name, digest = put_in_inbox(cfg, tmp_path, "1.2.0")

    def broken(cfg, app_dir, release):
        raise ue.UpdateError("dependency install failed")
    with pytest.raises(ue.UpdateError, match="dependency install failed"):
        ue.stage(cfg, name, digest, builder=broken)
    assert os.listdir(cfg.versions) == []
    assert ue.load_state(cfg)["last"]["outcome"] == "failed"


def test_recover_removes_a_version_left_by_a_killed_stage(tmp_path, cfg):
    name, digest = put_in_inbox(cfg, tmp_path, "1.2.0")
    crash(cfg, op="stage", name=name, digest=digest)
    state = ue.load_state(cfg)
    assert state["tx"]["kind"] == "stage" and state["tx"]["phase"] == "staging"
    partial = state["tx"]["target"]
    assert (cfg.versions / partial).is_dir() and ue.read_receipt(cfg, partial) is None
    with pytest.raises(ue.UpdateError, match="interrupted"):
        ue.stage(cfg, name, digest, builder=fake_builder)
    assert ue.recover(cfg, Service(), ready) == "aborted"
    assert not (cfg.versions / partial).exists() and ue.load_state(cfg)["tx"] is None
    assert ue.recover(cfg, Service(), ready) == "nothing to recover"
    assert ue.stage(cfg, name, digest, builder=fake_builder)["id"] == partial


def test_one_invocation_at_a_time(tmp_path, cfg):
    name, digest = put_in_inbox(cfg, tmp_path, "1.2.0")
    fd = os.open(cfg.state_dir / "lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(ue.UpdateError, match="another update"):
            ue.stage(cfg, name, digest, builder=fake_builder)
        with pytest.raises(ue.UpdateError, match="another update"):
            ue.recover(cfg, Service(), ready)
    finally:
        os.close(fd)
    assert ue.stage(cfg, name, digest, builder=fake_builder)


# --- switch --------------------------------------------------------------------------------


def test_apply_switches_atomically_after_drain(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    service = Service()
    result = ue.apply(cfg, new, service, readiness=ready, blockers=no_blockers)
    assert result["current"] == new and service.calls == ["stop", "start"]
    assert os.readlink(cfg.root / "current") == f"versions/{new}"
    assert os.readlink(cfg.root / "previous") == f"versions/{old}"
    state = ue.load_state(cfg)
    assert state["tx"] is None and state["last"]["outcome"] == "committed"
    assert (state["current"], state["previous"]) == (new, old)
    assert list((cfg.state_dir / "backups").glob("data-*.db"))
    with pytest.raises(ue.UpdateError, match="already current"):
        ue.apply(cfg, new, Service(), readiness=ready, blockers=no_blockers)


def test_apply_refuses_active_work_and_stops_nothing(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    service = Service()
    with pytest.raises(ue.UpdateError) as exc:
        ue.apply(cfg, new, service, readiness=ready, blockers=lambda p: ["1 agent run(s) still running"])
    assert "drain first; nothing was stopped" in exc.value.problems
    assert service.calls == [] and os.readlink(cfg.root / "current") == f"versions/{old}"
    assert ue.load_state(cfg)["tx"] is None


def test_work_started_during_stop_aborts_without_switching(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    answers = iter([[], ["1 task(s) queued or running"]])
    service = Service()
    with pytest.raises(ue.UpdateError, match="nothing was switched"):
        ue.apply(cfg, new, service, readiness=ready, blockers=lambda p: next(answers))
    assert service.calls == ["stop", "start"]
    assert os.readlink(cfg.root / "current") == f"versions/{old}"
    assert ue.load_state(cfg)["last"]["outcome"] == "aborted"


def test_unready_version_is_rolled_back_with_its_database_changes(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    seen = []

    def readiness(cfg, version, started):
        seen.append(version)
        if version == "1.2.0":
            set_marker(cfg, "migrated by 1.2.0")  # the new version changed the schema/data
            return False, "health reports version 1.1.0"
        return True, "ok"
    service = Service()
    with pytest.raises(ue.UpdateError, match="rolled back"):
        ue.apply(cfg, new, service, readiness=readiness, blockers=no_blockers)
    assert seen == ["1.2.0", "1.1.0"] and service.calls == ["stop", "start", "stop", "start"]
    assert os.readlink(cfg.root / "current") == f"versions/{old}"
    assert marker(cfg) == [("before",)]
    last = ue.load_state(cfg)["last"]
    assert last["outcome"] == "rolled_back" and last["database_restored"] is True
    assert ue.read_receipt(cfg, new)  # still staged; the operator can retry after a fix


def test_disk_full_during_snapshot_aborts_and_preserves_current_data(tmp_path, cfg, monkeypatch):
    old, new = installed(cfg, tmp_path)
    service = Service()

    def disk_full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ue, "backup_database", disk_full)
    with pytest.raises(OSError, match="No space left"):
        ue.apply(cfg, new, service, readiness=ready, blockers=no_blockers)
    assert os.readlink(cfg.root / "current") == f"versions/{old}"
    assert marker(cfg) == [("before",)]
    assert service.calls == ["stop", "start"]
    assert ue.load_state(cfg)["tx"] is None
    assert ue.load_state(cfg)["last"]["outcome"] == "aborted"


def test_start_failure_rolls_back_to_old_version(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)

    class FailsOnce(Service):
        def start(self):
            self.calls.append("start")
            if self.calls.count("start") == 1:
                raise ue.UpdateError("synthetic start failure")

    service = FailsOnce()
    with pytest.raises(ue.UpdateError, match="synthetic start failure"):
        ue.apply(cfg, new, service, readiness=ready, blockers=no_blockers)
    assert service.calls == ["stop", "start", "stop", "start"]
    assert os.readlink(cfg.root / "current") == f"versions/{old}"
    assert marker(cfg) == [("before",)]
    assert ue.load_state(cfg)["last"]["outcome"] == "rolled_back"


def test_unmanaged_installs_cannot_apply(tmp_path, cfg):
    new = staged(cfg, tmp_path, "1.2.0")
    with pytest.raises(ue.UpdateError, match="updated by hand"):
        ue.apply(cfg, new, Service(), readiness=ready, blockers=no_blockers)
    ue.activate_initial(cfg, new)
    with pytest.raises(ue.UpdateError, match="already exists"):
        ue.activate_initial(cfg, new)


# --- recovery after a killed helper ------------------------------------------------------------


def test_killed_before_switch_restarts_the_old_version(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    calls = tmp_path / "calls"
    crash(cfg, op="apply", version_id=new, crash="stop", calls=str(calls))
    assert ue.load_state(cfg)["tx"]["phase"] == "prepared"
    service = Service()
    assert ue.recover(cfg, service, ready) == "aborted"
    assert service.calls == ["start"] and os.readlink(cfg.root / "current") == f"versions/{old}"


@pytest.mark.parametrize("healthy", [True, False])
def test_killed_after_switch_commits_or_rolls_back(tmp_path, cfg, healthy):
    old, new = installed(cfg, tmp_path)
    calls = tmp_path / "calls"
    crash(cfg, op="apply", version_id=new, crash="readiness", calls=str(calls))
    assert calls.read_text().split() == ["stop", "start"]
    state = ue.load_state(cfg)
    assert state["tx"]["phase"] == "starting" and state["tx"]["backup"]
    assert os.readlink(cfg.root / "current") == f"versions/{new}"
    set_marker(cfg, "written by 1.2.0")

    def readiness(cfg, version, started):
        return (healthy or version == "1.1.0"), version
    service = Service()
    outcome = ue.recover(cfg, service, readiness)
    if healthy:
        assert outcome == "committed" and service.calls == ["start"]
        assert os.readlink(cfg.root / "current") == f"versions/{new}" and marker(cfg) == [("written by 1.2.0",)]
    else:
        assert outcome == "rolled_back" and service.calls == ["start", "stop", "start"]
        assert os.readlink(cfg.root / "current") == f"versions/{old}" and marker(cfg) == [("before",)]
    assert ue.load_state(cfg)["tx"] is None
    assert ue.recover(cfg, Service(), readiness) == "nothing to recover"


def test_interrupted_rollback_is_finished_by_recovery(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    state = ue.load_state(cfg)
    state["tx"] = {"id": "abc", "kind": "switch", "phase": "rolling_back", "target": new, "from": old,
                   "backup": None, "reason": "readiness failed"}
    ue.save_state(cfg, state)
    ue._point(cfg, "current", new)
    service = Service()
    assert ue.recover(cfg, service, ready) == "rolled_back"
    assert service.calls == ["stop", "start"] and os.readlink(cfg.root / "current") == f"versions/{old}"


def test_prune_keeps_current_previous_and_staged(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    ue.apply(cfg, new, Service(), readiness=ready, blockers=no_blockers)
    third = staged(cfg, tmp_path, "1.3.0")
    removed = ue.prune(cfg)
    assert removed == [] and {old, new, third} <= set(os.listdir(cfg.versions))
    with pytest.raises(ue.UpdateError, match="refusing to remove"):
        ue.remove_version(cfg, new)


# --- readiness against a real loopback server -----------------------------------------------------


def test_health_readiness_needs_the_expected_fresh_version(cfg):
    import dataclasses
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    answer = {"status": "ok", "version": "1.2.0", "uptime_s": 1.0, "web_built": True, "data_dir_writable": True}

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(answer).encode()
            self.send_response(200 if self.path == "/healthz" else 404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Health)  # ephemeral port; never the live 8800
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        local = dataclasses.replace(cfg, health_url=f"http://127.0.0.1:{server.server_port}/healthz",
                                    readiness_timeout_s=1)
        assert ue.health_readiness(local, "1.2.0", time.time())[0] is True
        ok, detail = ue.health_readiness(local, "1.3.0", time.time())
        assert not ok and "expected 1.3.0" in detail
        answer["uptime_s"] = 3600.0
        ok, detail = ue.health_readiness(local, "1.2.0", time.time())
        assert not ok and "predates the restart" in detail
    finally:
        server.shutdown()
        server.server_close()


# --- drain check against the real schema ----------------------------------------------------------


def test_drain_blockers_read_the_real_task_database(tmp_path):
    from db import make_engine, make_session_factory
    from migrate import upgrade_to_head
    from models import Card, Project, Run

    db_path = tmp_path / "data.db"
    engine = make_engine(db_path)
    upgrade_to_head(engine)
    sessions = make_session_factory(engine)
    assert ue.drain_blockers(db_path) == []
    with sessions() as s:
        card = Card(title="t", body="b", column="queued", timeout_s=60, created_at=0, updated_at=0)
        s.add(card)
        s.flush()
        s.add(Run(card_id=card.id, agent="claude", stage="running", started_at=0, working_dir="/tmp",
                  command="[]", log_path="/tmp/x"))
        s.add(Run(card_id=card.id, agent="claude", stage="awaiting_approval", started_at=0, ended_at=1,
                  working_dir="/tmp", command="[]", log_path="/tmp/y"))
        s.add(Card(title="a", body="b", column="review", timeout_s=60, created_at=0, updated_at=0,
                   approved_at=1))
        s.add(Project(document="{}", state="active", created_by="op", created_at=0, updated_at=0))
        s.commit()
    blockers = " | ".join(ue.drain_blockers(db_path))
    for expected in ("1 agent or chat run(s) still running", "1 run(s) waiting on a human decision",
                     "1 task(s) queued or running", "1 project(s) still dispatching"):
        assert expected in blockers
    engine.dispose()
    assert "could not be opened" in ue.drain_blockers(tmp_path / "missing" / "data.db")[0]


# --- data snapshots, schema compatibility and explicit restore (s5-engine-data) -----------------


def migrating_builder(*revisions):
    """A synthetic version whose sealed tree carries migration files for the given revisions."""
    def build(cfg, app_dir, release):
        fake_builder(cfg, app_dir, release)
        folder = app_dir / "apps" / "api" / "migrations" / "versions"
        folder.mkdir(parents=True, exist_ok=True)
        for rev in revisions:
            (folder / f"{rev}_step.py").write_text(f'revision = "{rev}"\ndown_revision = None\n')
    return build


def staged_with(cfg, tmp_path, version, builder):
    name, digest = put_in_inbox(cfg, tmp_path, version)
    return ue.stage(cfg, name, digest, builder=builder)["id"]


def set_revision(cfg, rev):
    """Simulate the alembic_version table a migrated database carries."""
    con = sqlite3.connect(cfg.db_path)
    con.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num TEXT PRIMARY KEY)")
    con.execute("DELETE FROM alembic_version")
    if rev:
        con.execute("INSERT INTO alembic_version VALUES (?)", (rev,))
    con.commit()
    con.close()


def migrated_install(cfg, tmp_path):
    """1.1.0 (schema 0014) running, 1.2.0 (schema 0014 -> 0015) staged."""
    old = staged_with(cfg, tmp_path, "1.1.0", migrating_builder("0014"))
    ue.activate_initial(cfg, old)
    new = staged_with(cfg, tmp_path, "1.2.0", migrating_builder("0014", "0015"))
    set_revision(cfg, "0014")
    return old, new


def failing_migration(cfg, version, started=None):
    if version == "1.2.0":
        set_revision(cfg, "0015")  # the new version migrated the schema, then failed readiness
        set_marker(cfg, "written by 1.2.0")
        return False, "health reports version 1.1.0"
    return True, "ok"


def test_known_revisions_reads_revision_lines_only(tmp_path):
    folder = tmp_path / "apps" / "api" / "migrations" / "versions"
    folder.mkdir(parents=True)
    (folder / "0015_x.py").write_text('revision = "0015"\ndown_revision = "0014"\n')
    (folder / "notes.txt").write_text('revision = "9999"\n')
    assert ue.known_revisions(tmp_path) == {"0015"}
    assert ue.known_revisions(tmp_path / "missing") == set()
    assert ue.schema_compatible(None, set()) and ue.schema_compatible("0015", {"0015"})
    assert not ue.schema_compatible("0016", {"0015"})


def test_migrated_schema_is_never_rolled_back_automatically(tmp_path, cfg):
    old, new = migrated_install(cfg, tmp_path)
    service = Service()
    with pytest.raises(ue.UpdateError, match="rolled back"):
        ue.apply(cfg, new, service, readiness=failing_migration, blockers=no_blockers)
    last = ue.load_state(cfg)["last"]
    assert last["outcome"] == "rolled_back" and last["database_restored"] is False
    assert "not restored automatically" in last["detail"] and last["schema_after"] == "0015"
    assert marker(cfg) == [("written by 1.2.0",)] and revision_of(cfg) == "0015"
    assert os.readlink(cfg.root / "current") == f"versions/{old}"


def revision_of(cfg):
    con = sqlite3.connect(cfg.db_path)
    try:
        return con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        con.close()


def test_explicit_restore_needs_the_snapshot_id_and_keeps_a_copy(tmp_path, cfg):
    old, _ = migrated_install(cfg, tmp_path)
    with pytest.raises(ue.UpdateError):
        ue.apply(cfg, staged_with_id(cfg), Service(), readiness=failing_migration, blockers=no_blockers)
    tx = ue.load_state(cfg)["last"]["tx"]
    with pytest.raises(ue.UpdateError, match="WARNING") as exc:
        ue.restore_snapshot(cfg, tx, None, Service(), ready, no_blockers)
    assert "discards every change" in str(exc.value) and marker(cfg) == [("written by 1.2.0",)]
    with pytest.raises(ue.UpdateError, match="WARNING"):
        ue.restore_snapshot(cfg, tx, "0" * 16, Service(), ready, no_blockers)
    service = Service()
    result = ue.restore_snapshot(cfg, tx, tx, service, ready, no_blockers)
    assert result == {"current": old, "snapshot": tx, "detail": "version 1.1.0 healthy"}
    assert marker(cfg) == [("before",)] and revision_of(cfg) == "0014"
    assert service.calls == ["stop", "start"]
    last = ue.load_state(cfg)["last"]
    assert last["outcome"] == "restored" and last["data_loss_confirmed"] is True and last["snapshot"] == tx
    kept = cfg.state_dir / "backups" / last["pre_restore"]
    con = sqlite3.connect(kept)
    try:
        assert con.execute("SELECT value FROM marker").fetchall() == [("written by 1.2.0",)]
    finally:
        con.close()


def staged_with_id(cfg):
    """The 1.2.0 id, found from the inbox-independent receipt directory."""
    return next(v for v in os.listdir(cfg.versions) if v.startswith("1.2.0-"))


def test_tampered_snapshot_is_refused_and_nothing_changes(tmp_path, cfg):
    migrated_install(cfg, tmp_path)
    with pytest.raises(ue.UpdateError):
        ue.apply(cfg, staged_with_id(cfg), Service(), readiness=failing_migration, blockers=no_blockers)
    tx = ue.load_state(cfg)["last"]["tx"]
    (cfg.state_dir / "backups" / f"data-{tx}.db").write_bytes(b"tampered")
    with pytest.raises(ue.UpdateError, match="failed its checksum"):
        ue.restore_snapshot(cfg, tx, tx, Service(), ready, no_blockers)
    assert marker(cfg) == [("written by 1.2.0",)]
    with pytest.raises(ue.UpdateError, match="snapshot id"):
        ue.restore_snapshot(cfg, "../escape", "../escape", Service(), ready, no_blockers)


def test_apply_refuses_a_version_that_does_not_know_the_schema(tmp_path, cfg):
    old, new = migrated_install(cfg, tmp_path)
    ue.apply(cfg, new, Service(), readiness=ready, blockers=no_blockers)
    set_revision(cfg, "0015")
    service = Service()
    with pytest.raises(ue.UpdateError, match="does not know"):
        ue.apply(cfg, old, service, readiness=ready, blockers=no_blockers)
    assert service.calls == [] and os.readlink(cfg.root / "current") == f"versions/{new}"


def test_snapshot_metadata_receipts_and_app_data_are_untouched(tmp_path, cfg):
    data = cfg.db_path.parent
    keep = {"profiles.json": b'{"p": 1}', ".env": b"SECRET=1", "tokens/t.json": b'{"t": 1}',
            "reports/r.json": b"{}", "logs/x.log": b"log"}
    for rel, body in keep.items():
        path = data / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        os.utime(path, (1, 1))
    old, new = installed(cfg, tmp_path)
    ue.apply(cfg, new, Service(), readiness=ready, blockers=no_blockers)
    tx = ue.load_state(cfg)["last"]["tx"]
    meta_path = cfg.state_dir / "backups" / f"data-{tx}.json"
    meta = json.loads(meta_path.read_text())
    assert meta["sha256"] == hashlib.sha256((cfg.state_dir / "backups" / f"data-{tx}.db").read_bytes()).hexdigest()
    assert meta["config"]["db_path"] == str(cfg.db_path) and meta["from_version"] == "1.1.0"
    assert oct(meta_path.stat().st_mode & 0o777) == "0o600"
    for rel, body in keep.items():
        assert (data / rel).read_bytes() == body and (data / rel).stat().st_mtime == 1, rel
    receipt = json.loads((cfg.state_dir / "receipts" / f"{tx}.json").read_text())
    assert receipt["schema"] == ue.RECEIPT_SCHEMA and receipt["outcome"]["outcome"] == "committed"
    assert receipt["outcome"]["schema_before"] is None and receipt["outcome"]["snapshot"] == tx


def test_database_must_be_outside_the_update_root(tmp_path, cfg):
    with pytest.raises(ue.UpdateError, match="outside the update root"):
        ue.load_config(config_file(tmp_path, cfg, db_path=str(cfg.root / "data.db")))


def test_interrupted_restore_is_finished_by_recovery(tmp_path, cfg):
    old, new = installed(cfg, tmp_path)
    state = ue.load_state(cfg)
    state["tx"] = {"id": "a" * 16, "kind": "restore", "phase": "restoring", "target": old, "from": old,
                   "backup": None, "snapshot": "b" * 16, "pre_restore": None}
    ue.save_state(cfg, state)
    service = Service()
    assert ue.recover(cfg, service, ready) == "restore_interrupted"
    assert service.calls == ["start"] and ue.load_state(cfg)["tx"] is None


# --- install kind and the operator API ----------------------------------------------------------


def test_install_kind_gives_dev_and_unmanaged_installs_manual_instructions(tmp_path, cfg):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    assert ue.install_kind(checkout, cfg.root)[0] == "dev"
    package = tmp_path / "package"
    package.mkdir()
    (package / "BUILD_INFO.json").write_text(json.dumps({"channel": "dev", "version": "1.2.0"}))
    assert ue.install_kind(package, cfg.root)[0] == "dev"
    (package / "BUILD_INFO.json").write_text(json.dumps({"channel": "stable", "version": "1.2.0",
                                                          "source_dirty": False}))
    assert ue.install_kind(package, cfg.root)[0] == "unmanaged"
    vid = staged(cfg, tmp_path, "1.2.0")
    assert ue.install_kind(cfg.versions / vid, cfg.root)[0] == "release"
    assert ue.manual_instructions("release", PRODUCT) == []
    assert any("Back up" in step for step in ue.manual_instructions("dev", PRODUCT))


def test_update_api_is_operator_only_and_refuses_dev_installs(make_client):
    client = make_client()
    signed_in = agent = False

    @client.app.middleware("http")
    async def operator_session(request, call_next):
        if signed_in:
            request.state.user = {"email": "operator@example.invalid"}
        if agent:
            request.state.agent_grant = {"id": "test"}
        return await call_next(request)
    with client:
        assert client.get("/api/app-updates").status_code == 403
        assert client.post("/api/app-updates/apply", json={"version_id": "1.2.0-abc"}).status_code == 403
        signed_in = True
        body = client.get("/api/app-updates").json()
        assert body["configured"] is False and body["manual_instructions"]
        refused = client.post("/api/app-updates/apply", json={"version_id": "1.2.0-abc"})
        assert refused.status_code == 409 and "manual_instructions" in refused.text
        assert client.post("/api/app-updates/stage", json={"name": "../x"}).status_code == 422
        assert client.post("/api/app-updates/apply", json={"version_id": "x", "force": True}).status_code == 422
        agent = True
        assert client.get("/api/app-updates").status_code == 403
