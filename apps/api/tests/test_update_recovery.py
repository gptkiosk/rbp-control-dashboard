"""Out-of-app recovery CLI (s5-recovery-cli): status, versions, rollback, restore, recover.

Synthetic roots under tmp_path, a recording service and injected readiness, as in
test_update_engine.py. Nothing here touches the API, a port or a real service manager; the app is
"down" because health_url points at a closed loopback port.
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys

import pytest

import update_engine as ue
import update_recovery as ur
from tests.test_update_engine import (  # noqa: F401  (fixtures)
    Service, cfg, config_file, installed, marker, ready, set_marker, staged, this_host,
)


@pytest.fixture(autouse=True)
def private_helper_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ur, "HERE", tmp_path)  # the pinned-helper directory check needs an owner-only folder


@pytest.fixture
def db_schema(cfg):
    con = sqlite3.connect(cfg.db_path)
    con.executescript(
        'CREATE TABLE run (id INTEGER PRIMARY KEY, card_id INTEGER, ended_at INTEGER, stage TEXT);'
        'CREATE TABLE card (id INTEGER PRIMARY KEY, "column" TEXT, approved_at INTEGER, approval_grant TEXT);'
        'CREATE TABLE project (id INTEGER PRIMARY KEY, state TEXT);'
        'CREATE TABLE project_task (card_id INTEGER PRIMARY KEY, project_id INTEGER);')
    con.commit()
    con.close()


def run(tmp_path, cfg, *argv, answers=(), interactive=True, service=None, json_out=False):
    out = io.StringIO()
    asked: list[str] = []
    queue = list(answers)

    def ask(prompt):
        asked.append(prompt)
        if not queue:
            raise EOFError
        return queue.pop(0)

    args = ["--config", str(config_file(tmp_path, cfg))] + (["--json"] if json_out else []) + list(argv)
    code = ur.main(args, out=out, ask=ask, interactive=interactive, service=service or Service(), readiness=ready)
    return code, out.getvalue(), asked


def switch_state(cfg, tmp_path):
    old, new = installed(cfg, tmp_path)
    ue.apply(cfg, new, Service(), ready, lambda p: [])
    return old, new  # current = new, previous = old


def test_status_reports_app_down_and_state_without_the_api(tmp_path, cfg, db_schema):
    old, new = switch_state(cfg, tmp_path)
    code, text, asked = run(tmp_path, cfg, "status")
    assert code == 0 and not asked
    assert "DOWN" in text and new in text and old in text and "Work in flight none" in text
    code, text, _ = run(tmp_path, cfg, "status", json_out=True)
    body = json.loads(text)
    assert body["ok"] and body["app"]["reachable"] is False
    assert (body["current"], body["previous"]) == (new, old)


def test_versions_and_snapshots_list_roles_and_ids(tmp_path, cfg, db_schema):
    old, new = switch_state(cfg, tmp_path)
    _, text, _ = run(tmp_path, cfg, "versions")
    assert any(l.startswith("current") and new in l for l in text.splitlines())
    assert any(l.startswith("previous") and old in l for l in text.splitlines())
    _, text, _ = run(tmp_path, cfg, "snapshots", json_out=True)
    snaps = json.loads(text)["snapshots"]
    assert len(snaps) == 1 and len(snaps[0]["tx"]) == 16


def test_rollback_asks_and_cancel_changes_nothing(tmp_path, cfg, db_schema):
    old, new = switch_state(cfg, tmp_path)
    for answers in ([], ["yes"], ["", ], [new]):
        service = Service()
        code, text, asked = run(tmp_path, cfg, "rollback", answers=answers, service=service)
        assert code == 3 and "Nothing was changed" in text and len(asked) == 1
        assert service.calls == []
        assert ue.status(cfg)["current"] == new


def test_rollback_with_typed_id_switches_to_previous(tmp_path, cfg, db_schema):
    old, new = switch_state(cfg, tmp_path)
    service = Service()
    code, text, asked = run(tmp_path, cfg, "rollback", answers=[old], service=service)
    assert code == 0, text
    assert old in asked[0]
    assert service.calls == ["stop", "start"]
    info = ue.status(cfg)
    assert (info["current"], info["previous"]) == (old, new)


def test_rollback_without_terminal_needs_confirm_flag(tmp_path, cfg, db_schema):
    old, new = switch_state(cfg, tmp_path)
    code, text, asked = run(tmp_path, cfg, "rollback", interactive=False)
    assert code == 3 and not asked and f"--confirm {old}" in text
    code, _, _ = run(tmp_path, cfg, "rollback", "--confirm", new, interactive=False)
    assert code == 3 and ue.status(cfg)["current"] == new
    code, _, _ = run(tmp_path, cfg, "rollback", "--confirm", old, interactive=False)
    assert code == 0 and ue.status(cfg)["current"] == old


def test_rollback_refused_without_previous_or_during_interrupted_update(tmp_path, cfg, db_schema):
    old = staged(cfg, tmp_path, "1.1.0")
    ue.activate_initial(cfg, old)
    code, text, asked = run(tmp_path, cfg, "rollback", answers=[old])
    assert code == 1 and "no previous version" in text and not asked
    new = staged(cfg, tmp_path, "1.2.0")
    ue.apply(cfg, new, Service(), ready, lambda p: [])
    state = ue.load_state(cfg)
    state["tx"] = {"id": "ab" * 8, "kind": "switch", "phase": "starting", "target": "x", "from": "y"}
    ue.save_state(cfg, state)
    code, text, _ = run(tmp_path, cfg, "rollback", answers=["x"])
    assert code == 1 and "run recover first" in text


def test_rollback_refused_while_work_is_in_flight(tmp_path, cfg, db_schema):
    old, new = switch_state(cfg, tmp_path)
    con = sqlite3.connect(cfg.db_path)
    con.execute("INSERT INTO run (ended_at, stage) VALUES (NULL, 'running')")
    con.commit()
    con.close()
    service = Service()
    code, text, asked = run(tmp_path, cfg, "rollback", answers=[old], service=service)
    assert code == 1 and "drain first" in text and not asked and service.calls == []
    # app is down, so the operator may knowingly skip the stale row, with a second question
    code, text, asked = run(tmp_path, cfg, "rollback", "--skip-drain", answers=["skip-drain", old], service=service)
    assert code == 0 and len(asked) == 2 and ue.status(cfg)["current"] == old
    # skipping is not possible without a terminal
    code, text, _ = run(tmp_path, cfg, "rollback", "--skip-drain", "--confirm", new, interactive=False)
    assert code == 3 and "needs a terminal" in text


def test_skip_drain_is_refused_while_app_answers(tmp_path, cfg, db_schema, monkeypatch):
    old, new = switch_state(cfg, tmp_path)
    con = sqlite3.connect(cfg.db_path)
    con.execute("INSERT INTO run (ended_at, stage) VALUES (NULL, 'running')")
    con.commit()
    con.close()
    monkeypatch.setattr(ur, "probe_health", lambda c: {"reachable": True, "status": "ok", "version": "1.2.0"})
    code, text, asked = run(tmp_path, cfg, "rollback", "--skip-drain", answers=["skip-drain", old])
    assert code == 1 and "app is answering" in text and not asked
    assert ue.status(cfg)["current"] == new


def test_rollback_refuses_a_schema_the_previous_version_does_not_know(tmp_path, cfg, db_schema):
    old, new = switch_state(cfg, tmp_path)
    con = sqlite3.connect(cfg.db_path)
    con.execute("CREATE TABLE alembic_version (version_num TEXT)")
    con.execute("INSERT INTO alembic_version VALUES ('from_the_future')")
    con.commit()
    con.close()
    code, text, asked = run(tmp_path, cfg, "rollback", answers=[old])
    assert code == 1 and "does not know" in text and "restore" in text and not asked


def test_restore_requires_the_snapshot_id_and_discards_newer_data(tmp_path, cfg, db_schema):
    old, new = switch_state(cfg, tmp_path)
    snap = ue.snapshots(cfg)[0]["tx"]
    set_marker(cfg, "after")
    code, text, asked = run(tmp_path, cfg, "restore", snap, answers=["nope"])
    assert code == 3 and "discards every change" in text and marker(cfg) == [("after",)]
    code, text, _ = run(tmp_path, cfg, "restore", snap, answers=[snap])
    assert code == 0, text
    assert marker(cfg) == [("before",)]


def test_restore_rejects_unknown_or_malformed_snapshot_ids(tmp_path, cfg, db_schema):
    switch_state(cfg, tmp_path)
    for bad in ("../../etc/passwd", "zz", "0" * 16):
        code, text, asked = run(tmp_path, cfg, "restore", bad, answers=[bad])
        assert code == 1 and not asked, bad


def test_restore_with_corrupt_snapshot_changes_nothing(tmp_path, cfg, db_schema):
    switch_state(cfg, tmp_path)
    snap = ue.snapshots(cfg)[0]["tx"]
    set_marker(cfg, "after")
    file = cfg.state_dir / "backups" / f"data-{snap}.db"
    file.chmod(0o600)
    file.write_bytes(file.read_bytes() + b"x")
    service = Service()
    code, text, _ = run(tmp_path, cfg, "restore", snap, answers=[snap], service=service)
    assert code == 1 and "checksum" in text and service.calls == [] and marker(cfg) == [("after",)]


def test_recover_finishes_an_interrupted_update(tmp_path, cfg, db_schema):
    old, new = installed(cfg, tmp_path)
    state = ue.load_state(cfg)
    state["tx"] = {"id": "cd" * 8, "kind": "switch", "phase": "prepared", "target": new, "from": old,
                   "backup": None, "backup_meta": None}
    ue.save_state(cfg, state)
    code, text, _ = run(tmp_path, cfg, "status")
    assert "INTERRUPTED" in text
    code, text, asked = run(tmp_path, cfg, "recover", answers=["no"])
    assert code == 3 and ue.status(cfg)["tx"]
    code, text, _ = run(tmp_path, cfg, "recover", "--yes")
    assert code == 0 and "aborted" in text and ue.status(cfg)["tx"] is None
    code, text, _ = run(tmp_path, cfg, "recover", "--yes")
    assert code == 0 and "Nothing to recover" in text


def test_usage_errors_and_bad_config_exit_nonzero(tmp_path, cfg):
    assert ur.main(["bogus"], out=io.StringIO()) == 2
    assert ur.main([], out=io.StringIO()) == 2
    bad = tmp_path / "missing.json"
    out = io.StringIO()
    assert ur.main(["--config", str(bad), "status"], out=out, interactive=False) == 1


def test_recovery_module_uses_only_the_engine_and_standard_library():
    src = open(ur.__file__).read()
    imports = {l.split()[1].split(".")[0] for l in src.splitlines() if l.startswith(("import ", "from "))}
    assert imports <= {"__future__", "argparse", "json", "os", "sys", "time", "urllib", "pathlib", "typing",
                       "update_engine"}
    assert "requests" not in src and "fastapi" not in src and sys.version_info >= (3, 9)
