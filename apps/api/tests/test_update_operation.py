"""The operation record the Updates page shows: ordered steps, their state and a log, for success, refusal and rollback."""
from __future__ import annotations

import json
import os
import time

import pytest

import update_engine as ue
from tests.test_update_engine import (  # noqa: F401  (fixtures)
    Service, cfg, installed, no_blockers, put_in_inbox, ready, staged, this_host, fake_builder,
)


def steps(cfg):
    data = ue.operation_status(cfg)["operation"]
    return {s["name"]: s["state"] for s in data["steps"]}, data


def test_a_successful_update_records_every_step_and_a_readable_log(tmp_path, cfg):  # noqa: F811
    old, new = installed(cfg, tmp_path)
    ue.apply(cfg, new, Service(), readiness=ready, blockers=no_blockers)
    by_name, data = steps(cfg)
    assert data["state"] == "succeeded" and data["version"] == "1.2.0"
    assert by_name == {"verify": "ok", "stage": "ok", "safety": "ok", "snapshot": "ok", "switch": "ok", "health": "ok", "finish": "ok"}
    log = "\n".join(ue.operation_status(cfg)["log"])
    for expected in ("safety: ok", "service stopped", "snapshot: ok", "switch: ok", "health: ok", "result: succeeded"):
        assert expected in log
    for path in (cfg.state_dir / "operation.json", cfg.state_dir / "operation.log"):
        assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_staging_alone_leaves_a_staged_record_and_apply_carries_on_the_same_operation(tmp_path, cfg):  # noqa: F811
    old = staged(cfg, tmp_path, "1.1.0"); ue.activate_initial(cfg, old)
    new = staged(cfg, tmp_path, "1.2.0")
    _, data = steps(cfg)
    assert data["state"] == "staged" and "not installed" in data["message"]
    first_id = data["id"]
    ue.apply(cfg, new, Service(), readiness=ready, blockers=no_blockers)
    by_name, data = steps(cfg)
    assert data["id"] == first_id and data["state"] == "succeeded" and by_name["verify"] == "ok" and by_name["health"] == "ok"


def test_a_refused_update_says_why_and_nothing_was_stopped(tmp_path, cfg):  # noqa: F811
    old, new = installed(cfg, tmp_path)
    service = Service()
    with pytest.raises(ue.UpdateError):
        ue.apply(cfg, new, service, readiness=ready, blockers=lambda p: ["1 agent or chat run(s) still running"])
    by_name, data = steps(cfg)
    assert data["state"] == "failed" and by_name["safety"] == "failed" and "Nothing was stopped" in data["message"]
    assert "still running" in " ".join(s["detail"] for s in data["steps"]) and service.calls == []


def test_a_failed_health_check_is_recorded_as_a_rollback(tmp_path, cfg):  # noqa: F811
    old, new = installed(cfg, tmp_path)
    calls = iter([(False, "health reports version 1.1.0"), (True, "version 1.1.0 healthy")])
    with pytest.raises(ue.UpdateError):
        ue.apply(cfg, new, Service(), readiness=lambda c, v, s: next(calls), blockers=no_blockers)
    by_name, data = steps(cfg)
    assert data["state"] == "rolled_back" and by_name["health"] == "failed" and by_name["finish"] == "failed"
    assert "previous version was restored" in data["message"]


def test_a_refused_package_is_recorded_without_touching_the_install(tmp_path, cfg):  # noqa: F811
    old = staged(cfg, tmp_path, "1.1.0"); ue.activate_initial(cfg, old)
    name, _ = put_in_inbox(cfg, tmp_path, "1.2.0")
    with pytest.raises(ue.UpdateError):
        ue.stage(cfg, name, "0" * 64, builder=fake_builder)                    # the wrong pinned digest
    by_name, data = steps(cfg)
    assert data["state"] == "failed" and by_name["verify"] == "failed"


def test_a_dead_helper_is_shown_as_failed_not_as_running_forever(tmp_path, cfg):  # noqa: F811
    ue.prepare_layout(cfg)
    record = {"id": "abcd1234", "version": "9.9.9", "state": "running", "message": "", "steps": [{"name": "stage", "state": "running", "detail": "", "at": 1}],
              "started_at": int(time.time()) - 600, "updated_at": int(time.time()) - 600}
    (cfg.state_dir / "operation.json").write_text(json.dumps(record))
    shown = ue.operation_status(cfg)
    assert shown["active"] is False and shown["operation"]["state"] == "failed" and "stopped without reporting" in shown["operation"]["message"]


def test_recording_can_never_break_an_update(tmp_path, cfg, monkeypatch):  # noqa: F811
    old, new = installed(cfg, tmp_path)
    monkeypatch.setattr(ue.OperationLog, "_save", lambda self: (_ for _ in ()).throw(OSError("disk full")))
    result = ue.apply(cfg, new, Service(), readiness=ready, blockers=no_blockers)
    assert result["current"] == new                                              # the update itself is unaffected


def test_the_operation_route_works_while_an_update_is_in_progress(tmp_path, monkeypatch, make_client, cfg):  # noqa: F811
    import shutil
    from routes import updates as routes
    from tests.test_update_engine import config_file
    helper_dir = cfg.root / "helper"; helper_dir.mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(config_file(tmp_path, cfg), helper_dir / "helper.json"); (helper_dir / "helper.json").chmod(0o600)
    monkeypatch.setenv("MAC_CONTROL_UPDATE_ROOT", str(cfg.root))
    monkeypatch.setattr(ue, "install_kind", lambda app_root, root: ("release", "packaged"))
    client = make_client()

    @client.app.middleware("http")
    async def session(request, call_next):
        request.state.user = {"email": "operator@example.invalid"}
        return await call_next(request)

    old, new = installed(cfg, tmp_path)
    state = ue.load_state(cfg); state["tx"] = {"id": "t", "kind": "switch", "phase": "starting", "target": new, "from": old}; ue.save_state(cfg, state)   # mid-update
    assert client.post("/api/app-updates/apply", json={"version_id": new}).status_code == 409                          # other routes refuse...
    response = client.get("/api/app-updates/operation")
    assert response.status_code == 200 and response.json()["operation"]["version"] == "1.2.0"                          # ...this one reports


# --------------------------------------------------------------------------------- refreshing the pinned helper

def builder_with_helper(content: bytes):
    def build(cfg, app_dir, release):
        fake_builder(cfg, app_dir, release)
        folder = app_dir / "apps" / "api"; folder.mkdir(parents=True, exist_ok=True)
        for name in ue.HELPER_FILES:
            (folder / name).write_bytes(content + name.encode())
    return build


def test_refresh_helper_adopts_the_current_versions_helper_and_keeps_the_old_copies(tmp_path, cfg):  # noqa: F811
    from tests.test_update_engine import put_in_inbox
    name, digest = put_in_inbox(cfg, tmp_path, "1.1.0")
    vid = ue.stage(cfg, name, digest, builder=builder_with_helper(b"# new helper\n"))["id"]
    ue.activate_initial(cfg, vid)
    helper = cfg.root / "helper"; helper.mkdir(mode=0o700, exist_ok=True)
    for file in ue.HELPER_FILES:
        (helper / file).write_bytes(b"# old helper " + file.encode()); (helper / file).chmod(0o600)
    result = ue.refresh_helper(cfg)
    assert sorted(result["refreshed"]) == sorted(ue.HELPER_FILES) and result["from"] == vid
    for file in ue.HELPER_FILES:
        assert (helper / file).read_bytes() == b"# new helper\n" + file.encode()
        assert (helper / "previous" / file).read_bytes() == b"# old helper " + file.encode()
        assert oct((helper / file).stat().st_mode & 0o777) == "0o600"
    assert ue.refresh_helper(cfg)["refreshed"] == []                                 # nothing to do the second time


def test_refresh_helper_refuses_other_sources_a_missing_install_and_an_update_in_progress(tmp_path, cfg):  # noqa: F811
    with pytest.raises(ue.UpdateError, match="no managed current version"):
        ue.refresh_helper(cfg)
    old, new = installed(cfg, tmp_path)
    (cfg.root / "helper").mkdir(mode=0o700, exist_ok=True)
    with pytest.raises(ue.UpdateError, match="only be refreshed from the current version"):
        ue.refresh_helper(cfg, tmp_path)
    state = ue.load_state(cfg); state["tx"] = {"id": "t", "kind": "switch", "phase": "starting", "target": new, "from": old}; ue.save_state(cfg, state)
    with pytest.raises(ue.UpdateError, match="interrupted"):
        ue.refresh_helper(cfg)
