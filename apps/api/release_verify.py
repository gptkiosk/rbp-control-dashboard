"""Verify a downloaded release package before anything from it is installed or run.

Standard library only and independent of the rest of the app, so the update engine and
the out-of-app recovery CLI can both use it. Every check fails closed: a check that cannot
complete refuses the package, and nothing from the package is executed here.

Order of checks:
  1. the trust policy itself (product, platform, repository, host);
  2. manifest bytes read once (no-follow, capped) and authenticated as those exact bytes;
  3. manifest structure (schema dashboard-release-manifest/v1, see packaging/);
  4. policy match: trusted repository, product, platform/os/arch, channel, version and
     downgrade;
  5. artifact bytes read once (no-follow, capped), size and sha256;
  6. gzip expanded under a cap, then every tar member: paths inside the root, no
     traversal, absolute, symlink, hardlink, device or sparse members, fixed modes,
     no duplicate, case-folded or file/directory collisions, per-file, total and count caps;
  7. inner manifest, every file digest, size and mode, dependency lock and BUILD_INFO.

`extract()` writes only the verified in-memory bytes into a new directory, opening every
component with O_NOFOLLOW, so the archive on disk is never read twice.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import platform as host
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

MANIFEST_SCHEMA = "dashboard-release-manifest/v1"
FILES_SCHEMA = "dashboard-release-files/v1"

OFFICIAL_REPOSITORIES = {"mcd": "gptkiosk/mac-control-dashboard", "rcd": "gptkiosk/rbp-control-dashboard"}
PLATFORM_OS_ARCH = {"darwin-arm64": ("darwin", "arm64"), "linux-arm64": ("linux", "arm64")}
SUPPORTED = {("mcd", "darwin-arm64"), ("rcd", "linux-arm64")}

# Same limits as scripts/release/release.py; the verifier never accepts more than the builder makes.
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_SIGNATURE_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_FILES = 5000
MAX_MEMBERS = MAX_FILES + 1000
TAR_OVERHEAD_BYTES = MAX_MEMBERS * 2048 + (1 << 20)
FILE_MODES = {"0644": 0o644, "0755": 0o755}
DIR_MODE = 0o755

REQUIRED_FILES = (
    "BUILD_INFO.json",
    "LICENSE",
    "packaging/product.json",
    "apps/api/main.py",
    "apps/api/version.py",
    "apps/api/requirements.release.txt",
    "apps/web/dist/index.html",
)
MANIFEST_KEYS = {"schema", "product", "product_name", "repository", "version", "channel", "platform", "runtime",
                 "source", "build", "dependencies", "artifact", "contents", "files"}

_IDENT = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER = re.compile(rf"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-({_IDENT}(?:\.{_IDENT})*))?$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PATH_PART = re.compile(r"^[\x21-\x5b\x5d-\x7e]{1,255}$")  # printable ASCII, no space or backslash
SIGNER_IDENTITY = re.compile(r"^[A-Za-z0-9._@+-]{1,128}$")


class VerificationError(Exception):
    """The package was refused. `problems` lists every reason found before refusing."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems) or ["refused"]
        super().__init__("; ".join(self.problems))


class AuthenticityError(Exception):
    pass


# An authenticator receives the exact manifest bytes and the detached signature (or None)
# and returns a short description of what vouched for them, or raises AuthenticityError.
Authenticator = Callable[[bytes, "bytes | None"], str]


@dataclass(frozen=True)
class TrustPolicy:
    product: str
    platform: str
    authenticator: Authenticator | None
    installed_version: str | None = None
    repository: str | None = None  # where the release was fetched from; None means the official one
    allow_fork: bool = False
    allow_prerelease: bool = False
    allow_downgrade: bool = False
    allow_reinstall: bool = False
    allow_dev: bool = False  # dev artifacts are never update candidates; local fault testing only
    expected_version: str | None = None  # e.g. from the release tag the caller selected
    check_host: bool = True


@dataclass(frozen=True)
class VerifiedRelease:
    product: str
    platform: str
    repository: str
    version: str
    channel: str
    change: str  # install, upgrade, reinstall or downgrade
    authenticity: str
    manifest_sha256: str
    artifact_sha256: str
    manifest: dict = field(repr=False)
    files: dict = field(repr=False)  # rel path -> (bytes, mode), including manifest.json


# --- versions --------------------------------------------------------------------------


def parse_version(value: object) -> tuple[tuple[int, int, int], tuple | None]:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("version is not a string")
    match = SEMVER.match(value)
    if not match:
        raise ValueError(f"not a semantic version: {value[:64]!r}")
    core = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    pre = tuple(int(p) if p.isdigit() else p for p in match.group(4).split(".")) if match.group(4) else None
    return core, pre


def compare_versions(a: str, b: str) -> int:
    """Semantic Versioning 2.0.0 precedence: -1, 0 or 1."""
    (core_a, pre_a), (core_b, pre_b) = parse_version(a), parse_version(b)
    if core_a != core_b:
        return -1 if core_a < core_b else 1
    if pre_a == pre_b:
        return 0
    if pre_a is None or pre_b is None:
        return 1 if pre_a is None else -1  # a release ranks above its prereleases
    for x, y in zip(pre_a, pre_b):
        if x == y:
            continue
        if isinstance(x, int) != isinstance(y, int):
            return -1 if isinstance(x, int) else 1  # numeric identifiers rank lower
        return -1 if x < y else 1
    return (len(pre_a) > len(pre_b)) - (len(pre_a) < len(pre_b))


def host_platform() -> str | None:
    arch = {"arm64": "arm64", "aarch64": "arm64"}.get(host.machine().lower())
    key = f"{host.system().lower()}-{arch}" if arch else None
    return key if key in PLATFORM_OS_ARCH else None


# --- authenticity ----------------------------------------------------------------------


class PinnedDigest:
    """Authentic when the manifest sha256 equals a digest obtained through a separately
    verified channel (for example an immutable release asset digest). Only as strong as
    that channel; the caller names it in `source`."""

    def __init__(self, manifest_sha256: str, source: str):
        if not isinstance(manifest_sha256, str) or not SHA256_HEX.match(manifest_sha256):
            raise ValueError("pinned manifest digest must be 64 lowercase hex characters")
        self.digest = manifest_sha256
        self.source = source

    def __call__(self, manifest: bytes, signature: bytes | None) -> str:
        if not hmac.compare_digest(hashlib.sha256(manifest).hexdigest(), self.digest):
            raise AuthenticityError("manifest digest does not match the pinned digest")
        return f"pinned-digest ({self.source})"


class SshSignature:
    """Detached `ssh-keygen -Y sign -n dashboard-release` signature over the manifest bytes,
    checked against a pinned allowed_signers file. Uses the system ssh-keygen only, never PATH."""

    NAMESPACE = "dashboard-release"
    CANDIDATES = ("/usr/bin/ssh-keygen", "/bin/ssh-keygen")

    def __init__(self, allowed_signers: Path, identity: str, ssh_keygen: str | None = None):
        if not SIGNER_IDENTITY.match(identity or ""):
            raise ValueError("signer identity must be 1-128 of [A-Za-z0-9._@+-]")
        self.allowed_signers = Path(allowed_signers)
        self.identity = identity
        self.ssh_keygen = ssh_keygen or next((c for c in self.CANDIDATES if os.path.isfile(c)), None)

    def __call__(self, manifest: bytes, signature: bytes | None) -> str:
        if not self.ssh_keygen or not os.path.isabs(self.ssh_keygen):
            raise AuthenticityError("ssh-keygen is not available at a system path")
        if not signature or not signature.startswith(b"-----BEGIN SSH SIGNATURE-----"):
            raise AuthenticityError("no SSH signature for the manifest")
        try:
            signers, st = read_regular(self.allowed_signers, 64 * 1024, "allowed signers file")
        except VerificationError as exc:
            raise AuthenticityError(exc.problems[0]) from None
        if st.st_mode & 0o022:
            raise AuthenticityError("allowed signers file is writable by group or others")
        with tempfile.TemporaryDirectory(prefix="release-verify-") as tmp:
            # Verify against the exact bytes checked above, not a path that could change.
            signers_path, sig_path = Path(tmp) / "allowed_signers", Path(tmp) / "manifest.sig"
            signers_path.write_bytes(signers)
            sig_path.write_bytes(signature)
            try:
                result = subprocess.run(
                    [self.ssh_keygen, "-Y", "verify", "-f", str(signers_path), "-I", self.identity,
                     "-n", self.NAMESPACE, "-s", str(sig_path)],
                    input=manifest, capture_output=True, timeout=30,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise AuthenticityError(f"ssh-keygen could not run: {type(exc).__name__}") from None
        if result.returncode != 0:
            raise AuthenticityError(f"SSH signature is not valid for signer {self.identity}")
        return f"ssh-signature ({self.identity})"


# --- reading ---------------------------------------------------------------------------


def read_regular(path: Path | str, limit: int, what: str) -> tuple[bytes, os.stat_result]:
    """Read a regular file without following a final symlink, refusing anything over limit."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise VerificationError([f"cannot open {what}: {exc.strerror or type(exc).__name__}"]) from None
    with os.fdopen(fd, "rb") as handle:
        st = os.fstat(handle.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise VerificationError([f"{what} is not a regular file"])
        if st.st_size > limit:
            raise VerificationError([f"{what} is larger than {limit} bytes"])
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise VerificationError([f"{what} is larger than {limit} bytes"])
    return data, st


def strict_json(data: bytes, what: str) -> object:
    def pairs(items: list) -> dict:
        obj: dict = {}
        for key, value in items:
            if key in obj:
                raise ValueError(f"duplicate key {key[:40]!r}")
            obj[key] = value
        return obj

    def constant(name: str) -> None:
        raise ValueError(f"non-finite number {name}")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise VerificationError([f"{what} is not valid JSON: {str(exc)[:120]}"]) from None


# --- policy and manifest ---------------------------------------------------------------


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _channel_for(version: str, release_eligible: bool) -> str:
    if not release_eligible:
        return "dev"
    return "prerelease" if "-" in version else "stable"


def policy_problems(policy: TrustPolicy) -> list[str]:
    problems = []
    if (policy.product, policy.platform) not in SUPPORTED:
        problems.append(f"policy: {policy.product}/{policy.platform} is not a supported product and platform")
    official = OFFICIAL_REPOSITORIES.get(policy.product)
    repository = policy.repository or official
    if not isinstance(repository, str) or not REPOSITORY.match(repository):
        problems.append("policy: bad repository")
    elif repository != official and not policy.allow_fork:
        problems.append(f"policy: {repository} is not the official {policy.product} repository; "
                        "forks need explicit opt-in")
    if policy.check_host and host_platform() != policy.platform:
        problems.append(f"policy: this host is {host_platform() or 'unsupported'}, not {policy.platform}")
    if policy.authenticator is None:
        problems.append("policy: no authenticity check is configured")
    for name in ("installed_version", "expected_version"):
        value = getattr(policy, name)
        if value is not None:
            try:
                parse_version(value)
            except ValueError:
                problems.append(f"policy: {name} is not a semantic version")
    return problems


def manifest_problems(m: object) -> list[str]:
    """Structure of dashboard-release-manifest/v1 plus the cross-checks the schema cannot express."""
    if not isinstance(m, dict):
        return ["manifest is not an object"]
    errors: list[str] = []

    def need(cond: object, message: str) -> None:
        if not cond:
            errors.append(message)

    need(m.get("schema") == MANIFEST_SCHEMA, f"schema must be {MANIFEST_SCHEMA}")
    need(set(m) == MANIFEST_KEYS, "manifest keys differ from the schema")
    if errors:
        return errors
    platform = m["platform"] if isinstance(m["platform"], dict) else {}
    key = platform.get("key")
    need(set(platform) == {"key", "os", "arch"}, "bad platform")
    need((m["product"], key) in SUPPORTED, "unsupported product/platform")
    need(PLATFORM_OS_ARCH.get(key) == (platform.get("os"), platform.get("arch")), "platform os/arch mismatch")
    need(isinstance(m["product_name"], str) and 0 < len(m["product_name"]) <= 100, "bad product_name")
    need(isinstance(m["repository"], str) and REPOSITORY.match(m["repository"]), "bad repository")
    version = m["version"]
    try:
        parse_version(version)
    except ValueError:
        errors.append("version is not semantic")
        version = None

    runtime = m["runtime"] if isinstance(m["runtime"], dict) else {}
    need(isinstance(runtime.get("python"), str) and re.match(r"^3\.\d+$", runtime["python"]), "bad runtime.python")
    need(isinstance(runtime.get("python_abi"), str) and re.match(r"^cp3\d+$", runtime["python_abi"]),
         "bad runtime.python_abi")
    need(isinstance(runtime.get("pip_platforms"), list) and runtime["pip_platforms"]
         and all(isinstance(p, str) for p in runtime["pip_platforms"]), "bad runtime.pip_platforms")

    source = m["source"] if isinstance(m["source"], dict) else {}
    need(set(source) == {"commit", "dirty", "release_eligible", "tree_sha256"}, "bad source")
    commit = source.get("commit")
    need(commit is None or (isinstance(commit, str) and GIT_SHA.match(commit)), "bad source.commit")
    need(source.get("dirty") in (True, False, None), "bad source.dirty")
    eligible = source.get("release_eligible")
    need(isinstance(eligible, bool), "source.release_eligible must be boolean")
    need(eligible is not True or (commit is not None and source.get("dirty") is False),
         "release_eligible requires a clean, committed source")
    need(isinstance(source.get("tree_sha256"), str) and SHA256_HEX.match(source["tree_sha256"]),
         "bad source.tree_sha256")
    if version and isinstance(eligible, bool):
        need(m["channel"] == _channel_for(version, eligible), "channel does not match version and source")

    build = m["build"] if isinstance(m["build"], dict) else {}
    need(_is_int(build.get("source_date_epoch")) and build["source_date_epoch"] >= 0, "bad build.source_date_epoch")
    need(build.get("web_build") in ("npm-ci", "prebuilt"), "bad build.web_build")

    deps = m["dependencies"] if isinstance(m["dependencies"], dict) else {}
    need(deps.get("lock_path") == "apps/api/requirements.release.txt", "bad dependencies.lock_path")
    need(isinstance(deps.get("lock_sha256"), str) and SHA256_HEX.match(deps["lock_sha256"]),
         "bad dependencies.lock_sha256")
    pkgs = deps.get("packages")
    need(isinstance(pkgs, list) and pkgs and all(
        isinstance(p, dict) and isinstance(p.get("name"), str) and PACKAGE_NAME.match(p["name"])
        and isinstance(p.get("version"), str) and p["version"] for p in pkgs), "bad dependencies.packages")

    art = m["artifact"] if isinstance(m["artifact"], dict) else {}
    base = f"{m['product']}-{m['version']}-{key}"
    need(set(art) == {"name", "root", "format", "sha256", "size"}, "bad artifact")
    need(art.get("name") == f"{base}.tar.gz", "artifact.name does not match product, version and platform")
    need(art.get("root") == base, "artifact.root does not match product, version and platform")
    need(art.get("format") == "tar+gzip", "artifact.format must be tar+gzip")
    need(isinstance(art.get("sha256"), str) and SHA256_HEX.match(art["sha256"]), "bad artifact.sha256")
    need(_is_int(art.get("size")) and 0 < art["size"] <= MAX_ARTIFACT_BYTES, "artifact.size out of range")

    files = m["files"]
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        return errors + ["files must be a non-empty list within the file limit"]
    paths = []
    for record in files:
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "size", "mode"}:
            errors.append("bad file record")
            continue
        path = record["path"]
        need(safe_relpath(path), "unsafe file path in manifest")
        need(isinstance(record["sha256"], str) and SHA256_HEX.match(record["sha256"]), "bad file sha256")
        need(_is_int(record["size"]) and 0 <= record["size"] <= MAX_FILE_BYTES, "file size out of range")
        need(record["mode"] in FILE_MODES, "bad file mode")
        paths.append(path)
    if errors:
        return errors
    need(paths == sorted(paths) and len(set(paths)) == len(paths), "files must be sorted and unique")
    need("manifest.json" not in paths, "files must not list manifest.json")
    for required in REQUIRED_FILES:
        need(required in paths, f"required file missing: {required}")
    total = sum(r["size"] for r in files)
    need(total <= MAX_TOTAL_BYTES, "total size over the limit")
    contents = m["contents"] if isinstance(m["contents"], dict) else {}
    need(set(contents) == {"manifest_path", "manifest_sha256", "file_count", "total_size"}, "bad contents")
    need(contents.get("manifest_path") == "manifest.json", "contents.manifest_path must be manifest.json")
    need(isinstance(contents.get("manifest_sha256"), str) and SHA256_HEX.match(contents["manifest_sha256"]),
         "bad contents.manifest_sha256")
    need(contents.get("file_count") == len(files), "contents.file_count mismatch")
    need(contents.get("total_size") == total, "contents.total_size mismatch")
    return errors


def match_policy(m: dict, policy: TrustPolicy) -> tuple[list[str], str]:
    """Trusted repository, product, platform, channel and version rules. Returns (problems, change)."""
    problems = []
    repository = policy.repository or OFFICIAL_REPOSITORIES.get(policy.product)
    if m["repository"] != repository:
        problems.append(f"release names repository {m['repository']}, but it was fetched from {repository}")
    if m["product"] != policy.product:
        problems.append(f"release is for product {m['product']}, not {policy.product}")
    if m["platform"]["key"] != policy.platform:
        problems.append(f"release is for {m['platform']['key']}, not {policy.platform}")
    channel = m["channel"]
    if channel == "dev" and not policy.allow_dev:
        problems.append("release is a dev build and is never an update candidate")
    if channel == "prerelease" and not policy.allow_prerelease:
        problems.append("release is a prerelease; prereleases need explicit opt-in")
    if policy.expected_version is not None and m["version"] != policy.expected_version:
        problems.append(f"release version {m['version']} is not the selected {policy.expected_version}")
    change = "install"
    if policy.installed_version is not None:
        order = compare_versions(m["version"], policy.installed_version)
        change = {1: "upgrade", 0: "reinstall", -1: "downgrade"}[order]
        if change == "reinstall" and not policy.allow_reinstall:
            problems.append(f"version {m['version']} is already installed")
        if change == "downgrade" and not policy.allow_downgrade:
            problems.append(f"{m['version']} is older than the installed {policy.installed_version}; "
                            "downgrades need explicit opt-in")
    return problems, change


# --- archive ---------------------------------------------------------------------------


def safe_relpath(path: object) -> bool:
    if not isinstance(path, str) or not path or len(path) > 1024:
        return False
    return all(part not in (".", "..") and PATH_PART.match(part) for part in path.split("/"))


def gunzip_capped(data: bytes, limit: int) -> bytes:
    """Decompress exactly one gzip member, refusing output over limit or trailing data."""
    decomp = zlib.decompressobj(wbits=31)
    out = bytearray()
    pending = data
    try:
        while not decomp.eof:
            chunk = decomp.decompress(pending, 1 << 20)
            out += chunk
            if len(out) > limit:
                raise VerificationError(["archive expands beyond the size limit"])
            pending = decomp.unconsumed_tail
            if not chunk and not pending:
                raise VerificationError(["archive is truncated"])
    except zlib.error:
        raise VerificationError(["archive is not valid gzip"]) from None
    if decomp.unused_data:
        raise VerificationError(["archive has data after the gzip stream"])
    return bytes(out)


def read_members(raw_tar: bytes, root: str) -> tuple[dict[str, tuple[bytes, int]], list[str]]:
    """Every regular member as rel path -> (bytes, mode). Nothing is written to disk."""
    errors: list[str] = []
    files: dict[str, tuple[bytes, int]] = {}
    seen: set[str] = set()
    folded: set[str] = set()
    dirs: set[str] = set()
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as tar:
            count = 0
            while (member := tar.next()) is not None:
                count += 1
                if count > MAX_MEMBERS:
                    return files, errors + ["too many archive members"]
                name = member.name
                if name in seen or name.casefold() in folded:
                    errors.append("duplicate or case-colliding member")
                    continue
                seen.add(name)
                folded.add(name.casefold())
                if name != root and not name.startswith(root + "/"):
                    errors.append("member outside the release root")
                    continue
                rel = name[len(root) + 1:]
                if name != root and not safe_relpath(rel):
                    errors.append("unsafe member path")
                    continue
                if member.issym() or member.islnk() or member.linkname:
                    errors.append("symlink or hardlink member")
                    continue
                if member.sparse is not None or any(k.startswith("GNU.sparse") for k in member.pax_headers):
                    errors.append("sparse member")
                    continue
                if member.isdir():
                    if member.mode != DIR_MODE:
                        errors.append("unexpected directory mode")
                    if name != root:
                        dirs.add(rel)
                    continue
                if name == root or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
                    errors.append("member is not a regular file or directory")
                    continue
                if member.mode not in FILE_MODES.values():
                    errors.append("unexpected file mode")
                    continue
                if member.size > MAX_FILE_BYTES:
                    errors.append("member over the per-file size limit")
                    continue
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    return files, errors + ["archive expands beyond the size limit"]
                handle = tar.extractfile(member)
                data = handle.read(member.size + 1) if handle else b""
                if len(data) != member.size:
                    errors.append("member data is truncated")
                    continue
                files[rel] = (data, member.mode)
    except (tarfile.TarError, EOFError, OSError, ValueError, UnicodeError):
        errors.append("archive is not a valid tar")
    for rel in files:
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        while parent:
            if parent in files:
                errors.append("a file is also used as a directory")
                break
            parent = parent.rsplit("/", 1)[0] if "/" in parent else ""
    if dirs & files.keys():
        errors.append("a file is also used as a directory")
    return files, errors


def contents_problems(m: dict, files: dict[str, tuple[bytes, int]]) -> list[str]:
    errors: list[str] = []
    inner_entry = files.get("manifest.json")
    if inner_entry is None:
        return ["artifact has no manifest.json"]
    inner_bytes = inner_entry[0]
    if hashlib.sha256(inner_bytes).hexdigest() != m["contents"]["manifest_sha256"]:
        errors.append("inner manifest.json digest does not match the release manifest")
    try:
        inner = strict_json(inner_bytes, "inner manifest.json")
    except VerificationError as exc:
        return errors + exc.problems
    if not isinstance(inner, dict) or inner.get("schema") != FILES_SCHEMA:
        return errors + [f"inner manifest schema must be {FILES_SCHEMA}"]
    if inner.get("files") != m["files"]:
        errors.append("inner manifest file list differs from the release manifest")
    for name, expected in (("product", m["product"]), ("version", m["version"]), ("platform", m["platform"]["key"])):
        if inner.get(name) != expected:
            errors.append(f"inner manifest {name} differs")

    expected = {r["path"]: r for r in m["files"]}
    actual = files.keys() - {"manifest.json"}
    if actual - expected.keys():
        errors.append(f"{len(actual - expected.keys())} unlisted file(s) in the artifact")
    if expected.keys() - actual:
        errors.append(f"{len(expected.keys() - actual)} listed file(s) missing from the artifact")
    for rel in sorted(actual & expected.keys()):
        data, mode = files[rel]
        record = expected[rel]
        if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            errors.append(f"digest mismatch: {rel}")
        elif mode != FILE_MODES[record["mode"]]:
            errors.append(f"mode mismatch: {rel}")

    lock = files.get("apps/api/requirements.release.txt", (b"", 0))[0]
    if hashlib.sha256(lock).hexdigest() != m["dependencies"]["lock_sha256"]:
        errors.append("dependency lock digest mismatch")
    try:
        info = strict_json(files.get("BUILD_INFO.json", (b"{}", 0))[0], "BUILD_INFO.json")
    except VerificationError as exc:
        return errors + exc.problems
    info = info if isinstance(info, dict) else {}
    for name, value in (("product", m["product"]), ("version", m["version"]), ("platform", m["platform"]["key"]),
                        ("source_commit", m["source"]["commit"]), ("channel", m["channel"]),
                        ("source_tree_sha256", m["source"]["tree_sha256"]),
                        ("source_date_epoch", m["build"]["source_date_epoch"])):
        if info.get(name) != value:
            errors.append(f"BUILD_INFO.json {name} differs from the manifest")
    return errors


# --- entry points ----------------------------------------------------------------------


def verify_bytes(manifest_bytes: bytes, signature: bytes | None, artifact: bytes,
                 policy: TrustPolicy) -> VerifiedRelease:
    """Verify in-memory release bytes against the policy. Raises VerificationError."""
    try:
        return _verify(manifest_bytes, signature, artifact, policy)
    except VerificationError:
        raise
    except Exception as exc:  # noqa: BLE001 - anything unexpected refuses the package
        raise VerificationError([f"verification could not complete ({type(exc).__name__})"]) from None


def verify_release(manifest_path: Path | str, artifact_path: Path | str, policy: TrustPolicy,
                   signature_path: Path | str | None = None) -> VerifiedRelease:
    """Read the manifest, optional detached signature and artifact once each, then verify."""
    problems = policy_problems(policy)
    if problems:
        raise VerificationError(problems)
    manifest_bytes, _ = read_regular(manifest_path, MAX_MANIFEST_BYTES, "release manifest")
    signature = None
    if signature_path is not None:
        signature, _ = read_regular(signature_path, MAX_SIGNATURE_BYTES, "manifest signature")
    artifact, _ = read_regular(artifact_path, MAX_ARTIFACT_BYTES, "release artifact")
    return verify_bytes(manifest_bytes, signature, artifact, policy)


def _verify(manifest_bytes: bytes, signature: bytes | None, artifact: bytes, policy: TrustPolicy) -> VerifiedRelease:
    problems = policy_problems(policy)
    if problems:
        raise VerificationError(problems)
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise VerificationError(["release manifest is over the size limit"])
    try:
        authenticity = policy.authenticator(manifest_bytes, signature)
    except AuthenticityError as exc:
        raise VerificationError([f"authenticity: {exc}"]) from None
    if not isinstance(authenticity, str) or not authenticity:
        raise VerificationError(["authenticity: the check returned no result"])

    manifest = strict_json(manifest_bytes, "release manifest")
    problems = manifest_problems(manifest)
    if problems:
        raise VerificationError(problems)
    problems, change = match_policy(manifest, policy)
    if problems:
        raise VerificationError(problems)

    if len(artifact) > MAX_ARTIFACT_BYTES:
        raise VerificationError(["artifact is over the size limit"])
    if len(artifact) != manifest["artifact"]["size"]:
        raise VerificationError(["artifact size does not match the manifest"])
    artifact_sha = hashlib.sha256(artifact).hexdigest()
    if not hmac.compare_digest(artifact_sha, manifest["artifact"]["sha256"]):
        raise VerificationError(["artifact sha256 does not match the manifest"])

    raw_tar = gunzip_capped(artifact, MAX_TOTAL_BYTES + TAR_OVERHEAD_BYTES)
    files, problems = read_members(raw_tar, manifest["artifact"]["root"])
    if problems:
        raise VerificationError(problems)
    problems = contents_problems(manifest, files)
    if problems:
        raise VerificationError(problems)
    return VerifiedRelease(
        product=manifest["product"], platform=manifest["platform"]["key"], repository=manifest["repository"],
        version=manifest["version"], channel=manifest["channel"], change=change, authenticity=authenticity,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), artifact_sha256=artifact_sha,
        manifest=manifest, files=files,
    )


def extract(release: VerifiedRelease, destination: Path | str) -> Path:
    """Write the verified files into a new directory. The parent must exist and must not be a
    symlink; the destination must not exist. On any failure the new directory is removed."""
    if not isinstance(release, VerifiedRelease):
        raise VerificationError(["only a verified release can be extracted"])
    destination = Path(destination)
    nofollow_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        parent_fd = os.open(destination.parent, nofollow_dir)
    except OSError as exc:
        raise VerificationError([f"cannot open the staging parent: {exc.strerror or type(exc).__name__}"]) from None
    created = False
    try:
        try:
            os.mkdir(destination.name, 0o700, dir_fd=parent_fd)
        except OSError as exc:
            raise VerificationError([f"cannot create the staging directory: {exc.strerror}"]) from None
        created = True
        root_fd = os.open(destination.name, nofollow_dir, dir_fd=parent_fd)
        try:
            for rel in sorted(release.files):
                data, mode = release.files[rel]
                _write_file(root_fd, rel, data, mode, nofollow_dir)
            _chmod_tree(root_fd, nofollow_dir)
            os.fchmod(root_fd, DIR_MODE)
            os.fsync(root_fd)
        finally:
            os.close(root_fd)
    except BaseException:
        if created:
            try:
                shutil.rmtree(destination.name, dir_fd=parent_fd, ignore_errors=True)
            except NotImplementedError:
                pass  # no symlink-safe rmtree here; the caller's staging cleanup removes it
        raise
    finally:
        os.close(parent_fd)
    return destination


def _write_file(root_fd: int, rel: str, data: bytes, mode: int, nofollow_dir: int) -> None:
    if not safe_relpath(rel) or mode not in FILE_MODES.values():
        raise VerificationError(["refusing to write an unverified path or mode"])
    *parents, name = rel.split("/")
    fd = os.dup(root_fd)
    try:
        for part in parents:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, nofollow_dir, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        out = os.open(name, flags, 0o600, dir_fd=fd)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(out, view):]
            os.fchmod(out, mode)
            os.fsync(out)
        finally:
            os.close(out)
    finally:
        os.close(fd)


def _chmod_tree(dir_fd: int, nofollow_dir: int) -> None:
    with os.scandir(dir_fd) as entries:
        subdirs = [entry.name for entry in entries if entry.is_dir(follow_symlinks=False)]
    for name in subdirs:
        child = os.open(name, nofollow_dir, dir_fd=dir_fd)
        try:
            _chmod_tree(child, nofollow_dir)
            os.fchmod(child, DIR_MODE)
        finally:
            os.close(child)
