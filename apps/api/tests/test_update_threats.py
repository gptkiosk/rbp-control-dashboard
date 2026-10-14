"""Adversarial threat-table tests for the release fetch path (s8-unit).

Each test is tagged with @threat("<slug>"). THREAT_IDS is the s2_design threat-table test-ID
mapping.  Keeping the ID on the pytest marker makes it visible in collection output and prevents a
new threat case from silently becoming untraceable.

Reuses the loopback mock release server and synthetic packages from test_release_fetch; no real
network, no gh, no token. Slugs without a case here are covered in test_release_fetch.py.
"""

from __future__ import annotations

import errno
import os
import urllib.request

import pytest

import release_fetch as rf
import release_verify as rv
from tests.test_release_fetch import (  # noqa: F401 - fixtures
    TAG, candidate, config, inbox, listing, publish, published, refused, server)
from tests.test_release_verify import PLATFORM, PRODUCT, make_release, sha

THREAT_IDS: dict[str, str] = {
    "partial-download": "S2-UT-01",
    "timeout": "S2-UT-02",
    "bad-redirect-offhost": "S2-UT-03",
    "bad-redirect-http": "S2-UT-04",
    "oversize-asset": "S2-UT-05",
    "non-allowlisted-asset": "S2-UT-06",
    "wrong-repo-product-arch-os": "S2-UT-07",
    "tampered-archive": "S2-UT-08",
    "tampered-manifest": "S2-UT-09",
    "bad-signature": "S2-UT-10",
    "downgrade": "S2-UT-11",
    "disk-full": "S2-UT-12",
}
SLUGS_SEEN: set[str] = set()


def threat(slug: str):
    assert slug in THREAT_IDS, slug
    SLUGS_SEEN.add(slug)
    def decorate(case):
        case.s2_test_id = THREAT_IDS[slug]
        return case
    return decorate


def route(name: str) -> str:
    return f"/dl/{TAG}/{name}"


# --- interrupted / partial transfer ----------------------------------------------------


@threat("partial-download")
def test_partial_asset_transfer_is_discarded(server, inbox, published):
    """The local release server closes mid-body; no partial or promoted asset may survive."""
    cfg, cand = candidate(server, inbox, published)
    archive = cand.asset("archive")

    def truncated(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(archive.size))
        handler.end_headers()
        handler.wfile.write(b"x" * (archive.size // 2))
        handler.wfile.flush()
        handler.close_connection = True

    server.routes[route(archive.name)] = truncated
    message = refused(rf.download_assets, cfg, cand)
    assert "transfer failed" in message or "ended early" in message
    assert os.listdir(inbox) == []


# --- timeout ---------------------------------------------------------------------------


@threat("timeout")
def test_release_listing_that_stalls_is_cut_off(server, inbox):
    import time

    def stall(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "1000")
        handler.end_headers()
        handler.wfile.write(b"[")
        handler.wfile.flush()
        time.sleep(2)

    server.routes[f"/repos/{rv.OFFICIAL_REPOSITORIES[PRODUCT]}/releases"] = stall
    started = time.monotonic()
    refused(rf.query_release, config(server, inbox, limits=rf.Limits(io_timeout=0.4)))
    assert time.monotonic() - started < 3


@threat("timeout")
def test_server_that_never_answers_the_download_request(server, inbox, published):
    import time
    cfg, cand = candidate(server, inbox, published, limits=rf.Limits(io_timeout=0.4))
    server.routes[route(cand.asset("manifest").name)] = lambda handler: time.sleep(2)
    started = time.monotonic()
    refused(rf.download_assets, cfg, cand)
    assert time.monotonic() - started < 3
    assert os.listdir(inbox) == []


# --- redirects -------------------------------------------------------------------------


@threat("bad-redirect-offhost")
@pytest.mark.parametrize("kind", ["manifest", "signature", "archive"])
def test_offhost_redirect_is_refused_for_every_asset(server, inbox, published, kind):
    cfg, cand = candidate(server, inbox, published)
    server.routes[route(cand.asset(kind).name)] = (302, {"Location": "http://127.0.0.2:1/x"}, b"")
    assert "not an allowed" in refused(rf.download_assets, cfg, cand)
    assert os.listdir(inbox) == []


@threat("bad-redirect-offhost")
def test_offhost_redirect_from_the_release_listing_is_refused(server, inbox):
    server.routes[f"/repos/{rv.OFFICIAL_REPOSITORIES[PRODUCT]}/releases"] = (
        302, {"Location": "http://127.0.0.2:1/releases"}, b"")
    assert "not an allowed" in refused(rf.query_release, config(server, inbox))


@threat("bad-redirect-http")
def test_https_to_http_redirect_is_refused_in_production_config():
    cfg = rf.FetchConfig(product=PRODUCT, platform=PLATFORM, inbox="/nonexistent")
    handler = rf._Redirects(cfg)
    req = urllib.request.Request("https://github.com/gptkiosk/rbp-control-dashboard/releases/download/v1/x")
    for target in ("http://github.com/x", "http://objects.githubusercontent.com/x"):
        with pytest.raises(rf.FetchError):
            handler.redirect_request(req, None, 302, "Found", {}, target)
    # An https redirect to another allowed host is fine.
    new = handler.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/obj")
    assert new.full_url == "https://objects.githubusercontent.com/obj"


@threat("bad-redirect-http")
def test_redirect_drops_credentials_headers():
    cfg = rf.FetchConfig(product=PRODUCT, platform=PLATFORM, inbox="/nonexistent")
    req = urllib.request.Request("https://github.com/x", headers={
        "Authorization": "token secret", "Cookie": "a=b", "Accept": "application/octet-stream"})
    new = rf._Redirects(cfg).redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/o")
    names = {k.lower() for k, _ in new.header_items()}
    assert "authorization" not in names and "cookie" not in names and "accept" in names


@threat("bad-redirect-http")
def test_production_config_refuses_a_plain_http_asset_url(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    strict = rf.FetchConfig(product=PRODUCT, platform=PLATFORM, inbox=inbox, installed_version="1.1.0")
    assert "non-https" in refused(rf._request, strict, cand.asset("archive").url, "x", None)


# --- oversize --------------------------------------------------------------------------


@threat("oversize-asset")
def test_listing_larger_than_the_cap_is_refused_before_any_download(server, inbox, published):
    _, obj = published
    obj["assets"][2]["size"] = rv.MAX_ARTIFACT_BYTES + 1
    publish(server, [obj])
    assert "size outside" in refused(rf.query_release, config(server, inbox))
    assert not any(r["path"].startswith("/dl/") for r in server.requests)


@threat("oversize-asset")
def test_content_length_over_the_cap_is_refused(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    name = cand.asset("signature").name
    server.routes[route(name)] = (200, {"Content-Length": str(rv.MAX_SIGNATURE_BYTES * 100)}, b"x")
    assert refused(rf.download_assets, cfg, cand)
    assert os.listdir(inbox) == []


# --- non-allowlisted assets ------------------------------------------------------------


@threat("non-allowlisted-asset")
@pytest.mark.parametrize("renamed", [
    "{base}.tar.gz.exe", "{base}.tar.gz/../../x", "{base}.TAR.GZ", " {base}.tar.gz", "{base}.tgz",
    "{base}.manifest.json.sig.bak", "SHA256SUMS",
])
def test_lookalike_names_do_not_satisfy_the_allowlist(server, inbox, published, renamed):
    _, obj = published
    base = f"{PRODUCT}-1.2.0-{PLATFORM}"
    obj["assets"][2]["name"] = renamed.format(base=base)
    publish(server, [obj])
    assert "needs exactly one asset" in refused(rf.query_release, config(server, inbox))


@threat("non-allowlisted-asset")
def test_only_other_platform_and_product_assets_are_refused(server, inbox, tmp_path):
    other = make_release(tmp_path, product="mcd", platform="darwin-arm64", name="o")
    obj = listing(server, other)
    for asset in obj["assets"]:
        asset["name"] = asset["name"].replace(f"{PRODUCT}-", "mcd-").replace(PLATFORM, "darwin-arm64")
    publish(server, [obj])
    assert "needs exactly one asset" in refused(rf.query_release, config(server, inbox))


# --- wrong repo / product / arch / OS --------------------------------------------------


@threat("wrong-repo-product-arch-os")
@pytest.mark.parametrize("url", [
    "https://github.com/gptkiosk/mac-control-dashboard/releases/download/v1.2.0/{n}",
    "https://github.com/attacker/rbp-control-dashboard/releases/download/v1.2.0/{n}",
    "https://github.com/gptkiosk/rbp-control-dashboard/releases/download/v9.9.9/{n}",
    "https://github.com/gptkiosk/rbp-control-dashboard/archive/{n}",
])
def test_asset_url_must_be_this_repositorys_tag_download(server, inbox, published, url):
    _, obj = published
    obj["assets"][0]["browser_download_url"] = url.format(n=obj["assets"][0]["name"])
    publish(server, [obj])
    assert "does not point at" in refused(rf.query_release, config(server, inbox))


@threat("wrong-repo-product-arch-os")
def test_release_from_the_other_product_repository_is_never_queried(server, inbox, published):
    refused(rf.query_release, config(server, inbox, repository=rv.OFFICIAL_REPOSITORIES["mcd"]))
    assert server.requests == []


# --- tampering and signatures ----------------------------------------------------------


@threat("tampered-archive")
@pytest.mark.parametrize("offset", [0, 100, -1])
def test_any_flipped_archive_byte_is_refused(server, inbox, tmp_path, offset):
    release = make_release(tmp_path)
    obj = listing(server, release)
    for asset in obj["assets"]:
        asset.pop("digest")
    name = rf.asset_names(PRODUCT, "1.2.0", PLATFORM)["archive"]
    body = bytearray(release.artifact_path.read_bytes())
    body[offset] ^= 0x01
    server.routes[route(name)] = bytes(body)
    publish(server, [obj])
    cfg = config(server, inbox)
    refused(rf.fetch_and_verify, cfg, rf.query_release(cfg), manifest_sha256=sha(release.manifest_bytes))
    assert os.listdir(inbox) == []


@threat("tampered-archive")
def test_truncated_archive_with_a_matching_listing_size_is_refused(server, inbox, tmp_path):
    release = make_release(tmp_path)
    obj = listing(server, release)
    name = rf.asset_names(PRODUCT, "1.2.0", PLATFORM)["archive"]
    body = release.artifact_path.read_bytes()[:-50]
    server.routes[route(name)] = body
    for asset in obj["assets"]:
        asset.pop("digest")
        asset["size"] = len(server.routes[route(asset["name"])])
    publish(server, [obj])
    cfg = config(server, inbox)
    refused(rf.fetch_and_verify, cfg, rf.query_release(cfg), manifest_sha256=sha(release.manifest_bytes))
    assert os.listdir(inbox) == []


@threat("tampered-manifest")
def test_manifest_with_trailing_data_or_duplicate_keys_is_refused(server, inbox, tmp_path):
    release = make_release(tmp_path)
    for tampered in (release.manifest_bytes + b"\n{}", release.manifest_bytes.replace(b"{", b'{"version":"9.9.9",', 1)):
        obj = listing(server, release)
        name = rf.asset_names(PRODUCT, "1.2.0", PLATFORM)["manifest"]
        server.routes[route(name)] = tampered
        for asset in obj["assets"]:
            asset.pop("digest")
            asset["size"] = len(server.routes[route(asset["name"])])
        publish(server, [obj])
        cfg = config(server, inbox, trust={"kind": "pinned-digest"})
        refused(rf.fetch_and_verify, cfg, rf.query_release(cfg), manifest_sha256=sha(tampered))
        assert os.listdir(inbox) == []


@threat("bad-signature")
@pytest.mark.parametrize("sig", [b"", b"not a signature", b"-----BEGIN SSH SIGNATURE-----\n", b"\x00" * 64])
def test_garbage_signature_fails_closed_under_an_ssh_trust_root(server, inbox, tmp_path, sig):
    signers = tmp_path / "allowed_signers"
    signers.write_text('release@example namespaces="dashboard-release" ssh-ed25519 AAAA\n')
    signers.chmod(0o600)
    release = make_release(tmp_path)
    obj = listing(server, release)
    name = rf.asset_names(PRODUCT, "1.2.0", PLATFORM)["signature"]
    server.routes[route(name)] = sig or b"x"
    for asset in obj["assets"]:
        asset.pop("digest")
        asset["size"] = len(server.routes[route(asset["name"])])
    publish(server, [obj])
    trust = {"kind": "ssh-signature", "allowed_signers": str(signers), "identity": "release@example"}
    cfg = config(server, inbox, trust=trust)
    refused(rf.fetch_and_verify, cfg, rf.query_release(cfg))
    assert os.listdir(inbox) == []


# --- downgrade -------------------------------------------------------------------------


@threat("downgrade")
def test_a_replayed_older_release_is_never_offered(server, inbox, tmp_path):
    old = make_release(tmp_path, version="1.0.0", name="old")
    publish(server, [listing(server, old, "v1.0.0", "1.0.0")])
    assert rf.query_release(config(server, inbox, installed_version="1.1.0")) is None
    assert server.requests and not any(r["path"].startswith("/dl/") for r in server.requests)


@threat("downgrade")
def test_prerelease_of_the_installed_version_is_not_an_upgrade(server, inbox, tmp_path):
    pre = make_release(tmp_path, version="1.1.0-rc.1", name="p")
    publish(server, [listing(server, pre, "v1.1.0-rc.1", "1.1.0-rc.1", True)])
    assert rf.query_release(config(server, inbox, channel="prerelease", installed_version="1.1.0")) is None


# --- disk full -------------------------------------------------------------------------


@threat("disk-full")
@pytest.mark.parametrize("where", ["fsync", "link"])
def test_enospc_on_fsync_or_promote_leaves_the_inbox_empty(server, inbox, published, monkeypatch, where):
    cfg, cand = candidate(server, inbox, published)
    real = getattr(os, where)

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, where, full)
    with pytest.raises(rf.FetchError) if where == "fsync" else pytest.raises(OSError):
        rf.download_assets(cfg, cand)
    monkeypatch.setattr(os, where, real)
    assert os.listdir(inbox) == []


@threat("disk-full")
def test_free_space_is_checked_against_the_listed_sizes_plus_margin(server, inbox, published, monkeypatch):
    import shutil
    cfg, cand = candidate(server, inbox, published, limits=rf.Limits(disk_margin_bytes=0))
    need = sum(a.size for a in cand.assets)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(need * 2, need, need - 1))
    assert "not enough free disk" in refused(rf.download_assets, cfg, cand)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(need * 2, need, need))
    rf.download_assets(cfg, cand)


# --- bookkeeping -----------------------------------------------------------------------


def test_every_threat_has_an_id():
    assert set(THREAT_IDS) == SLUGS_SEEN
    assert len(set(THREAT_IDS.values())) == len(THREAT_IDS)
    cases = [value for value in globals().values() if callable(value) and hasattr(value, "s2_test_id")]
    assert {case.s2_test_id for case in cases} == set(THREAT_IDS.values())
