"""Release fetch (s4-core): query, bounded download and verification, unit and adversarial.

A loopback HTTP server stands in for GitHub; the config's transport overrides point at it.
Packages are synthetic (tests.test_release_verify.make_release). No real network, no gh, no token.
"""

from __future__ import annotations

import errno
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

import release_fetch as rf
import release_verify as rv
from tests.test_release_verify import OTHER_PLATFORM, OTHER_PRODUCT, PLATFORM, PRODUCT, SSH_KEYGEN, make_release, sha

TAG = "v1.2.0"


@pytest.fixture(autouse=True)
def _linux_arm64_host(monkeypatch):
    """The packages are synthetic Linux arm64 releases; the logic under test must not depend on the host
    the suite runs on (a Mac developer machine reports darwin-arm64)."""
    monkeypatch.setattr(rv, "host_platform", lambda: PLATFORM)


class Server:
    """Tiny GitHub stand-in. routes: path -> bytes | (status, headers, body) | callable(handler)."""

    def __init__(self):
        self.routes: dict = {}
        self.requests: list[dict] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.requests.append({"path": self.path, "headers": dict(self.headers)})
                route = outer.routes.get(self.path.split("?")[0])
                if route is None:
                    self.send_error(404)
                elif callable(route):
                    route(self)
                else:
                    status, headers, body = route if isinstance(route, tuple) else (200, {}, route)
                    self.send_response(status)
                    for key, value in headers.items():
                        self.send_header(key, value)
                    if "Content-Length" not in headers:
                        self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    srv = Server()
    yield srv
    srv.close()


@pytest.fixture
def inbox(tmp_path):
    path = tmp_path / "inbox"
    path.mkdir(mode=0o700)
    return path


def config(server, inbox, **kwargs) -> rf.FetchConfig:
    values = dict(product=PRODUCT, platform=PLATFORM, inbox=inbox, api_base=server.base,
                  allowed_hosts=frozenset({"127.0.0.1"}), require_https=False,
                  trust={"kind": "pinned-digest"}, installed_version="1.1.0")
    values.update(kwargs)
    return rf.FetchConfig(**values)


def listing(server, release, tag=TAG, version="1.2.0", prerelease=False, extra_assets=(), **fields) -> dict:
    """Publish a release's three assets on the server and return its API object."""
    names = rf.asset_names(PRODUCT, version, PLATFORM)
    bodies = {"manifest": release.manifest_path.read_bytes(), "archive": release.artifact_path.read_bytes(),
              "signature": b"-----BEGIN SSH SIGNATURE-----\nsynthetic\n"}
    assets = []
    for kind, name in names.items():
        server.routes[f"/dl/{tag}/{name}"] = bodies[kind]
        assets.append({"name": name, "size": len(bodies[kind]), "state": "uploaded",
                       "digest": f"sha256:{sha(bodies[kind])}",
                       "browser_download_url": f"{server.base}/dl/{tag}/{name}"})
    return {"tag_name": tag, "draft": False, "prerelease": prerelease, "body": "Notes", "assets": assets + list(extra_assets),
            "html_url": f"https://github.com/gptkiosk/rbp-control-dashboard/releases/tag/{tag}", **fields}


def publish(server, releases: list) -> None:
    server.routes[f"/repos/{rv.OFFICIAL_REPOSITORIES[PRODUCT]}/releases"] = json.dumps(releases).encode()


@pytest.fixture
def published(server, tmp_path):
    release = make_release(tmp_path)
    obj = listing(server, release)
    publish(server, [obj])
    return release, obj


def candidate(server, inbox, published, **kwargs):
    cfg = config(server, inbox, **kwargs)
    return cfg, rf.query_release(cfg)


def refused(call, *args, **kwargs) -> str:
    with pytest.raises(rf.FetchError) as exc:
        call(*args, **kwargs)
    return " | ".join(exc.value.problems)


# --- query -----------------------------------------------------------------------------


def test_query_returns_the_candidate_with_notes_and_digests(server, inbox, published):
    release, _ = published
    cfg, cand = candidate(server, inbox, published)
    assert (cand.version, cand.tag, cand.change, cand.channel) == ("1.2.0", TAG, "upgrade", "stable")
    assert cand.notes == "Notes" and cand.repository == rv.OFFICIAL_REPOSITORIES[PRODUCT]
    assert cand.manifest_digest == sha(release.manifest_bytes)
    assert {a.name for a in cand.assets} == set(rf.asset_names(PRODUCT, "1.2.0", PLATFORM).values())


def test_query_is_unauthenticated(server, inbox, published, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "should-never-be-sent")
    monkeypatch.setenv("GH_TOKEN", "should-never-be-sent")
    cfg, cand = candidate(server, inbox, published)
    rf.download_assets(cfg, cand)
    assert server.requests
    for request in server.requests:
        lowered = {k.lower() for k in request["headers"]}
        assert "authorization" not in lowered and "cookie" not in lowered
        assert request["headers"]["Accept-Encoding"] == "identity"


def test_stable_channel_skips_prereleases_and_prerelease_channel_takes_them(server, inbox, tmp_path):
    stable = make_release(tmp_path, version="1.2.0", name="a")
    pre = make_release(tmp_path, version="1.3.0-rc.1", name="b")
    publish(server, [listing(server, pre, "v1.3.0-rc.1", "1.3.0-rc.1", True), listing(server, stable)])
    assert rf.query_release(config(server, inbox)).version == "1.2.0"
    assert rf.query_release(config(server, inbox, channel="prerelease")).version == "1.3.0-rc.1"


def test_highest_semver_wins_regardless_of_api_order(server, inbox, tmp_path):
    old = make_release(tmp_path, version="1.2.0", name="a")
    new = make_release(tmp_path, version="1.10.0", name="b")
    publish(server, [listing(server, old), listing(server, new, "v1.10.0", "1.10.0")])
    assert rf.query_release(config(server, inbox)).version == "1.10.0"


def test_drafts_bad_tags_and_flag_mismatches_are_ignored(server, inbox, tmp_path):
    good = make_release(tmp_path, version="1.2.0", name="a")
    other = make_release(tmp_path, version="9.0.0", name="b")
    draft = listing(server, other, "v9.0.0", "9.0.0", draft=True)
    mislabeled = listing(server, other, "v8.0.0", "9.0.0", tag_name="v8.0.0-beta.1", prerelease=False)
    junk = {"tag_name": "latest", "draft": False, "prerelease": False, "assets": []}
    publish(server, [draft, mislabeled, junk, listing(server, good)])
    assert rf.query_release(config(server, inbox, channel="prerelease")).version == "1.2.0"


def test_up_to_date_and_downgrade_offer_nothing(server, inbox, published):
    assert rf.query_release(config(server, inbox, installed_version="1.2.0")) is None
    assert rf.query_release(config(server, inbox, installed_version="2.0.0")) is None


def test_first_install_is_an_install(server, inbox, published):
    assert rf.query_release(config(server, inbox, installed_version=None)).change == "install"


@pytest.mark.parametrize("mutate,expect", [
    (lambda a: a.pop(0), "needs exactly one asset"),
    (lambda a: a.append(dict(a[0])), "needs exactly one asset"),
    (lambda a: a[0].update(browser_download_url="https://evil.example/x"), "does not point at"),
    (lambda a: a[0].update(state="starter"), "not fully uploaded"),
    (lambda a: a[0].update(size=10 ** 9), "size outside"),
    (lambda a: a[0].update(size=0), "size outside"),
    (lambda a: a[0].update(digest="md5:abc"), "unreadable digest"),
])
def test_asset_selection_refuses_a_bad_asset_list(server, inbox, published, mutate, expect):
    _, obj = published
    mutate(obj["assets"])
    publish(server, [obj])
    assert expect in refused(rf.query_release, config(server, inbox))


def test_extra_unlisted_assets_are_ignored_not_downloaded(server, inbox, published):
    release, obj = published
    obj["assets"].append({"name": "evil.sh", "size": 5, "state": "uploaded", "browser_download_url": server.base + "/dl/evil.sh"})
    publish(server, [obj])
    cfg, cand = candidate(server, inbox, published)
    assert "evil.sh" not in {a.name for a in cand.assets}
    rf.download_assets(cfg, cand)
    assert not any(r["path"] == "/dl/evil.sh" for r in server.requests)


def test_wrong_product_repository_and_platform_are_refused_by_config(server, inbox):
    assert "updates rcd only" in refused(rf.query_release, config(server, inbox, product=OTHER_PRODUCT))
    assert "not a supported" in refused(rf.query_release, config(server, inbox, platform=OTHER_PLATFORM))
    assert "not the official" in refused(rf.query_release, config(server, inbox, repository="attacker/rbp-control-dashboard"))
    assert "not the official" in refused(rf.query_release, config(server, inbox, repository=rv.OFFICIAL_REPOSITORIES["mcd"]))
    assert "channel" in refused(rf.query_release, config(server, inbox, channel="nightly"))
    assert "https" in refused(rf.query_release, config(server, inbox, require_https=True))


def test_make_config_pins_the_product(inbox):
    cfg = rf.make_config(inbox, PLATFORM, trust=None)
    assert cfg.product == PRODUCT and cfg.repository is None
    assert refused(rf.make_config, inbox, OTHER_PLATFORM)


def test_garbled_and_oversized_api_answers_are_refused(server, inbox):
    path = f"/repos/{rv.OFFICIAL_REPOSITORIES[PRODUCT]}/releases"
    server.routes[path] = b"{not json"
    assert "not valid JSON" in refused(rf.query_release, config(server, inbox))
    server.routes[path] = b'{"a": 1}'
    assert "unexpected release list" in refused(rf.query_release, config(server, inbox))
    server.routes[path] = b" " * (rf.MAX_API_BYTES + 10)
    assert "larger than the limit" in refused(rf.query_release, config(server, inbox))


def test_http_errors_and_rate_limit_are_reported(server, inbox):
    path = f"/repos/{rv.OFFICIAL_REPOSITORIES[PRODUCT]}/releases"
    server.routes[path] = (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}, b"{}")
    assert "rate limit" in refused(rf.query_release, config(server, inbox))
    server.routes[path] = (500, {}, b"oops")
    assert "HTTP 500" in refused(rf.query_release, config(server, inbox))
    server.routes[path] = (200, {"Content-Encoding": "gzip"}, b"[]")
    assert "content-encoded" in refused(rf.query_release, config(server, inbox))


def test_notes_are_capped_and_html_url_must_be_the_repository(server, inbox, published):
    _, obj = published
    obj["body"] = "x" * (rf.MAX_NOTES_CHARS * 2)
    obj["html_url"] = "https://evil.example/phish"
    publish(server, [obj])
    cand = rf.query_release(config(server, inbox))
    assert len(cand.notes) == rf.MAX_NOTES_CHARS and cand.html_url is None


# --- redirects -------------------------------------------------------------------------


def test_redirect_to_a_host_off_the_allowlist_is_refused(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    name = cand.asset("archive").name
    server.routes[f"/dl/{TAG}/{name}"] = (302, {"Location": "http://localhost:1/steal"}, b"")
    assert "not an allowed" in refused(rf.download_assets, cfg, cand)
    assert os.listdir(inbox) == []


def test_redirect_loop_is_cut_off(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    name = cand.asset("archive").name
    server.routes[f"/dl/{TAG}/{name}"] = (302, {"Location": f"{server.base}/dl/{TAG}/{name}"}, b"")
    assert "too many redirects" in refused(rf.download_assets, cfg, cand)


def test_redirect_within_the_allowlist_is_followed(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    archive = cand.asset("archive")
    body = server.routes[f"/dl/{TAG}/{archive.name}"]
    server.routes[f"/dl/{TAG}/{archive.name}"] = (302, {"Location": "/cdn/object"}, b"")
    server.routes["/cdn/object"] = body
    package = rf.download_assets(cfg, cand)
    assert package.archive.read_bytes() == body


def test_production_config_refuses_http_userinfo_ports_and_foreign_hosts():
    cfg = rf.FetchConfig(product=PRODUCT, platform=PLATFORM, inbox=Path("/nonexistent"))
    for url in ("http://github.com/x", "https://user:pw@github.com/x", "https://github.com:8443/x",
                "https://evilgithub.com/x", "https://github.com.evil.example/x", "ftp://github.com/x", "https://[::1/x"):
        with pytest.raises(rf.FetchError):
            rf.check_url(cfg, url)
    for url in ("https://api.github.com/repos/a/b/releases", "https://github.com/a/b/releases/download/v1/x",
                "https://objects.githubusercontent.com/x", "https://release-assets.githubusercontent.com/x"):
        assert rf.check_url(cfg, url) == url


# --- download limits and failure handling ----------------------------------------------


def test_download_places_exactly_three_private_files(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    package = rf.download_assets(cfg, cand)
    assert sorted(os.listdir(inbox)) == sorted(rf.asset_names(PRODUCT, "1.2.0", PLATFORM).values())
    for path in (package.manifest, package.archive, package.signature):
        assert (path.stat().st_mode & 0o777) == 0o600
    assert package.name == "rcd-1.2.0-linux-arm64"


def test_partial_download_leaves_nothing(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    archive = cand.asset("archive")

    def truncated(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(archive.size))
        handler.end_headers()
        handler.wfile.write(b"x" * (archive.size // 2))
        handler.wfile.flush()
        handler.close_connection = True

    server.routes[f"/dl/{TAG}/{archive.name}"] = truncated
    msg = refused(rf.download_assets, cfg, cand)
    assert "transfer failed" in msg or "ended early" in msg
    assert os.listdir(inbox) == []


def test_stalled_server_times_out(server, inbox, published):
    limits = rf.Limits(io_timeout=0.4)
    cfg, cand = candidate(server, inbox, published, limits=limits)
    archive = cand.asset("archive")

    def stall(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(archive.size))
        handler.end_headers()
        handler.wfile.write(b"x" * 10)
        handler.wfile.flush()
        time.sleep(2)

    server.routes[f"/dl/{TAG}/{archive.name}"] = stall
    started = time.monotonic()
    assert "transfer failed" in refused(rf.download_assets, cfg, cand)
    assert time.monotonic() - started < 3
    assert os.listdir(inbox) == []


def test_slow_download_is_cut_off_by_total_time_and_rate(server, inbox, published):
    limits = rf.Limits(total_seconds=0.3, min_rate_grace=0.0, min_bytes_per_second=1)
    cfg, cand = candidate(server, inbox, published, limits=limits)
    archive = cand.asset("archive")

    def drip(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(archive.size))
        handler.end_headers()
        try:
            for _ in range(archive.size):
                handler.wfile.write(b"x")
                handler.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass

    server.routes[f"/dl/{TAG}/{archive.name}"] = drip
    assert "too long" in refused(rf.download_assets, cfg, cand)
    assert os.listdir(inbox) == []
    limits = rf.Limits(min_rate_grace=0.0, min_bytes_per_second=10 ** 6)
    cfg, cand = candidate(server, inbox, published, limits=limits)
    assert "too slow" in refused(rf.download_assets, cfg, cand)


def test_server_sending_more_than_listed_is_refused(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    archive = cand.asset("archive")

    def flood(handler):
        handler.send_response(200)
        handler.end_headers()  # no Content-Length: only the byte count can stop it
        try:
            handler.wfile.write(b"x" * (archive.size + 5000))
        except OSError:
            pass

    server.routes[f"/dl/{TAG}/{archive.name}"] = flood
    assert "larger than expected" in refused(rf.download_assets, cfg, cand)
    assert os.listdir(inbox) == []


def test_declared_length_that_differs_from_the_listing_is_refused(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    manifest = cand.asset("manifest")
    server.routes[f"/dl/{TAG}/{manifest.name}"] = b"short"
    assert "differs from the release listing" in refused(rf.download_assets, cfg, cand)


def test_body_that_differs_from_the_published_digest_is_refused(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    archive = cand.asset("archive")
    body = bytearray(server.routes[f"/dl/{TAG}/{archive.name}"])
    body[100] ^= 0xFF
    server.routes[f"/dl/{TAG}/{archive.name}"] = bytes(body)
    assert "published" in refused(rf.download_assets, cfg, cand)
    assert os.listdir(inbox) == []


def test_disk_full_before_and_during_the_download(server, inbox, published, monkeypatch):
    cfg, cand = candidate(server, inbox, published)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 100, 0))
    assert "not enough free disk" in refused(rf.download_assets, cfg, cand)
    monkeypatch.undo()
    real_fdopen = os.fdopen

    class Full:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def write(self, data):
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "fdopen", lambda fd, mode="r", *a, **k: Full(real_fdopen(fd, mode, *a, **k)))
    assert "disk is full" in refused(rf.download_assets, cfg, cand)
    monkeypatch.undo()
    assert os.listdir(inbox) == []


def test_interruption_removes_partial_and_promoted_files(server, inbox, published, monkeypatch):
    cfg, cand = candidate(server, inbox, published)
    calls = {"n": 0}
    real_link = os.link

    def link_then_die(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return real_link(*a, **k)

    monkeypatch.setattr(os, "link", link_then_die)
    with pytest.raises(KeyboardInterrupt):
        rf.download_assets(cfg, cand)
    monkeypatch.undo()
    assert os.listdir(inbox) == []


def test_manifest_is_promoted_last(server, inbox, published, monkeypatch):
    cfg, cand = candidate(server, inbox, published)
    order = []
    real_link = os.link
    monkeypatch.setattr(os, "link", lambda src, dst, **k: (order.append(dst), real_link(src, dst, **k))[1])
    rf.download_assets(cfg, cand)
    assert order[-1].endswith(".manifest.json")


def test_existing_inbox_files_are_never_overwritten(server, inbox, published):
    cfg, cand = candidate(server, inbox, published)
    target = inbox / cand.asset("archive").name
    target.write_bytes(b"mine")
    assert "already in the inbox" in refused(rf.download_assets, cfg, cand)
    assert target.read_bytes() == b"mine"


def test_inbox_must_be_a_private_real_directory(server, inbox, published, tmp_path):
    cfg, cand = candidate(server, inbox, published)
    inbox.chmod(0o755)
    assert "private" in refused(rf.download_assets, cfg, cand)
    inbox.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(inbox)
    assert "plain directory" in refused(rf.download_assets, config(server, link), cand)
    assert "does not exist" in refused(rf.download_assets, config(server, tmp_path / "none"), cand)


def test_candidate_for_another_product_or_asset_set_is_refused(server, inbox, published):
    import dataclasses
    cfg, cand = candidate(server, inbox, published)
    assert "belong to this product" in refused(rf.download_assets, cfg, dataclasses.replace(cand, product="mcd"))
    assert "belong to this product" in refused(rf.download_assets, cfg, dataclasses.replace(cand, repository="a/b"))
    extra = dataclasses.replace(cand.assets[0], name="evil.sh", kind="script")
    assert "allowlisted" in refused(rf.download_assets, cfg, dataclasses.replace(cand, assets=cand.assets + (extra,)))


# --- verification ----------------------------------------------------------------------


def fetch(server, inbox, published, **kwargs):
    release, _ = published
    cfg, cand = candidate(server, inbox, published, **kwargs)
    return cfg, cand, release


def test_fetch_and_verify_accepts_a_valid_pinned_release(server, inbox, published):
    cfg, cand, release = fetch(server, inbox, published)
    package, verified = rf.fetch_and_verify(cfg, cand, manifest_sha256=sha(release.manifest_bytes))
    assert (verified.product, verified.platform, verified.version, verified.change) == (PRODUCT, PLATFORM, "1.2.0", "upgrade")
    assert package.manifest.exists()


def test_failed_verification_removes_the_package_from_the_inbox(server, inbox, published):
    cfg, cand, _ = fetch(server, inbox, published)
    assert "authenticity" in refused(rf.fetch_and_verify, cfg, cand, manifest_sha256="0" * 64)
    assert os.listdir(inbox) == []


@pytest.mark.parametrize("trust,expect", [
    (None, "no trust root"),
    ({"kind": "other"}, "unknown trust root"),
    ({"kind": "ssh-signature", "allowed_signers": "/x/allowed_signers.PLACEHOLDER", "identity": "r"}, "placeholder"),
    ({"kind": "ssh-signature", "allowed_signers": "relative", "identity": "r"}, "placeholder"),
    ({"kind": "pinned-digest"}, "pinned manifest digest"),
])
def test_missing_or_placeholder_trust_root_fails_closed(server, inbox, published, trust, expect):
    cfg, cand, _ = fetch(server, inbox, published, trust=trust)
    assert expect in refused(rf.fetch_and_verify, cfg, cand)
    assert os.listdir(inbox) == []


def test_tampered_archive_is_refused_even_when_github_publishes_no_digest(server, inbox, tmp_path):
    release = make_release(tmp_path)
    obj = listing(server, release)
    for asset in obj["assets"]:
        asset.pop("digest")
    body = bytearray(release.artifact_path.read_bytes())
    body[len(body) // 2] ^= 0x01
    server.routes[f"/dl/{TAG}/{rf.asset_names(PRODUCT, '1.2.0', PLATFORM)['archive']}"] = bytes(body)
    publish(server, [obj])
    cfg = config(server, inbox)
    cand = rf.query_release(cfg)
    assert "package refused" in refused(rf.fetch_and_verify, cfg, cand, manifest_sha256=sha(release.manifest_bytes))
    assert os.listdir(inbox) == []


def test_tampered_manifest_fails_the_pin(server, inbox, tmp_path):
    release = make_release(tmp_path)
    obj = listing(server, release)
    for asset in obj["assets"]:
        asset.pop("digest")
    name = rf.asset_names(PRODUCT, "1.2.0", PLATFORM)["manifest"]
    server.routes[f"/dl/{TAG}/{name}"] = release.manifest_bytes.replace(b"1.2.0", b"1.9.0", 1)
    obj["assets"][0]["size"] = len(server.routes[f"/dl/{TAG}/{name}"])
    for asset in obj["assets"]:
        if asset["name"] == name:
            asset["size"] = len(server.routes[f"/dl/{TAG}/{name}"])
    publish(server, [obj])
    cfg = config(server, inbox)
    assert "authenticity" in refused(rf.fetch_and_verify, cfg, rf.query_release(cfg), manifest_sha256=sha(release.manifest_bytes))


@pytest.mark.parametrize("kwargs,expect", [
    (dict(product=OTHER_PRODUCT, platform=OTHER_PLATFORM), "is for product mcd"),
    # On the real Linux ARM64 host the foreign darwin package is rejected at the
    # supported product/platform boundary before the more specific mismatch text.
    (dict(platform=OTHER_PLATFORM), "unsupported product/platform"),
    (dict(repository=rv.OFFICIAL_REPOSITORIES[OTHER_PRODUCT]), "names repository"),
])
def test_wrong_product_arch_or_repo_package_under_our_names_is_refused(server, inbox, tmp_path, kwargs, expect):
    """A hostile release that publishes someone else's genuinely-built package under our asset names."""
    foreign = make_release(tmp_path, **kwargs)
    ours = make_release(tmp_path, name="ours")
    obj = listing(server, ours)
    names = rf.asset_names(PRODUCT, "1.2.0", PLATFORM)
    server.routes[f"/dl/{TAG}/{names['manifest']}"] = foreign.manifest_bytes
    server.routes[f"/dl/{TAG}/{names['archive']}"] = foreign.artifact_path.read_bytes()
    for asset in obj["assets"]:
        asset.pop("digest")
        body = server.routes[f"/dl/{TAG}/{asset['name']}"]
        asset["size"] = len(body)
    publish(server, [obj])
    cfg = config(server, inbox)
    msg = refused(rf.fetch_and_verify, cfg, rf.query_release(cfg), manifest_sha256=sha(foreign.manifest_bytes))
    assert expect in msg
    assert os.listdir(inbox) == []


def test_version_that_disagrees_with_the_release_tag_is_refused(server, inbox, tmp_path):
    """Tag says 1.2.0 but the signed package is the older 1.0.0: a replayed old release."""
    old = make_release(tmp_path, version="1.0.0", name="old")
    ours = make_release(tmp_path, name="ours")
    obj = listing(server, ours)
    names = rf.asset_names(PRODUCT, "1.2.0", PLATFORM)
    server.routes[f"/dl/{TAG}/{names['manifest']}"] = old.manifest_bytes
    server.routes[f"/dl/{TAG}/{names['archive']}"] = old.artifact_path.read_bytes()
    for asset in obj["assets"]:
        asset.pop("digest")
        asset["size"] = len(server.routes[f"/dl/{TAG}/{asset['name']}"])
    publish(server, [obj])
    cfg = config(server, inbox)
    msg = refused(rf.fetch_and_verify, cfg, rf.query_release(cfg), manifest_sha256=sha(old.manifest_bytes))
    assert "not the selected 1.2.0" in msg


def test_installed_version_moving_ahead_before_verification_blocks_the_downgrade(server, inbox, published):
    cfg, cand, release = fetch(server, inbox, published)
    package = rf.download_assets(cfg, cand)
    import dataclasses
    newer = dataclasses.replace(cfg, installed_version="1.5.0")
    msg = refused(rf.verify_staged, newer, cand, package, sha(release.manifest_bytes))
    assert "downgrades need explicit opt-in" in msg
    same = dataclasses.replace(cfg, installed_version="1.2.0")
    assert "already installed" in refused(rf.verify_staged, same, cand, package, sha(release.manifest_bytes))


def test_stable_channel_refuses_a_prerelease_package(server, inbox, tmp_path):
    pre = make_release(tmp_path, version="1.3.0-rc.1")
    obj = listing(server, pre, "v1.3.0-rc.1", "1.3.0-rc.1", True)
    publish(server, [obj])
    cfg = config(server, inbox, channel="prerelease")
    cand = rf.query_release(cfg)
    package = rf.download_assets(cfg, cand)
    import dataclasses
    stable = dataclasses.replace(cfg, channel="stable")
    assert "prerelease" in refused(rf.verify_staged, stable, cand, package, sha(pre.manifest_bytes))
    assert rf.verify_staged(cfg, cand, package, sha(pre.manifest_bytes)).channel == "prerelease"


@pytest.mark.skipif(SSH_KEYGEN is None, reason="ssh-keygen is not available")
def test_real_ssh_signature_trust_root(server, inbox, tmp_path):
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    for name in ("good", "evil"):
        subprocess.run([SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-f", str(keys / name)], check=True)
    pub = (keys / "good.pub").read_text().split()
    signers = keys / "allowed_signers"
    signers.write_text(f'release@example namespaces="dashboard-release" {pub[0]} {pub[1]}\n')
    signers.chmod(0o600)

    def sign(key: str, data: bytes, where: Path) -> bytes:
        where.write_bytes(data)
        subprocess.run([SSH_KEYGEN, "-Y", "sign", "-q", "-f", str(keys / key), "-n", "dashboard-release", str(where)], check=True)
        return Path(f"{where}.sig").read_bytes()

    release = make_release(tmp_path)
    names = rf.asset_names(PRODUCT, "1.2.0", PLATFORM)
    trust = {"kind": "ssh-signature", "allowed_signers": str(signers), "identity": "release@example"}

    obj = listing(server, release)
    server.routes[f"/dl/{TAG}/{names['signature']}"] = sign("good", release.manifest_bytes, tmp_path / "m1")
    for asset in obj["assets"]:
        asset["size"] = len(server.routes[f"/dl/{TAG}/{asset['name']}"])
        asset.pop("digest")
    publish(server, [obj])
    cfg = config(server, inbox, trust=trust)
    _, verified = rf.fetch_and_verify(cfg, rf.query_release(cfg))
    assert verified.authenticity == "ssh-signature (release@example)"
    for path in os.listdir(inbox):
        os.unlink(inbox / path)

    server.routes[f"/dl/{TAG}/{names['signature']}"] = sign("evil", release.manifest_bytes, tmp_path / "m2")
    for asset in obj["assets"]:
        asset["size"] = len(server.routes[f"/dl/{TAG}/{asset['name']}"])
    publish(server, [obj])
    assert "SSH signature is not valid" in refused(rf.fetch_and_verify, cfg, rf.query_release(cfg))
    assert os.listdir(inbox) == []

    server.routes[f"/dl/{TAG}/{names['signature']}"] = sign("good", b"another manifest", tmp_path / "m3")
    for asset in obj["assets"]:
        asset["size"] = len(server.routes[f"/dl/{TAG}/{asset['name']}"])
    publish(server, [obj])
    assert "SSH signature is not valid" in refused(rf.fetch_and_verify, cfg, rf.query_release(cfg))
