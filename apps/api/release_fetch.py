"""Find, download and verify a published release from the public GitHub Releases API.

Standard library only, unauthenticated: no gh, no token, no Authorization header is ever sent.
Nothing here stops a service, touches the installed version or runs code from the package; the
result is a verified package in the private update inbox that update_engine.stage() verifies
again before anything is switched.

Flow (each step is a separate call so the UI can show the release and ask before downloading):
  1. query_release()   - list releases, filter by channel, pick the newest newer-than-installed one,
                         select exactly the three allowlisted assets by name and URL;
  2. download_assets() - stream them into the inbox under size, time, throughput and redirect limits;
  3. verify_staged()   - release_verify: product, OS, arch, version (downgrade refused), sha256,
                         signature against the configured trust root.
"""

from __future__ import annotations

import errno
import functools
import hashlib
import hmac
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import release_verify as rv
import update_engine as ue

PRODUCT = "rcd"  # the only product this checkout may update; a cross-product release is refused

API_BASE = "https://api.github.com"
ALLOWED_HOSTS = frozenset({"api.github.com", "github.com", "objects.githubusercontent.com",
                           "release-assets.githubusercontent.com"})
MAX_API_BYTES = 2 * 1024 * 1024
MAX_NOTES_CHARS = 20_000
MAX_REDIRECTS = 3
CHUNK = 64 * 1024
CHANNELS = ("stable", "prerelease")
TAG = re.compile(r"^v?(\S{1,64})$")
GITHUB_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


class FetchError(Exception):
    """A query, download or check was refused. `problems` lists the reasons."""

    def __init__(self, problems: list[str] | str):
        self.problems = [problems] if isinstance(problems, str) else list(problems) or ["refused"]
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class Limits:
    manifest_bytes: int = rv.MAX_MANIFEST_BYTES
    signature_bytes: int = rv.MAX_SIGNATURE_BYTES
    artifact_bytes: int = rv.MAX_ARTIFACT_BYTES
    io_timeout: float = 15.0  # connect and each read; a stalled server is cut off
    total_seconds: float = 600.0  # whole download of one asset
    min_bytes_per_second: int = 16 * 1024  # checked after min_rate_grace seconds
    min_rate_grace: float = 20.0
    max_redirects: int = MAX_REDIRECTS
    disk_margin_bytes: int = 64 * 1024 * 1024


@dataclass(frozen=True)
class FetchConfig:
    product: str
    platform: str
    inbox: Path
    channel: str = "stable"
    installed_version: str | None = None
    repository: str | None = None  # None means the official repository of the product
    trust: dict | None = None  # {"kind": "ssh-signature", "allowed_signers": path, "identity": id}
    limits: Limits = field(default_factory=Limits)
    # Transport overrides exist for tests; production code leaves the defaults.
    api_base: str = API_BASE
    allowed_hosts: frozenset = ALLOWED_HOSTS
    require_https: bool = True
    per_page: int = 30


@dataclass(frozen=True)
class Asset:
    kind: str  # manifest, signature or archive
    name: str
    url: str
    size: int
    digest: str | None  # sha256 hex published by GitHub for the asset, if any
    limit: int


@dataclass(frozen=True)
class Candidate:
    """What the operator is shown before confirming. Everything here is untrusted until verified."""

    product: str
    platform: str
    repository: str
    channel: str
    tag: str
    version: str
    name: str  # base name used in the inbox
    change: str  # upgrade or install
    notes: str  # plain text only; never render as HTML
    html_url: str | None
    published_at: str | None
    prerelease: bool
    assets: tuple[Asset, ...]

    def asset(self, kind: str) -> Asset:
        return next(a for a in self.assets if a.kind == kind)

    @property
    def manifest_digest(self) -> str | None:
        return self.asset("manifest").digest

    @property
    def archive_digest(self) -> str | None:
        return self.asset("archive").digest


@dataclass(frozen=True)
class StagedPackage:
    name: str
    manifest: Path
    archive: Path
    signature: Path


# --- configuration ---------------------------------------------------------------------


def make_config(inbox: Path | str, platform: str, **kwargs) -> FetchConfig:
    """Config for this checkout's product. Raises FetchError for anything unsupported."""
    cfg = FetchConfig(product=PRODUCT, platform=platform, inbox=Path(inbox), **kwargs)
    problems = config_problems(cfg)
    if problems:
        raise FetchError(problems)
    return cfg


def official_repository(cfg: FetchConfig) -> str:
    return cfg.repository or rv.OFFICIAL_REPOSITORIES[cfg.product]


def config_problems(cfg: FetchConfig) -> list[str]:
    problems = []
    if cfg.product != PRODUCT:
        problems.append(f"this build updates {PRODUCT} only, not {cfg.product}")
    if (cfg.product, cfg.platform) not in rv.SUPPORTED:
        problems.append(f"{cfg.product}/{cfg.platform} is not a supported product and platform")
    if cfg.channel not in CHANNELS:
        problems.append(f"channel must be one of {', '.join(CHANNELS)}")
    repo = cfg.repository or rv.OFFICIAL_REPOSITORIES.get(cfg.product)
    if not isinstance(repo, str) or not rv.REPOSITORY.match(repo):
        problems.append("bad repository")
    elif repo != rv.OFFICIAL_REPOSITORIES.get(cfg.product):
        problems.append(f"{repo} is not the official {cfg.product} repository")
    if cfg.installed_version is not None:
        try:
            rv.parse_version(cfg.installed_version)
        except ValueError:
            problems.append("installed version is not a semantic version")
    if cfg.require_https and not cfg.api_base.startswith("https://"):
        problems.append("api_base must be https")
    return problems


def build_authenticator(trust: dict | None, manifest_sha256: str | None = None) -> rv.Authenticator:
    """The configured trust root. No trust root, or a placeholder one, fails closed."""
    if not isinstance(trust, dict):
        raise FetchError("no trust root is configured; releases cannot be verified")
    kind = trust.get("kind")
    if kind == "ssh-signature":
        path = str(trust.get("allowed_signers") or "")
        if not path or path.endswith(".PLACEHOLDER") or not os.path.isabs(path):
            raise FetchError("the trust root is a placeholder or not an absolute path")
        try:
            return rv.SshSignature(Path(path), str(trust.get("identity") or ""))
        except ValueError as exc:
            raise FetchError(str(exc)) from None
    if kind == "pinned-digest":
        try:
            return rv.PinnedDigest(manifest_sha256 or "", "operator-entered release digest")
        except ValueError as exc:
            raise FetchError(str(exc)) from None
    raise FetchError("unknown trust root kind")


# --- transport -------------------------------------------------------------------------


def check_url(cfg: FetchConfig, url: str) -> str:
    """Scheme, host, port and credentials of every URL fetched or redirected to."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        raise FetchError("malformed URL") from None
    if cfg.require_https and parts.scheme != "https":
        raise FetchError(f"refusing non-https URL ({parts.scheme or 'none'})")
    if parts.scheme not in ("https", "http"):
        raise FetchError("refusing non-http URL")
    if parts.username or parts.password:
        raise FetchError("refusing URL with credentials")
    if (parts.hostname or "").lower() not in cfg.allowed_hosts:
        raise FetchError(f"refusing host {(parts.hostname or '')[:60]!r}; not an allowed GitHub host")
    if cfg.require_https and port not in (None, 443):
        raise FetchError("refusing non-standard port")
    return url


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, cfg: FetchConfig):
        self.cfg, self.count = cfg, 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > self.cfg.limits.max_redirects:
            raise FetchError("too many redirects")
        target = urllib.parse.urljoin(req.full_url, newurl)
        check_url(self.cfg, target)
        if req.full_url.startswith("https://") and target.startswith("http://"):
            raise FetchError("refusing redirect from https to http")
        new = urllib.request.Request(target, method="GET", headers={
            k: v for k, v in req.header_items() if k.lower() in ("accept", "user-agent", "accept-encoding")})
        return new


Opener = Callable[[urllib.request.Request, float], "urllib.response.addinfourl"]


def _default_open(cfg: FetchConfig) -> Opener:
    def open_(req: urllib.request.Request, timeout: float):
        return urllib.request.build_opener(_Redirects(cfg)).open(req, timeout=timeout)
    return open_


def _request(cfg: FetchConfig, url: str, accept: str, opener: Opener | None):
    check_url(cfg, url)
    req = urllib.request.Request(url, method="GET", headers={
        "Accept": accept, "Accept-Encoding": "identity", "User-Agent": f"{cfg.product}-updater",
        "X-GitHub-Api-Version": "2022-11-28"})
    try:
        resp = (opener or _default_open(cfg))(req, cfg.limits.io_timeout)
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
            reset = exc.headers.get("X-RateLimit-Reset", "?")
            raise FetchError(f"GitHub rate limit reached; resets at epoch {reset[:20]}") from None
        raise FetchError(f"GitHub answered HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"network error ({type(reason).__name__})") from None
    if resp.status != 200:
        resp.close()
        raise FetchError(f"unexpected HTTP status {resp.status}")
    final = resp.geturl()
    try:
        check_url(cfg, final)
    except FetchError:
        resp.close()
        raise
    if (resp.headers.get("Content-Encoding") or "identity").lower() != "identity":
        resp.close()
        raise FetchError("refusing a content-encoded response")
    return resp


def _read_capped(resp, limit: int, deadline: float, timeout_msg: str = "request timed out") -> bytes:
    declared = resp.headers.get("Content-Length")
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise FetchError("response is larger than the limit")
    out = bytearray()
    try:
        while True:
            if time.monotonic() > deadline:
                raise FetchError(timeout_msg)
            chunk = resp.read(min(CHUNK, limit + 1 - len(out)))
            if not chunk:
                break
            out += chunk
            if len(out) > limit:
                raise FetchError("response is larger than the limit")
    except FetchError:
        raise
    except (OSError, ValueError) as exc:
        raise FetchError(f"read failed ({type(exc).__name__})") from None
    finally:
        resp.close()
    if declared is not None and len(out) != int(declared):
        raise FetchError("response ended before its declared length")
    return bytes(out)


# --- query -----------------------------------------------------------------------------


def asset_names(product: str, version: str, platform: str) -> dict[str, str]:
    """Exact allowlisted asset names; they are also the inbox file names update_engine expects."""
    base = f"{product}-{version}-{platform}"
    return {"manifest": f"{base}.manifest.json", "signature": f"{base}.manifest.json.sig",
            "archive": f"{base}.tar.gz"}


def _release_version(release: object) -> tuple[str, str] | None:
    if not isinstance(release, dict) or release.get("draft") is not False:
        return None
    tag = release.get("tag_name")
    match = TAG.match(tag) if isinstance(tag, str) else None
    if not match:
        return None
    try:
        rv.parse_version(match.group(1))
    except ValueError:
        return None
    return tag, match.group(1)


def select_candidate(cfg: FetchConfig, releases: object) -> Candidate | None:
    """Newest release on the channel that is newer than the installed version, or None."""
    problems = config_problems(cfg)
    if problems:
        raise FetchError(problems)
    if not isinstance(releases, list):
        raise FetchError("GitHub returned an unexpected release list")
    repo = official_repository(cfg)
    eligible = []
    for release in releases:
        found = _release_version(release)
        if not found:
            continue
        tag, version = found
        prerelease = release.get("prerelease")
        if not isinstance(prerelease, bool) or prerelease != ("-" in version):
            continue  # the GitHub flag and the version must agree
        if prerelease and cfg.channel != "prerelease":
            continue
        eligible.append((tag, version, release))
    # Highest semantic version first; ties keep the API order.
    eligible.sort(key=functools.cmp_to_key(lambda a, b: rv.compare_versions(b[1], a[1])))
    for tag, version, release in eligible:
        if cfg.installed_version is not None and rv.compare_versions(version, cfg.installed_version) <= 0:
            return None  # the best one is not newer: nothing to do, and never a downgrade
        assets = _select_assets(cfg, repo, tag, version, release)
        notes = release.get("body") if isinstance(release.get("body"), str) else ""
        html = release.get("html_url")
        return Candidate(
            product=cfg.product, platform=cfg.platform, repository=repo, channel=cfg.channel, tag=tag,
            version=version, name=f"{cfg.product}-{version}-{cfg.platform}",
            change="upgrade" if cfg.installed_version else "install", notes=notes[:MAX_NOTES_CHARS],
            html_url=html if isinstance(html, str) and html.startswith(f"https://github.com/{repo}/") else None,
            published_at=release.get("published_at") if isinstance(release.get("published_at"), str) else None,
            prerelease=bool(release["prerelease"]), assets=assets)
    return None


def _select_assets(cfg: FetchConfig, repo: str, tag: str, version: str, release: dict) -> tuple[Asset, ...]:
    listed = release.get("assets")
    if not isinstance(listed, list):
        raise FetchError(f"release {tag} has no asset list")
    names = asset_names(cfg.product, version, cfg.platform)
    limits = {"manifest": cfg.limits.manifest_bytes, "signature": cfg.limits.signature_bytes,
              "archive": cfg.limits.artifact_bytes}
    by_name: dict[str, list[dict]] = {}
    for item in listed:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            by_name.setdefault(item["name"], []).append(item)
    selected, problems = [], []
    for kind, name in names.items():
        matches = by_name.get(name, [])
        if len(matches) != 1:
            problems.append(f"release {tag} needs exactly one asset {name} (found {len(matches)})")
            continue
        item = matches[0]
        size, digest = item.get("size"), item.get("digest")
        expected_url = f"https://github.com/{repo}/releases/download/{urllib.parse.quote(tag, safe='')}/{name}"
        url = item.get("browser_download_url")
        try:
            if not isinstance(url, str):
                raise FetchError("asset URL is missing")
            check_url(cfg, url)
        except FetchError:
            problems.append(f"asset {name} does not point at this repository's release download")
            continue
        if url != expected_url and cfg.require_https:
            problems.append(f"asset {name} does not point at this repository's release download")
            continue
        if item.get("state") != "uploaded":
            problems.append(f"asset {name} is not fully uploaded")
            continue
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= limits[kind]:
            problems.append(f"asset {name} has a size outside the allowed range")
            continue
        sha = None
        if digest is not None:
            match = GITHUB_DIGEST.match(digest) if isinstance(digest, str) else None
            if not match:
                problems.append(f"asset {name} has an unreadable digest")
                continue
            sha = match.group(1)
        selected.append(Asset(kind, name, url, size, sha, limits[kind]))
    if problems:
        raise FetchError(problems)
    return tuple(selected)


def query_release(cfg: FetchConfig, opener: Opener | None = None) -> Candidate | None:
    """List public releases of the product repository and pick the update candidate, if any."""
    problems = config_problems(cfg)
    if problems:
        raise FetchError(problems)
    url = f"{cfg.api_base}/repos/{official_repository(cfg)}/releases?per_page={cfg.per_page}"
    resp = _request(cfg, url, "application/vnd.github+json", opener)
    body = _read_capped(resp, MAX_API_BYTES, time.monotonic() + cfg.limits.total_seconds)
    try:
        releases = rv.strict_json(body, "release list")
    except rv.VerificationError as exc:
        raise FetchError(exc.problems) from None
    return select_candidate(cfg, releases)


# --- download --------------------------------------------------------------------------


def _check_inbox(inbox: Path) -> None:
    try:
        st = os.lstat(inbox)
    except OSError:
        raise FetchError("the update inbox does not exist") from None
    if not os.path.isdir(inbox) or os.path.islink(inbox):
        raise FetchError("the update inbox is not a plain directory")
    if st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise FetchError("the update inbox must be private (owner only)")


def _download_one(cfg: FetchConfig, asset: Asset, dest_dir_fd: int, partial: str, opener: Opener | None) -> str:
    """Stream one asset into `partial`; returns its sha256. Raises FetchError."""
    limits = cfg.limits
    started = time.monotonic()
    resp = _request(cfg, asset.url, "application/octet-stream", opener)
    try:
        declared = resp.headers.get("Content-Length")
        if declared is not None and (not declared.isdigit() or int(declared) != asset.size):
            raise FetchError(f"{asset.name}: server length differs from the release listing")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(partial, flags, 0o600, dir_fd=dest_dir_fd)
        digest, total = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as out:
            while True:
                now = time.monotonic()
                if now - started > limits.total_seconds:
                    raise FetchError(f"{asset.name}: download took too long")
                if total > 0 and now - started > limits.min_rate_grace and total / (now - started) < limits.min_bytes_per_second:
                    raise FetchError(f"{asset.name}: download is too slow")
                chunk = resp.read(min(CHUNK, asset.limit + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > asset.limit or total > asset.size:
                    raise FetchError(f"{asset.name}: download is larger than expected")
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    except FetchError:
        raise
    except OSError as exc:
        if exc.errno in (errno.ENOSPC, errno.EDQUOT):
            raise FetchError(f"{asset.name}: the disk is full") from None
        raise FetchError(f"{asset.name}: transfer failed ({type(exc).__name__})") from None
    except ValueError as exc:  # http.client.IncompleteRead is an HTTPException, handled below
        raise FetchError(f"{asset.name}: transfer failed ({type(exc).__name__})") from None
    except Exception as exc:  # noqa: BLE001 - http.client errors such as IncompleteRead
        raise FetchError(f"{asset.name}: transfer failed ({type(exc).__name__})") from None
    finally:
        resp.close()
    if total != asset.size:
        raise FetchError(f"{asset.name}: download ended early ({total} of {asset.size} bytes)")
    sha = digest.hexdigest()
    if asset.digest and not hmac.compare_digest(sha, asset.digest):
        raise FetchError(f"{asset.name}: sha256 differs from the digest GitHub published")
    return sha


def download_assets(cfg: FetchConfig, candidate: Candidate, opener: Opener | None = None) -> StagedPackage:
    """Download exactly the candidate's three allowlisted assets into the private inbox.

    Files appear under their final names only after all three completed; on any failure every
    partial and every file created by this call is removed.
    """
    if (candidate.product, candidate.platform) != (cfg.product, cfg.platform) \
            or candidate.repository != official_repository(cfg):
        raise FetchError("candidate does not belong to this product, platform and repository")
    names = asset_names(cfg.product, candidate.version, cfg.platform)
    if {a.kind: a.name for a in candidate.assets} != names:
        raise FetchError("candidate assets are not the allowlisted set")
    inbox = Path(cfg.inbox)
    _check_inbox(inbox)
    for asset in candidate.assets:
        if os.path.lexists(inbox / asset.name):
            raise FetchError(f"{asset.name} is already in the inbox; remove it or stage it")
    need = sum(a.size for a in candidate.assets) + cfg.limits.disk_margin_bytes
    if shutil.disk_usage(inbox).free < need:
        raise FetchError("not enough free disk space in the update inbox")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    dir_fd = os.open(inbox, flags)
    partials: dict[str, str] = {}
    finals: list[str] = []
    try:
        for asset in candidate.assets:
            partial = f".{asset.name}.partial"
            partials[asset.name] = partial
            _unlink(dir_fd, partial)  # left by an earlier interrupted download; the inbox is private
            _download_one(cfg, asset, dir_fd, partial, opener)
        # Promote; the manifest goes last so a half set is never complete.
        for asset in sorted(candidate.assets, key=lambda a: a.kind == "manifest"):
            os.link(partials[asset.name], asset.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd,
                    follow_symlinks=False)  # fails if the final name appeared meanwhile; never overwrites
            finals.append(asset.name)
        os.fsync(dir_fd)
    except BaseException:
        for name in finals:
            _unlink(dir_fd, name)
        raise
    finally:
        for partial in partials.values():
            _unlink(dir_fd, partial)
        os.close(dir_fd)
    return StagedPackage(candidate.name, inbox / names["manifest"], inbox / names["archive"],
                         inbox / names["signature"])


def _unlink(dir_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=dir_fd)
    except OSError:
        pass


def discard(package: StagedPackage) -> None:
    """Remove a downloaded package from the inbox (for example after verification failed)."""
    for path in (package.manifest, package.signature, package.archive):
        try:
            os.unlink(path)
        except OSError:
            pass


# --- verify ----------------------------------------------------------------------------


def verify_staged(cfg: FetchConfig, candidate: Candidate, package: StagedPackage,
                  manifest_sha256: str | None = None) -> rv.VerifiedRelease:
    """Product, OS, arch, version (no downgrade), digests and signature against the trust root.

    Raises FetchError; the caller must not stop services or switch versions before this returns.
    """
    authenticator = build_authenticator(cfg.trust, manifest_sha256)
    policy = rv.TrustPolicy(
        product=cfg.product, platform=cfg.platform, authenticator=authenticator,
        installed_version=cfg.installed_version, repository=official_repository(cfg),
        allow_prerelease=cfg.channel == "prerelease", expected_version=candidate.version)
    try:
        release = rv.verify_release(package.manifest, package.archive, policy, package.signature)
    except rv.VerificationError as exc:
        raise FetchError(["package refused"] + exc.problems) from None
    if release.change not in ("install", "upgrade"):
        raise FetchError(f"package is a {release.change}, not an update")
    for asset in candidate.assets:
        expected = release.manifest_sha256 if asset.kind == "manifest" else \
            release.artifact_sha256 if asset.kind == "archive" else None
        if expected and asset.digest and not hmac.compare_digest(expected, asset.digest):
            raise FetchError(f"{asset.name}: verified digest differs from the digest GitHub published")
    return release


def fetch_and_verify(cfg: FetchConfig, candidate: Candidate, opener: Opener | None = None,
                     manifest_sha256: str | None = None) -> tuple[StagedPackage, rv.VerifiedRelease]:
    """Download then verify; a package that fails verification is removed from the inbox."""
    package = download_assets(cfg, candidate, opener)
    try:
        return package, verify_staged(cfg, candidate, package, manifest_sha256)
    except BaseException:
        discard(package)
        raise


# --- hand-off to the install engine -----------------------------------------------------


def installed_version(hcfg: ue.HelperConfig) -> str | None:
    """Version `current` points at, from its sealed receipt; None before the first install."""
    current = ue._link_target(hcfg, "current")  # noqa: SLF001 - same package, same pinned copy
    return (ue.read_receipt(hcfg, current) or {}).get("version") if current else None


def fetch_config(hcfg: ue.HelperConfig, channel: str, **overrides) -> FetchConfig:
    """Fetch settings come from the helper configuration, never from the request."""
    if channel == "prerelease" and not hcfg.allow_prerelease:
        raise FetchError("the prerelease channel is off; set allow_prerelease in helper.json to use it")
    cfg = FetchConfig(product=hcfg.product, platform=hcfg.platform, inbox=hcfg.inbox, channel=channel,
                      installed_version=installed_version(hcfg), trust=hcfg.trust, **overrides)
    problems = config_problems(cfg)
    if problems:
        raise FetchError(problems)
    return cfg


def check(hcfg: ue.HelperConfig, channel: str, opener: Opener | None = None, **overrides) -> Candidate | None:
    """Read-only: the release that would be offered. Downloads nothing and changes nothing."""
    return query_release(fetch_config(hcfg, channel, **overrides), opener)


def describe(candidate: Candidate) -> dict:
    """What the operator sees before confirming. Authenticity is only known after download and
    verification, so it is shown as unverified here; digests are the ones GitHub publishes."""
    return {"product": candidate.product, "platform": candidate.platform, "repository": candidate.repository,
            "channel": candidate.channel, "tag": candidate.tag, "version": candidate.version,
            "change": candidate.change, "prerelease": candidate.prerelease, "notes": candidate.notes,
            "notes_format": "text", "html_url": candidate.html_url, "published_at": candidate.published_at,
            "manifest_sha256": candidate.manifest_digest, "archive_sha256": candidate.archive_digest,
            "assets": [{"kind": a.kind, "name": a.name, "size": a.size} for a in candidate.assets],
            "authenticity": "unverified until downloaded and checked against the configured trust root"}


def fetch_and_stage(hcfg: ue.HelperConfig, channel: str, version: str, manifest_sha256: str | None = None,
                    opener: Opener | None = None, builder=ue.build_runtime, **overrides) -> dict:
    """Operator-confirmed path: download the release the operator was shown, verify it, stage it.

    `version` is what the operator confirmed; if the newest release has changed since, nothing is
    downloaded. Nothing is drained, stopped or switched here: update_engine.apply() does that on a
    separate operator request, with its snapshot, health check and automatic rollback. The inbox
    copy is removed whatever the outcome; what matters afterwards is the sealed version directory.
    """
    cfg = fetch_config(hcfg, channel, **overrides)
    op = ue.OperationLog.begin(hcfg, version)
    op.step("fetch", "running", f"reading the release list and downloading {version} from GitHub")
    try:
        candidate = query_release(cfg, opener)
        if candidate is None:
            raise FetchError("no newer release is available on this channel")
        if candidate.version != version:
            raise FetchError(f"the newest release is now {candidate.version}, not {version}; check again and confirm")
    except FetchError as exc:
        op.step("fetch", "failed", "; ".join(exc.problems)[:280])
        op.finish("failed", "Nothing was installed. " + "; ".join(exc.problems)[:250])
        raise
    names = asset_names(cfg.product, version, cfg.platform)
    package = StagedPackage(candidate.name, cfg.inbox / names["manifest"], cfg.inbox / names["archive"],
                            cfg.inbox / names["signature"])
    present = [p for p in (package.manifest, package.archive, package.signature) if os.path.lexists(p)]
    try:
        if present:
            # An earlier fetch was interrupted. These are this release's own names in a private inbox:
            # reuse them only if the whole set verifies, otherwise start again.
            try:
                if len(present) != 3:
                    raise FetchError("incomplete")
                verify_staged(cfg, candidate, package, manifest_sha256)
            except FetchError:
                discard(package)
                present = []
        try:
            if not present:
                package = download_assets(cfg, candidate, opener)
                verify_staged(cfg, candidate, package, manifest_sha256)
            op.step("fetch", "ok", "downloaded the manifest, signature and package; checksums match what GitHub published")
        except FetchError as exc:
            op.step("fetch", "failed", "; ".join(exc.problems)[:280])
            op.finish("failed", "Nothing was installed. " + "; ".join(exc.problems)[:250])
            raise
        try:
            staged = ue.stage(hcfg, candidate.name, manifest_sha256, builder)
        except ue.UpdateError as exc:
            raise FetchError(exc.problems) from None
    finally:
        discard(package)
    return {**staged, "tag": candidate.tag, "repository": candidate.repository, "channel": channel,
            "manifest_sha256": candidate.manifest_digest, "archive_sha256": candidate.archive_digest}
