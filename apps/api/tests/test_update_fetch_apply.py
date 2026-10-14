"""s5-apply: a release fetched from the (synthetic) GitHub Releases API goes through the existing
verify -> stage -> drain -> snapshot -> atomic switch -> health check -> rollback flow.

Nothing here reimplements the engine: fetch_and_stage() must end in ue.stage(), and the switch
is ue.apply() with the same recorder service and injected readiness the engine tests use.
Everything is synthetic and inside tmp_path; no network leaves loopback.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

import release_fetch as rf
import update_engine as ue
from tests.test_release_fetch import TAG, listing, publish, server  # noqa: F401 - server is a fixture
from tests.test_release_verify import make_release, sha
from tests.test_update_engine import (Service, cfg, fake_builder, installed, marker, no_blockers,  # noqa: F401
                                      ready, staged, this_host)  # noqa: F401 - fixtures


TRANSPORT = dict(allowed_hosts=frozenset({"127.0.0.1"}), require_https=False)


def overrides(server):
    return dict(api_base=server.base, **TRANSPORT)


def publish_version(server, tmp_path, version="1.2.0", **fields):
    release = make_release(tmp_path, version=version, name=f"pub-{version}")
    publish(server, [listing(server, release, tag=f"v{version}", version=version,
                             prerelease="-" in version, **fields)])
    return release, sha(release.manifest_bytes)


def fetch(cfg, server, version="1.2.0", digest=None, channel="stable", **kwargs):
    return rf.fetch_and_stage(cfg, channel, version, digest, builder=fake_builder, **overrides(server), **kwargs)


def refused(cfg, server, *args, **kwargs) -> str:
    with pytest.raises(rf.FetchError) as exc:
        fetch(cfg, server, *args, **kwargs)
    return " | ".join(exc.value.problems)


def downloads(server):
    return [r for r in server.requests if r["path"].startswith("/dl/")]


def untouched(cfg, old, inbox_empty=True):
    assert ue.load_state(cfg)["tx"] is None
    assert os.readlink(cfg.root / "current") == f"versions/{old}"
    if inbox_empty:
        assert os.listdir(cfg.inbox) == []


@pytest.fixture
def running(tmp_path, cfg):
    old = staged(cfg, tmp_path, "1.1.0")
    ue.activate_initial(cfg, old)
    for item in cfg.inbox.iterdir():
        item.unlink()
    return old


# --- happy path --------------------------------------------------------------------------


def test_check_describes_the_release_without_downloading_or_changing_anything(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)
    found = rf.check(cfg, "stable", **overrides(server))
    shown = rf.describe(found)
    assert shown["version"] == "1.2.0" and shown["change"] == "upgrade" and shown["notes"] == "Notes"
    assert shown["repository"] == "gptkiosk/rbp-control-dashboard" and shown["manifest_sha256"] == digest
    assert shown["authenticity"].startswith("unverified")
    assert downloads(server) == []
    untouched(cfg, running)
    assert all("authorization" not in {k.lower() for k in r["headers"]} for r in server.requests)


def test_fetch_stages_a_verified_version_and_switches_nothing(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)
    result = fetch(cfg, server, digest=digest)
    assert result["version"] == "1.2.0" and result["already_staged"] is False
    assert ue.read_receipt(cfg, result["id"])["authenticity"]
    untouched(cfg, running)  # not applied; inbox is emptied after staging
    assert ue.load_state(cfg)["last"]["outcome"] == "staged"


def test_staged_fetch_is_applied_by_the_existing_flow_with_snapshot_and_commit(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)
    vid = fetch(cfg, server, digest=digest)["id"]
    service = Service()
    ue.apply(cfg, vid, service, readiness=ready, blockers=no_blockers)
    assert service.calls == ["stop", "start"]
    assert os.readlink(cfg.root / "current") == f"versions/{vid}"
    assert os.readlink(cfg.root / "previous") == f"versions/{running}"
    assert list((cfg.state_dir / "backups").glob("data-*.db"))
    assert ue.load_state(cfg)["last"]["outcome"] == "committed"


def test_fetched_version_that_fails_health_is_rolled_back_automatically(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)
    vid = fetch(cfg, server, digest=digest)["id"]
    service = Service()
    with pytest.raises(ue.UpdateError, match="rolled back"):
        ue.apply(cfg, vid, service, readiness=lambda c, v, s: (v != "1.2.0", "synthetic"), blockers=no_blockers)
    untouched(cfg, running, inbox_empty=False)
    assert marker(cfg) == [("before",)]
    assert ue.load_state(cfg)["last"]["outcome"] == "rolled_back"


def test_fetched_version_whose_service_will_not_start_is_rolled_back(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)
    vid = fetch(cfg, server, digest=digest)["id"]

    class FailsOnce(Service):
        def start(self):
            self.calls.append("start")
            if self.calls.count("start") == 1:
                raise ue.UpdateError("synthetic start failure")

    with pytest.raises(ue.UpdateError, match="synthetic start failure"):
        ue.apply(cfg, vid, FailsOnce(), readiness=ready, blockers=no_blockers)
    untouched(cfg, running, inbox_empty=False)
    assert ue.load_state(cfg)["last"]["outcome"] == "rolled_back"


# --- nothing is stopped, drained or switched unless the package verified --------------------


def test_confirmed_version_must_still_be_the_newest(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path, "1.3.0")
    assert "now 1.3.0, not 1.2.0" in refused(cfg, server, "1.2.0", digest)
    assert downloads(server) == []
    untouched(cfg, running)


def test_wrong_trust_pin_is_refused_and_leaves_no_version_or_inbox_file(tmp_path, cfg, server, running):
    publish_version(server, tmp_path)
    assert "package refused" in refused(cfg, server, digest="0" * 64)
    untouched(cfg, running)
    assert [v["id"] for v in ue.status(cfg)["versions"]] == [running]


def test_missing_pin_with_pinned_digest_trust_is_refused(tmp_path, cfg, server, running):
    publish_version(server, tmp_path)
    assert refused(cfg, server, digest=None)
    untouched(cfg, running)


def test_tampered_archive_is_refused_before_staging(tmp_path, cfg, server, running):
    release, digest = publish_version(server, tmp_path)
    archive = release.artifact_path.read_bytes()
    middle = len(archive) // 2
    bad = archive[:middle] + bytes([archive[middle] ^ 0xFF]) + archive[middle + 1:]
    server.routes[f"/dl/{TAG}/rcd-1.2.0-linux-arm64.tar.gz"] = bad
    assert "sha256 differs" in refused(cfg, server, digest=digest)
    untouched(cfg, running)
    assert [v["id"] for v in ue.status(cfg)["versions"]] == [running]


def test_tamper_with_a_matching_listing_digest_is_still_caught_by_the_manifest(tmp_path, cfg, server, running):
    release, digest = publish_version(server, tmp_path)
    archive = release.artifact_path.read_bytes()
    middle = len(archive) // 2
    bad = archive[:middle] + bytes([archive[middle] ^ 0xFF]) + archive[middle + 1:]
    route = "/repos/gptkiosk/rbp-control-dashboard/releases"
    server.routes[f"/dl/{TAG}/rcd-1.2.0-linux-arm64.tar.gz"] = bad
    server.routes[route] = server.routes[route].replace(
        sha(archive).encode(), sha(bad).encode())  # a hostile listing that agrees with the hostile archive
    assert "package refused" in refused(cfg, server, digest=digest)
    untouched(cfg, running)


def test_downgrade_and_same_version_are_never_offered(tmp_path, cfg, server, running):
    publish_version(server, tmp_path, "1.0.0")
    assert "no newer release" in refused(cfg, server, "1.0.0")
    publish_version(server, tmp_path, "1.1.0")
    assert "no newer release" in refused(cfg, server, "1.1.0")
    assert downloads(server) == []


def test_prerelease_channel_needs_the_helper_opt_in(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path, "1.3.0-rc.1")
    assert "prerelease channel is off" in refused(cfg, server, "1.3.0-rc.1", digest, channel="prerelease")
    assert "no newer release" in refused(cfg, server, "1.3.0-rc.1", digest, channel="stable")
    assert downloads(server) == []
    opted_in = replace(cfg, allow_prerelease=True)
    result = fetch(opted_in, server, "1.3.0-rc.1", digest, channel="prerelease")
    assert result["version"] == "1.3.0-rc.1"
    untouched(cfg, running)


def test_failed_runtime_build_leaves_no_version_and_clears_the_inbox(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)

    def broken(cfg, app_dir, release):
        raise RuntimeError("synthetic dependency install failure")

    with pytest.raises(RuntimeError):
        rf.fetch_and_stage(cfg, "stable", "1.2.0", digest, builder=broken, **overrides(server))
    untouched(cfg, running)
    assert [v["id"] for v in ue.status(cfg)["versions"]] == [running]


# --- transport faults while fetching -----------------------------------------------------


def test_partial_download_stages_nothing_and_a_retry_succeeds(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)
    route = f"/dl/{TAG}/rcd-1.2.0-linux-arm64.tar.gz"
    full = server.routes[route]

    def truncated(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(full)))
        handler.end_headers()
        handler.wfile.write(full[: len(full) // 2])
        handler.wfile.flush()
        handler.close_connection = True

    server.routes[route] = truncated
    assert refused(cfg, server, digest=digest)
    untouched(cfg, running)
    server.routes[route] = full
    assert fetch(cfg, server, digest=digest)["version"] == "1.2.0"


def test_redirect_off_the_allowlist_stages_nothing(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)
    server.routes[f"/dl/{TAG}/rcd-1.2.0-linux-arm64.tar.gz"] = (302, {"Location": "http://evil.example/x"}, b"")
    assert "evil.example" in refused(cfg, server, digest=digest)
    untouched(cfg, running)


def test_disk_full_stages_nothing(tmp_path, cfg, server, running, monkeypatch):
    _, digest = publish_version(server, tmp_path)
    monkeypatch.setattr(rf.shutil, "disk_usage", lambda p: type("U", (), {"free": 1024})())
    assert "not enough free disk space" in refused(cfg, server, digest=digest)
    untouched(cfg, running)


# --- interruption ----------------------------------------------------------------------


def test_stale_partial_from_a_killed_download_does_not_block_a_retry(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)
    (cfg.inbox / ".rcd-1.2.0-linux-arm64.tar.gz.partial").write_bytes(b"half")
    assert fetch(cfg, server, digest=digest)["version"] == "1.2.0"
    untouched(cfg, running)


def test_complete_set_left_by_a_killed_fetch_is_reverified_and_reused(tmp_path, cfg, server, running):
    release, digest = publish_version(server, tmp_path)
    names = rf.asset_names("rcd", "1.2.0", cfg.platform)
    (cfg.inbox / names["manifest"]).write_bytes(release.manifest_path.read_bytes())
    (cfg.inbox / names["archive"]).write_bytes(release.artifact_path.read_bytes())
    (cfg.inbox / names["signature"]).write_bytes(b"-----BEGIN SSH SIGNATURE-----\nsynthetic\n")
    assert fetch(cfg, server, digest=digest)["version"] == "1.2.0"
    assert downloads(server) == []
    untouched(cfg, running)


def test_half_a_set_or_a_corrupt_leftover_is_replaced_not_trusted(tmp_path, cfg, server, running):
    _, digest = publish_version(server, tmp_path)
    names = rf.asset_names("rcd", "1.2.0", cfg.platform)
    (cfg.inbox / names["archive"]).write_bytes(b"corrupt")
    assert fetch(cfg, server, digest=digest)["version"] == "1.2.0"
    assert len(downloads(server)) == 3


def test_no_fetch_while_an_interrupted_transaction_awaits_recovery(tmp_path, cfg, server, running):
    """Recovery itself is the engine's (test_update_engine); a fetch must not run past it."""
    _, digest = publish_version(server, tmp_path)
    state = ue.load_state(cfg)
    state["tx"] = {"id": "ab" * 8, "kind": "apply", "phase": "prepared", "target": running, "from": running,
                   "started_at": 1}
    ue.save_state(cfg, state)
    with pytest.raises(rf.FetchError, match="interrupted"):
        fetch(cfg, server, digest=digest)
    assert os.listdir(cfg.inbox) == []
    assert [v["id"] for v in ue.status(cfg)["versions"]] == [running]
