"""Update integration (s9): end-to-end flows against a temporary install root, driven through the
real engine and the out-of-app recovery CLI.

Covered: a helper killed mid-switch, a killed helper after the link switch, a migration that
fails readiness, a service start failure, a health failure that rolls back, and recovery CLI use
(recover, refusal without confirmation, and rollback after a clean update).

Everything lives under tmp_path with synthetic packages, a recording service and injected
readiness. A guard fixture refuses any socket connection to port 8800 (the live MCD/API port),
and the crash cases run update_crash_host.py as a separate process.
"""

from __future__ import annotations

import io
import json
import os
import socket

import pytest

import update_engine as ue
import update_recovery as ur
from tests.test_update_engine import (  # noqa: F401  (fixtures)
    Service, cfg, config_file, crash, failing_migration, installed, marker, migrated_install, no_blockers,
    ready, revision_of, set_marker, this_host,
)
from tests.test_update_recovery import db_schema  # noqa: F401  (fixture)

LIVE_PORT = 8800


@pytest.fixture(autouse=True)
def never_touch_live_port(monkeypatch):
    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        if isinstance(address, tuple) and len(address) >= 2 and address[1] == LIVE_PORT:
            raise AssertionError(f"integration test tried to reach the live port {LIVE_PORT}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def private_helper_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ur, "HERE", tmp_path)  # the pinned-helper directory check needs an owner-only folder


def recovery_cli(tmp_path, cfg, *argv, service=None, readiness=ready, interactive=False):
    out = io.StringIO()
    args = ["--config", str(config_file(tmp_path, cfg)), "--json", *argv]
    code = ur.main(args, out=out, ask=None, interactive=interactive, service=service or Service(),
                   readiness=readiness)
    return code, json.loads(out.getvalue() or "{}")


def assert_back_on(cfg, version_id, data):
    assert os.readlink(cfg.root / "current") == f"versions/{version_id}"
    assert marker(cfg) == data
    assert ue.load_state(cfg)["tx"] is None


# --- helper killed mid-switch --------------------------------------------------------------


def test_helper_killed_before_switch_is_recovered_by_the_cli(tmp_path, cfg, db_schema):
    old, new = installed(cfg, tmp_path)
    calls = tmp_path / "calls"
    crash(cfg, op="apply", version_id=new, crash="stop", calls=str(calls))
    assert ue.load_state(cfg)["tx"]["phase"] == "prepared"

    service = Service()
    code, body = recovery_cli(tmp_path, cfg, "recover", "--yes", service=service)
    assert code == 0 and body["outcome"] == "aborted"
    assert service.calls == ["start"]
    assert_back_on(cfg, old, [("before",)])

    code, body = recovery_cli(tmp_path, cfg, "recover", "--yes", service=Service())
    assert code == 0 and body["outcome"] == "nothing to recover"


@pytest.mark.parametrize("healthy", [True, False])
def test_helper_killed_after_switch_commits_or_rolls_back_via_the_cli(tmp_path, cfg, db_schema, healthy):
    old, new = installed(cfg, tmp_path)
    calls = tmp_path / "calls"
    crash(cfg, op="apply", version_id=new, crash="readiness", calls=str(calls))
    assert os.readlink(cfg.root / "current") == f"versions/{new}"
    set_marker(cfg, "written by 1.2.0")

    def readiness(cfg, version, started):
        return (healthy or version == old), version

    service = Service()
    code, body = recovery_cli(tmp_path, cfg, "recover", "--yes", service=service, readiness=readiness)
    assert code == 0
    if healthy:
        assert body["outcome"] == "committed"
        assert_back_on(cfg, new, [("written by 1.2.0",)])
    else:
        assert body["outcome"] == "rolled_back"
        assert_back_on(cfg, old, [("before",)])


def test_recover_without_a_terminal_or_confirm_changes_nothing(tmp_path, cfg, db_schema):
    old, new = installed(cfg, tmp_path)
    crash(cfg, op="apply", version_id=new, crash="stop", calls=str(tmp_path / "calls"))

    service = Service()
    code, body = recovery_cli(tmp_path, cfg, "recover", service=service)
    assert code == 3 and not body["ok"] and "--confirm recover" in body["declined"]
    assert service.calls == []
    assert ue.load_state(cfg)["tx"] is not None  # still interrupted, nothing was started or switched
    assert os.readlink(cfg.root / "current") == f"versions/{old}"


# --- migration, start and health failures ------------------------------------------------------


def test_migration_failure_keeps_the_migrated_schema_and_the_old_code_runs(tmp_path, cfg, db_schema):
    old, new = migrated_install(cfg, tmp_path)
    service = Service()
    with pytest.raises(ue.UpdateError, match="rolled back"):
        ue.apply(cfg, new, service, readiness=failing_migration, blockers=no_blockers)

    assert service.calls == ["stop", "start", "stop", "start"]
    assert os.readlink(cfg.root / "current") == f"versions/{old}"
    assert revision_of(cfg) == "0015" and marker(cfg) == [("written by 1.2.0",)]
    last = ue.load_state(cfg)["last"]
    assert last["outcome"] == "rolled_back" and last["database_restored"] is False
    assert "not restored automatically" in last["detail"]

    code, body = recovery_cli(tmp_path, cfg, "recover", "--yes", service=Service())
    assert code == 0 and body["outcome"] == "nothing to recover"


def test_start_failure_after_switch_rolls_back_and_restores_data(tmp_path, cfg, db_schema):
    old, new = installed(cfg, tmp_path)

    class FailsOnFirstStart(Service):
        def start(self):
            self.calls.append("start")
            if self.calls.count("start") == 1:
                raise ue.UpdateError("synthetic start failure")

    def writes_then_starts(cfg, version, started):
        # The rollback health probe uses this seam too. Only the candidate
        # process could have made the simulated migration write.
        if version == "1.2.0":
            set_marker(cfg, "written by 1.2.0")
        return True, version

    with pytest.raises(ue.UpdateError, match="synthetic start failure"):
        ue.apply(cfg, new, FailsOnFirstStart(), readiness=writes_then_starts, blockers=no_blockers)

    assert_back_on(cfg, old, [("before",)])
    assert ue.load_state(cfg)["last"]["outcome"] == "rolled_back"


def test_health_failure_rolls_back_then_the_cli_reports_the_old_version(tmp_path, cfg, db_schema):
    old, new = installed(cfg, tmp_path)

    def unhealthy_new(cfg, version, started):
        if version == "1.2.0":
            set_marker(cfg, "written by 1.2.0")
            return False, "health reports the wrong version"
        return True, "ok"

    service = Service()
    with pytest.raises(ue.UpdateError, match="rolled back"):
        ue.apply(cfg, new, service, readiness=unhealthy_new, blockers=no_blockers)
    assert service.calls == ["stop", "start", "stop", "start"]
    assert_back_on(cfg, old, [("before",)])

    code, body = recovery_cli(tmp_path, cfg, "versions", service=Service())
    assert code == 0 and body["ok"]


def test_failed_update_can_be_retried_after_a_fix(tmp_path, cfg, db_schema):
    old, new = installed(cfg, tmp_path)
    attempts = []

    def fails_then_passes(cfg, version, started):
        attempts.append(version)
        return (len(attempts) > 2 or version == old), version

    with pytest.raises(ue.UpdateError):
        ue.apply(cfg, new, Service(), readiness=fails_then_passes, blockers=no_blockers)
    assert_back_on(cfg, old, [("before",)])

    ue.apply(cfg, new, Service(), readiness=lambda c, v, s: (True, v), blockers=no_blockers)
    assert os.readlink(cfg.root / "current") == f"versions/{new}"
    assert ue.load_state(cfg)["last"]["outcome"] == "committed"


# --- clean update followed by CLI rollback -----------------------------------------------------


def test_clean_update_then_cli_rollback_restores_the_previous_code_only(tmp_path, cfg, db_schema):
    old, new = installed(cfg, tmp_path)
    ue.apply(cfg, new, Service(), readiness=ready, blockers=no_blockers)
    set_marker(cfg, "written by 1.2.0")

    service = Service()
    code, body = recovery_cli(tmp_path, cfg, "rollback", "--confirm", old, service=service)
    assert code == 0, body
    assert service.calls == ["stop", "start"]
    assert os.readlink(cfg.root / "current") == f"versions/{old}"
    assert marker(cfg) == [("written by 1.2.0",)]  # data is not rolled back by a code rollback
