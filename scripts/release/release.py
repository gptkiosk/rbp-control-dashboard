#!/usr/bin/env python3
"""Build, verify and scan versioned OS/arch release artifacts.

Standard library only. Run from any directory with an isolated interpreter:

    python3 -I scripts/release/release.py lock      [--platform KEY]
    python3 -I scripts/release/release.py build     [--platform KEY] [--out DIR] [--dev] ...
    python3 -I scripts/release/release.py repro     [--platform KEY] [--out DIR] [--dev] ...
    python3 -I scripts/release/release.py verify    MANIFEST [--artifact PATH]
    python3 -I scripts/release/release.py scan      ARTIFACT [--gitleaks auto|on|off]

The product, platforms and file set come from packaging/product.json. Python
dependencies are installed only from the hash-pinned lock apps/api/locks/<platform>.txt
(written by `lock`); the web UI is built with `npm ci` from apps/web/package-lock.json
in a temporary copy, so the working tree is never modified.

Artifacts never contain secrets, runtime data or host identities: the file set is an
explicit allowlist, a path/content scan runs on every build and fails it, and the
manifest records only the source commit, digests and tool versions.
"""

from __future__ import annotations

import argparse
import ast
import getpass
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api"
WEB_DIR = REPO_ROOT / "apps" / "web"
PRODUCT_FILE = REPO_ROOT / "packaging" / "product.json"
SCAN_ALLOWLIST_FILE = REPO_ROOT / "packaging" / "scan-allowlist.json"

MANIFEST_SCHEMA = "dashboard-release-manifest/v1"
FILES_SCHEMA = "dashboard-release-files/v1"

# Product/platform pairs this tooling builds. The updater's trust policy is separate.
SUPPORTED = {("mcd", "darwin-arm64"), ("rcd", "linux-arm64")}
PLATFORM_OS_ARCH = {"darwin-arm64": ("darwin", "arm64"), "linux-arm64": ("linux", "arm64")}

MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_FILES = 5000
FILE_MODES = (0o644, 0o755)

# Files the artifact must carry to be installable.
REQUIRED_FILES = (
    "BUILD_INFO.json",
    "LICENSE",
    "packaging/product.json",
    "apps/api/main.py",
    "apps/api/version.py",
    "apps/api/requirements.release.txt",
    "apps/web/dist/index.html",
)

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LOCK_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==([^\s;\\]+)")


class ReleaseError(Exception):
    pass


def die(message: str) -> None:
    raise ReleaseError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        die(f"{cmd[0]} failed to run: {exc}")
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-25:])
        die(f"`{' '.join(cmd)}` exited {result.returncode}:\n{tail}")
    return result.stdout


# --- product, version and source ----------------------------------------------------


def load_product() -> dict:
    try:
        product = json.loads(PRODUCT_FILE.read_text())
    except (OSError, ValueError) as exc:
        die(f"cannot read {PRODUCT_FILE}: {exc}")
    for key in ("product", "product_name", "repository", "platforms", "include"):
        if key not in product:
            die(f"{PRODUCT_FILE} is missing {key!r}")
    if not REPOSITORY.match(product["repository"]):
        die(f"{PRODUCT_FILE}: bad repository {product['repository']!r}")
    return product


def select_platform(product: dict, key: str | None) -> tuple[str, dict]:
    platforms = product["platforms"]
    if key is None:
        if len(platforms) != 1:
            die(f"choose --platform from {sorted(platforms)}")
        key = next(iter(platforms))
    if key not in platforms:
        die(f"platform {key!r} is not in {PRODUCT_FILE} ({sorted(platforms)})")
    if (product["product"], key) not in SUPPORTED:
        die(f"{product['product']} on {key} is not a supported release target")
    return key, platforms[key]


def read_version() -> str:
    tree = ast.parse((API_DIR / "version.py").read_text())
    version = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets
        ):
            version = ast.literal_eval(node.value)
    if not isinstance(version, str) or not SEMVER.match(version):
        die(f"apps/api/version.py __version__ is not a semantic version: {version!r}")
    return version


def source_info() -> dict:
    """Commit and cleanliness of the source tree; unversioned trees are never release-eligible."""
    git = shutil.which("git")
    if not git or not (REPO_ROOT / ".git").exists():
        return {"commit": None, "dirty": None, "release_eligible": False}
    commit = run([git, "rev-parse", "HEAD"], REPO_ROOT).strip()
    status = run([git, "status", "--porcelain", "--untracked-files=normal"], REPO_ROOT)
    dirty = bool(status.strip())
    return {"commit": commit, "dirty": dirty, "release_eligible": not dirty}


# --- dependency lock ------------------------------------------------------------------


def lock_path(platform_key: str) -> Path:
    return API_DIR / "locks" / f"{platform_key}.txt"


def parse_lock(path: Path) -> list[dict]:
    """Return [{name, version}] and require every requirement to be ==-pinned with hashes."""
    if not path.is_file():
        die(f"missing dependency lock {path.relative_to(REPO_ROOT)}; run `release.py lock` first")
    logical: list[str] = []
    current = ""
    for raw in path.read_text().splitlines():
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        current += line
        if current.strip():
            logical.append(current.strip())
        current = ""
    packages = []
    for entry in logical:
        if entry.startswith("-"):
            die(f"{path.name}: option lines are not allowed in a release lock: {entry[:60]!r}")
        match = LOCK_PIN.match(entry)
        if not match:
            die(f"{path.name}: requirement is not pinned with ==: {entry[:60]!r}")
        if "--hash=sha256:" not in entry:
            die(f"{path.name}: {match.group(1)} has no sha256 hash")
        packages.append({"name": match.group(1).lower().replace("_", "-"), "version": match.group(3)})
    if not packages:
        die(f"{path.name} lists no packages")
    return sorted(packages, key=lambda p: p["name"])


def cmd_lock(args: argparse.Namespace) -> int:
    product = load_product()
    uv = shutil.which("uv")
    if not uv:
        die("uv is required to resolve the lock (https://docs.astral.sh/uv/)")
    keys = [args.platform] if args.platform else sorted(product["platforms"])
    for key in keys:
        key, platform = select_platform(product, key)
        out = lock_path(key)
        out.parent.mkdir(exist_ok=True)
        cmd = [
            uv, "pip", "compile", "requirements.runtime.in",
            "--constraint", "requirements.lock.txt",
            "--python-version", platform["python_version"],
            "--python-platform", platform["uv_python_platform"],
            # Wheels only: installs never run package build scripts or need a compiler on the Pi.
            "--only-binary", ":all:",
            "--generate-hashes", "--no-header", "--quiet",
            "--output-file", str(out.relative_to(API_DIR)),
        ]
        if args.exclude_newer:
            cmd += ["--exclude-newer", args.exclude_newer]
        run(cmd, API_DIR, env=minimal_env())
        packages = parse_lock(out)
        print(f"{out.relative_to(REPO_ROOT)}: {len(packages)} pinned packages, sha256 {sha256_file(out)}")
    return 0


# --- file collection ---------------------------------------------------------------------


def minimal_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    passthrough = ("PATH", "HOME", "TMPDIR", "UV_CACHE_DIR", "npm_config_cache", "SSL_CERT_FILE",
                   "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy")
    env = {k: os.environ[k] for k in passthrough if k in os.environ}
    env.update({"LC_ALL": "C", "TZ": "UTC"})
    env.update(extra or {})
    return env


def file_mode(rel: str, source: Path | None) -> int:
    if rel.endswith(".sh") or (source is not None and source.stat().st_mode & 0o111):
        return 0o755
    return 0o644


def checked_file(path: Path, base: Path) -> str:
    """Relative POSIX path of a regular, non-symlinked file inside base."""
    rel = path.relative_to(base).as_posix()
    probe = base
    for part in Path(rel).parts:
        probe = probe / part
        if probe.is_symlink():
            die(f"refusing symlink in release input: {probe}")
    if not path.is_file():
        die(f"release input is not a regular file: {path}")
    return rel


def collect_sources(patterns: list[str]) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for pattern in patterns:
        if pattern.startswith("/") or ".." in Path(pattern).parts:
            die(f"include pattern must stay inside the repository: {pattern!r}")
        matches = [p for p in sorted(REPO_ROOT.glob(pattern)) if not p.is_dir()]
        if not matches:
            die(f"include pattern matched nothing: {pattern!r}")
        for path in matches:
            files[checked_file(path, REPO_ROOT)] = path
    return files


def collect_web(dist: Path) -> dict[str, Path]:
    if not (dist / "index.html").is_file():
        die(f"web build has no index.html: {dist}")
    files = {}
    for path in sorted(dist.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        rel = checked_file(path, dist)
        if rel.endswith(".map"):
            continue  # source maps can carry absolute build paths
        files[f"apps/web/dist/{rel}"] = path
    return files


def build_web(work_root: Path, source: dict, source_date_epoch: int) -> Path:
    """Build the UI with `npm ci` from package-lock.json in a copy, leaving apps/web untouched."""
    npm = shutil.which("npm")
    if not npm:
        die("npm is required to build the web UI (or pass --skip-web-build)")
    work = work_root / "web"
    shutil.copytree(
        WEB_DIR, work, symlinks=False,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".vite", "*.log", ".DS_Store"),
    )
    extra = {"CI": "1", "SOURCE_DATE_EPOCH": str(source_date_epoch)}
    if source["commit"]:
        # vite.config.ts stamps `git rev-parse --short HEAD`; point it at the real repository.
        extra["GIT_DIR"] = str(REPO_ROOT / ".git")
    env = minimal_env(extra)
    run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], work, env)
    run([npm, "run", "build"], work, env)
    return work / "dist"


def resolve_source_date_epoch(arg: int | None, source: dict, files: dict[str, Path]) -> tuple[int, str]:
    if arg is not None:
        return arg, "argument"
    if os.environ.get("SOURCE_DATE_EPOCH", "").isdigit():
        return int(os.environ["SOURCE_DATE_EPOCH"]), "environment"
    if source["commit"] and not source["dirty"]:
        out = run(["git", "log", "-1", "--format=%ct", source["commit"]], REPO_ROOT).strip()
        return int(out), "commit"
    return max(int(p.stat().st_mtime) for p in files.values()), "newest-source-mtime"


# --- archive ---------------------------------------------------------------------------


def write_archive(path: Path, root: str, entries: dict[str, tuple[bytes, int]], mtime: int) -> None:
    """Deterministic tar.gz: sorted entries, fixed owner/mtime/modes, no gzip name or time."""
    names = set()
    for rel in entries:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            names.add("/".join(parts[:i]))
    members = [(d, None, 0o755) for d in names] + [(rel, data, mode) for rel, (data, mode) in entries.items()]
    members.sort(key=lambda m: m[0])
    with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for rel, data, mode in [("", None, 0o755)] + members:
                info = tarfile.TarInfo(f"{root}/{rel}" if rel else root)
                info.mtime = mtime
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = mode
                if data is None:
                    info.type = tarfile.DIRTYPE
                    tar.addfile(info)
                else:
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))


def file_records(entries: dict[str, tuple[bytes, int]]) -> list[dict]:
    return [
        {"path": rel, "sha256": sha256_bytes(data), "size": len(data), "mode": f"{mode:04o}"}
        for rel, (data, mode) in sorted(entries.items())
    ]


def tree_digest(records: list[dict]) -> str:
    return sha256_bytes("".join(f"{r['path']}\0{r['sha256']}\n" for r in records).encode())


def tool_versions() -> dict:
    versions = {"python": sys.version.split()[0]}
    for tool in ("node", "npm", "uv"):
        exe = shutil.which(tool)
        if exe:
            try:
                out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
                versions[tool] = out.splitlines()[0] if out else "unknown"
            except (OSError, subprocess.SubprocessError):
                versions[tool] = "unknown"
    return versions


def channel_for(version: str, source: dict) -> str:
    if not source["release_eligible"]:
        return "dev"
    return "prerelease" if "-" in version else "stable"


def validate_python_sources(sources: dict[str, Path], python_version: str) -> None:
    """Compile with the actual target runtime; older feature_version flags do not reject all PEP701 syntax."""
    interpreter = sys.executable if sys.version_info[:2] == tuple(map(int, python_version.split('.'))) else shutil.which('python' + python_version)
    if not interpreter:
        die(f"Python {python_version} is required on the build host to validate package syntax; install that runtime and put it on PATH.")
    payload = {name: path.read_bytes().hex() for name, path in sources.items() if name.endswith('.py')}
    code = """
import json, sys
expected, = sys.argv[1:]
if f'{sys.version_info.major}.{sys.version_info.minor}' != expected:
    sys.exit('Syntax-check interpreter does not match Python ' + expected)
errors = []
for name, data in json.load(sys.stdin).items():
    try:
        compile(bytes.fromhex(data), name, 'exec')
    except SyntaxError as exc:
        errors.append(f'{name}:{exc.lineno}: {exc.msg}')
if errors:
    sys.exit('\\n'.join(errors))
"""
    result = subprocess.run([interpreter, '-I', '-c', code, python_version], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        die(f"Package Python {python_version} syntax validation failed:\n{result.stderr.strip()}")


def build_once(args: argparse.Namespace, out_dir: Path) -> dict:
    product = load_product()
    key, platform = select_platform(product, args.platform)
    version = read_version()
    source = source_info()
    if not source["release_eligible"] and not args.dev:
        state = "unversioned (no git)" if source["commit"] is None else "dirty"
        die(f"source tree is {state}; pass --dev to build a non-release artifact marked channel=dev")

    if not args.dev:
        # A release carries its notes: the build stops when CHANGELOG.md has no dated section for this version.
        import importlib.util
        spec = importlib.util.spec_from_file_location("mcd_changelog", REPO_ROOT / "scripts" / "release" / "changelog.py")
        changelog = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(changelog)
        try:
            changelog.check((REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)
        except (changelog.ChangelogError, OSError) as exc:
            die(f"release notes missing: {exc}")

    lock = lock_path(key)
    packages = parse_lock(lock)
    sources = collect_sources(product["include"])
    validate_python_sources(sources, platform["python_version"])
    sde, sde_from = resolve_source_date_epoch(args.source_date_epoch, source, sources)
    source_records = file_records({rel: (p.read_bytes(), file_mode(rel, p)) for rel, p in sources.items()})

    base = f"{product['product']}-{version}-{key}"
    artifact = out_dir / f"{base}.tar.gz"
    manifest_file = out_dir / f"{base}.manifest.json"
    if (artifact.exists() or manifest_file.exists()) and not args.force:
        die(f"{artifact} already exists; use another --out or --force")

    with tempfile.TemporaryDirectory(prefix="release-build-") as tmp:
        tmp_path = Path(tmp)
        if args.skip_web_build:
            dist, web_build = WEB_DIR / "dist", "prebuilt"
        else:
            dist, web_build = build_web(tmp_path, source, sde), "npm-ci"
        web = collect_web(dist)

        entries: dict[str, tuple[bytes, int]] = {}
        for rel, path in {**sources, **web}.items():
            data = path.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                die(f"{rel} is larger than {MAX_FILE_BYTES} bytes")
            entries[rel] = (data, file_mode(rel, path if rel in sources else None))
        lock_bytes = lock.read_bytes()
        entries["apps/api/requirements.release.txt"] = (lock_bytes, 0o644)
        entries["packaging/product.json"] = (PRODUCT_FILE.read_bytes(), 0o644)
        build_info = {
            "product": product["product"],
            "version": version,
            "platform": key,
            "source_commit": source["commit"],
            "source_dirty": source["dirty"],
            "source_tree_sha256": tree_digest(source_records),
            "source_date_epoch": sde,
            "web_build": web_build,
            "channel": channel_for(version, source),
        }
        entries["BUILD_INFO.json"] = (canonical_json(build_info), 0o644)

        records = file_records(entries)
        if len(records) > MAX_FILES:
            die(f"artifact would hold {len(records)} files (limit {MAX_FILES})")
        inner = {"schema": FILES_SCHEMA, "product": product["product"], "version": version,
                 "platform": key, "files": records}
        inner_bytes = canonical_json(inner)
        entries["manifest.json"] = (inner_bytes, 0o644)

        out_dir.mkdir(parents=True, exist_ok=True)
        partial = artifact.with_name(artifact.name + ".partial")
        write_archive(partial, base, entries, sde)
        os.replace(partial, artifact)

        os_name, arch = PLATFORM_OS_ARCH[key]
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "product": product["product"],
            "product_name": product["product_name"],
            "repository": product["repository"],
            "version": version,
            "channel": build_info["channel"],
            "platform": {"key": key, "os": os_name, "arch": arch},
            "runtime": {
                "python": platform["python_version"],
                "python_abi": platform["python_abi"],
                "pip_platforms": platform["pip_platforms"],
            },
            "source": {
                "commit": source["commit"],
                "dirty": source["dirty"],
                "release_eligible": source["release_eligible"],
                "tree_sha256": build_info["source_tree_sha256"],
            },
            "build": {
                "source_date_epoch": sde,
                "source_date_epoch_from": sde_from,
                "web_build": web_build,
                "tools": tool_versions(),
            },
            "dependencies": {
                "lock_path": "apps/api/requirements.release.txt",
                "lock_sha256": sha256_bytes(lock_bytes),
                "packages": packages,
            },
            "artifact": {
                "name": artifact.name,
                "root": base,
                "format": "tar+gzip",
                "sha256": sha256_file(artifact),
                "size": artifact.stat().st_size,
            },
            "contents": {
                "manifest_path": "manifest.json",
                "manifest_sha256": sha256_bytes(inner_bytes),
                "file_count": len(records),
                "total_size": sum(r["size"] for r in records),
            },
            "files": records,
        }
        manifest_file.write_bytes(canonical_json(manifest))

        problems = validate_manifest(manifest)
        problems = problems or verify_artifact(manifest, artifact)
        if problems:
            die("built artifact failed verification:\n  " + "\n  ".join(problems))
        identities = host_identities([str(tmp_path), os.path.realpath(tmp)])
        findings = scan_artifact(artifact, identities, args.gitleaks)
        if findings:
            artifact.rename(artifact.with_name(artifact.name + ".rejected"))
            manifest_file.unlink()
            die("content scan rejected the artifact (renamed to .rejected):\n  " + "\n  ".join(findings))

    write_sha256sums(out_dir)
    print(f"{artifact.name}\n  sha256 {manifest['artifact']['sha256']}\n  size   {manifest['artifact']['size']}"
          f"\n  files  {len(records)}\n  channel {manifest['channel']}  source_date_epoch {sde} ({sde_from})")
    return manifest


def write_sha256sums(out_dir: Path) -> None:
    lines = [f"{sha256_file(p)}  {p.name}\n" for p in sorted(out_dir.iterdir())
             if p.is_file() and (p.name.endswith(".tar.gz") or p.name.endswith(".manifest.json"))]
    (out_dir / "SHA256SUMS").write_text("".join(lines))


def cmd_build(args: argparse.Namespace) -> int:
    build_once(args, Path(args.out).resolve())
    return 0


def cmd_repro(args: argparse.Namespace) -> int:
    """Build twice into separate directories and compare artifact digests."""
    out = Path(args.out).resolve()
    args.force = True  # repro owns build-1/ and build-2/ under --out
    first = build_once(args, out / "build-1")
    second = build_once(args, out / "build-2")
    report = {
        "artifact": first["artifact"]["name"],
        "build_1_sha256": first["artifact"]["sha256"],
        "build_2_sha256": second["artifact"]["sha256"],
        "identical": first["artifact"]["sha256"] == second["artifact"]["sha256"],
        "differing_files": [],
    }
    if not report["identical"]:
        a = {r["path"]: r["sha256"] for r in first["files"]}
        b = {r["path"]: r["sha256"] for r in second["files"]}
        report["differing_files"] = sorted(p for p in a.keys() | b.keys() if a.get(p) != b.get(p))
        if not report["differing_files"]:
            report["note"] = "file contents match; the difference is in tar/gzip encoding"
    (out / "repro-report.json").write_bytes(canonical_json(report))
    print(json.dumps(report, indent=2))
    return 0 if report["identical"] else 1


# --- verification --------------------------------------------------------------------


def safe_relpath(path: object) -> bool:
    if not isinstance(path, str) or not path or len(path) > 1024:
        return False
    if path.startswith("/") or "\\" in path or any(ord(c) < 32 or ord(c) == 127 for c in path):
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def validate_manifest(m: dict) -> list[str]:
    """Structural validation equivalent to packaging/release-manifest.schema.json."""
    errors: list[str] = []

    def need(cond: bool, message: str) -> None:
        if not cond:
            errors.append(message)

    if not isinstance(m, dict):
        return ["manifest is not an object"]
    need(m.get("schema") == MANIFEST_SCHEMA, f"schema must be {MANIFEST_SCHEMA}")
    for key in ("product", "product_name", "repository", "version", "channel", "platform", "runtime",
                "source", "build", "dependencies", "artifact", "contents", "files"):
        need(key in m, f"missing {key}")
    if errors:
        return errors
    platform = m["platform"] if isinstance(m["platform"], dict) else {}
    key = platform.get("key")
    need((m["product"], key) in SUPPORTED, f"unsupported product/platform {m['product']}/{key}")
    need(PLATFORM_OS_ARCH.get(key) == (platform.get("os"), platform.get("arch")), "platform os/arch mismatch")
    need(isinstance(m["repository"], str) and bool(REPOSITORY.match(m["repository"])), "bad repository")
    version = m["version"]
    need(isinstance(version, str) and bool(SEMVER.match(version)), "version is not semantic")

    source = m["source"] if isinstance(m["source"], dict) else {}
    commit = source.get("commit")
    need(commit is None or (isinstance(commit, str) and bool(GIT_SHA.match(commit))), "bad source.commit")
    need(isinstance(source.get("release_eligible"), bool), "source.release_eligible must be boolean")
    need(source.get("release_eligible") is not True or (commit is not None and source.get("dirty") is False),
         "release_eligible requires a clean, committed source")
    need(isinstance(source.get("tree_sha256"), str) and bool(SHA256_HEX.match(source.get("tree_sha256", ""))),
         "bad source.tree_sha256")
    if isinstance(version, str) and isinstance(source.get("release_eligible"), bool):
        expected = channel_for(version, source)
        need(m["channel"] == expected, f"channel must be {expected!r}")

    build = m["build"] if isinstance(m["build"], dict) else {}
    sde = build.get("source_date_epoch")
    need(isinstance(sde, int) and not isinstance(sde, bool) and sde >= 0, "bad build.source_date_epoch")
    need(build.get("web_build") in ("npm-ci", "prebuilt"), "bad build.web_build")

    deps = m["dependencies"] if isinstance(m["dependencies"], dict) else {}
    need(deps.get("lock_path") == "apps/api/requirements.release.txt", "bad dependencies.lock_path")
    need(bool(SHA256_HEX.match(str(deps.get("lock_sha256", "")))), "bad dependencies.lock_sha256")
    pkgs = deps.get("packages")
    need(isinstance(pkgs, list) and len(pkgs) > 0 and all(
        isinstance(p, dict) and PACKAGE_NAME.match(str(p.get("name", ""))) and isinstance(p.get("version"), str)
        for p in pkgs), "bad dependencies.packages")

    art = m["artifact"] if isinstance(m["artifact"], dict) else {}
    base = f"{m['product']}-{version}-{key}"
    need(art.get("name") == f"{base}.tar.gz", f"artifact.name must be {base}.tar.gz")
    need(art.get("root") == base, f"artifact.root must be {base}")
    need(art.get("format") == "tar+gzip", "artifact.format must be tar+gzip")
    need(bool(SHA256_HEX.match(str(art.get("sha256", "")))), "bad artifact.sha256")
    size = art.get("size")
    need(isinstance(size, int) and 0 < size <= MAX_ARTIFACT_BYTES, "artifact.size out of range")

    files = m["files"]
    if not isinstance(files, list) or not files:
        return errors + ["files must be a non-empty list"]
    paths = []
    for record in files:
        if not isinstance(record, dict):
            errors.append("file record is not an object")
            continue
        path = record.get("path")
        need(safe_relpath(path), f"unsafe file path {path!r}")
        need(bool(SHA256_HEX.match(str(record.get("sha256", "")))), f"bad sha256 for {path!r}")
        need(isinstance(record.get("size"), int) and 0 <= record["size"] <= MAX_FILE_BYTES, f"bad size for {path!r}")
        need(record.get("mode") in [f"{m_:04o}" for m_ in FILE_MODES], f"bad mode for {path!r}")
        paths.append(path)
    need(paths == sorted(paths) and len(set(paths)) == len(paths), "files must be sorted and unique")
    need("manifest.json" not in paths, "files must not list manifest.json")
    for required in REQUIRED_FILES:
        need(required in paths, f"required file missing: {required}")
    contents = m["contents"] if isinstance(m["contents"], dict) else {}
    need(contents.get("manifest_path") == "manifest.json", "contents.manifest_path must be manifest.json")
    need(bool(SHA256_HEX.match(str(contents.get("manifest_sha256", "")))), "bad contents.manifest_sha256")
    need(contents.get("file_count") == len(files), "contents.file_count mismatch")
    need(contents.get("total_size") == sum(r.get("size", 0) for r in files if isinstance(r, dict)),
         "contents.total_size mismatch")
    return errors


def read_members(artifact: Path, root: str) -> tuple[dict[str, bytes], list[str]]:
    """Read every regular member into memory without extracting; enforce archive safety."""
    errors: list[str] = []
    contents: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(artifact, mode="r:gz") as tar:
            for count, member in enumerate(tar, start=1):
                if count > MAX_FILES + 1000:
                    return contents, errors + ["too many archive members"]
                name = member.name
                if name in seen:
                    errors.append(f"duplicate member {name!r}")
                seen.add(name)
                if name != root and not name.startswith(root + "/"):
                    errors.append(f"member outside {root}/: {name!r}")
                    continue
                rel = name[len(root) + 1:]
                if name != root and not safe_relpath(rel):
                    errors.append(f"unsafe member path {name!r}")
                    continue
                if member.mode & ~0o777:
                    errors.append(f"special mode bits on {name!r}")
                if member.isdir():
                    continue
                if not member.isreg() or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
                    errors.append(f"member is not a regular file or directory: {name!r}")
                    continue
                if member.size > MAX_FILE_BYTES:
                    errors.append(f"member too large: {name!r}")
                    continue
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    return contents, errors + ["archive expands beyond the size limit"]
                handle = tar.extractfile(member)
                contents[rel] = handle.read() if handle else b""
                if f"{member.mode & 0o777:04o}" not in [f"{m:04o}" for m in FILE_MODES]:
                    errors.append(f"unexpected mode {member.mode:04o} on {name!r}")
    except (OSError, tarfile.TarError, EOFError, zlib.error) as exc:
        errors.append(f"cannot read archive: {exc}")
    return contents, errors


def verify_artifact(m: dict, artifact: Path) -> list[str]:
    errors: list[str] = []
    if not artifact.is_file() or artifact.is_symlink():
        return [f"artifact not found as a regular file: {artifact}"]
    size = artifact.stat().st_size
    if size != m["artifact"]["size"]:
        errors.append(f"artifact size {size} != manifest {m['artifact']['size']}")
    if size > MAX_ARTIFACT_BYTES:
        return errors + ["artifact exceeds the size limit"]
    if sha256_file(artifact) != m["artifact"]["sha256"]:
        return errors + ["artifact sha256 does not match the manifest"]

    contents, problems = read_members(artifact, m["artifact"]["root"])
    errors += problems
    inner_bytes = contents.pop("manifest.json", None)
    if inner_bytes is None:
        return errors + ["artifact has no manifest.json"]
    if sha256_bytes(inner_bytes) != m["contents"]["manifest_sha256"]:
        errors.append("inner manifest.json digest does not match contents.manifest_sha256")
    try:
        inner = json.loads(inner_bytes)
    except ValueError:
        return errors + ["inner manifest.json is not JSON"]
    if inner.get("files") != m["files"]:
        errors.append("inner manifest file list differs from the release manifest")
    for field in ("product", "version"):
        if inner.get(field) != m[field]:
            errors.append(f"inner manifest {field} differs")
    if inner.get("platform") != m["platform"]["key"]:
        errors.append("inner manifest platform differs")

    expected = {r["path"]: r for r in m["files"]}
    for rel in sorted(contents.keys() - expected.keys()):
        errors.append(f"unlisted file in artifact: {rel}")
    for rel in sorted(expected.keys() - contents.keys()):
        errors.append(f"listed file missing from artifact: {rel}")
    for rel, data in contents.items():
        record = expected.get(rel)
        if record and (sha256_bytes(data) != record["sha256"] or len(data) != record["size"]):
            errors.append(f"digest mismatch: {rel}")

    lock = contents.get("apps/api/requirements.release.txt", b"")
    if sha256_bytes(lock) != m["dependencies"]["lock_sha256"]:
        errors.append("dependency lock digest mismatch")
    try:
        info = json.loads(contents.get("BUILD_INFO.json", b"{}"))
    except ValueError:
        info = {}
    for field, value in (("product", m["product"]), ("version", m["version"]), ("platform", m["platform"]["key"]),
                         ("source_commit", m["source"]["commit"]), ("channel", m["channel"]),
                         ("source_tree_sha256", m["source"]["tree_sha256"]),
                         ("source_date_epoch", m["build"]["source_date_epoch"])):
        if info.get(field) != value:
            errors.append(f"BUILD_INFO.json {field} differs from the manifest")
    return errors


def cmd_verify(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        die(f"cannot read manifest: {exc}")
    try:
        errors = validate_manifest(manifest)
        if not errors:
            artifact = Path(args.artifact) if args.artifact else manifest_path.parent / manifest["artifact"]["name"]
            errors = verify_artifact(manifest, artifact)
    except (TypeError, KeyError, AttributeError) as exc:
        errors = [f"malformed manifest: {type(exc).__name__}"]
        manifest = manifest if isinstance(manifest, dict) else {}
    for expect, actual in ((args.expect_product, manifest.get("product")),
                           (args.expect_platform, (manifest.get("platform") or {}).get("key")),
                           (args.expect_version, manifest.get("version"))):
        if expect and expect != actual:
            errors.append(f"expected {expect!r}, manifest says {actual!r}")
    if errors:
        print("FAIL\n  " + "\n  ".join(errors))
        return 1
    print(f"OK {manifest['artifact']['name']} sha256 {manifest['artifact']['sha256']} "
          f"({manifest['contents']['file_count']} files, channel {manifest['channel']})")
    return 0


# --- content scan ------------------------------------------------------------------------

DEV_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", ".vite"}
RUNTIME_DIRS = {"runs", "logs", "quarantine", "project-outputs", "backups", ".mac-control", ".rcd-control",
                ".hermes", ".openclaw", ".codex", ".claude", ".config", ".ssh", ".gnupg", ".aws", ".docker",
                ".kube", ".local"}
SECRET_NAMES = {"vault.key", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "known_hosts", "authorized_keys",
                "hosts.yml", ".netrc", ".npmrc", ".pypirc", "auth.json", ".DS_Store", ".envrc"}
SECRET_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key", ".p12", ".pfx", ".der", ".kdbx",
                   ".token", ".pyc", ".map", ".bak", ".swp")
SECRET_NAME_PATTERNS = (
    re.compile(r"^\.env(\..+)?$"),
    re.compile(r"\.db-"),
    re.compile(r"^client_secret_.*\.json$"),
    re.compile(r"^google-oauth-client.*\.json$"),
    re.compile(r"^credentials.*\.json$"),
    re.compile(r"^tokens?(\.|_|-).*\.json$|^tokens?\.json$"),
)
CONTENT_RULES = (
    ("private-key", re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("github-token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})")),
    ("api-key-sk", re.compile(rb"\bsk-(?:ant-|proj-|or-v1-)?[A-Za-z0-9_-]{32,}")),
    ("aws-access-key", re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google-oauth-secret", re.compile(rb"\bGOCSPX-[A-Za-z0-9_-]{20,}")),
    ("google-api-key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(rb"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("telegram-bot-token", re.compile(rb"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b")),
    ("home-path", re.compile(rb"/(?:Users|home)/(?!(?:you|user|username|example|USER|runner|pi)/)[a-z_][a-z0-9_.-]{1,31}/")),
    ("lan-address", re.compile(rb"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?![\d.])")),
    ("tailnet-address", re.compile(rb"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?![\d.])|[a-z0-9-]+\.[a-z0-9-]+\.ts\.net\b")),
    # The domain is matched in lowercase, as addresses are written: minified bundles contain binary-like runs
    # ("eb@Wl'z@aPeb95Si.ebcp") that an any-case domain pattern reads as an address.
    ("email", re.compile(rb"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b)(?!users\.noreply\.github\.com\b)[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b")),
)


def host_identities(extra: list[str]) -> list[str]:
    """Strings that identify the build host or operator; never shipped in an artifact."""
    values = set(extra)
    try:
        values.add(getpass.getuser())
    except Exception:  # noqa: BLE001 - no user database entry
        pass
    hostname = socket.gethostname()
    values.update({hostname, hostname.split(".")[0]})
    values.update({str(Path.home()), str(REPO_ROOT), os.path.realpath(REPO_ROOT)})
    values.update(line.strip() for line in os.environ.get("RELEASE_SCAN_IDENTITIES", "").splitlines())
    return sorted(v for v in values if len(v) >= 4 and v not in {"root", "runner", "localhost", "/root"})


def load_scan_allowlist() -> list[dict]:
    """packaging/scan-allowlist.json: [{"path": ..., "rule": ..., "reason": ...}], each entry reviewed."""
    if not SCAN_ALLOWLIST_FILE.is_file():
        return []
    entries = json.loads(SCAN_ALLOWLIST_FILE.read_text())
    for entry in entries:
        if not (entry.get("path") and entry.get("rule") and entry.get("reason")):
            die(f"{SCAN_ALLOWLIST_FILE.name}: every entry needs path, rule and reason")
        if entry["rule"] in ("private-key", "github-token", "host-identity") or entry["rule"].startswith("path:"):
            die(f"{SCAN_ALLOWLIST_FILE.name}: rule {entry['rule']!r} cannot be allowlisted")
    return entries


def path_rule(rel: str) -> str | None:
    parts = rel.split("/")
    name = parts[-1]
    if any(p in DEV_DIRS for p in parts[:-1]):
        return "path:development-directory"
    if any(p in RUNTIME_DIRS for p in parts[:-1]):
        return "path:runtime-or-host-config-directory"
    if name == ".env.example":
        return None
    if name in SECRET_NAMES or name.endswith(SECRET_SUFFIXES) or any(p.search(name) for p in SECRET_NAME_PATTERNS):
        return "path:secret-or-runtime-file"
    return None


def scan_contents(contents: dict[str, bytes], identities: list[str]) -> list[str]:
    allow = {(e["path"], e["rule"]) for e in load_scan_allowlist()}
    identity_bytes = [(v, v.encode()) for v in identities]
    findings = []
    for rel in sorted(contents):
        rule = path_rule(rel)
        if rule:
            findings.append(f"{rel}: {rule}")
        data = contents[rel]
        for name, pattern in CONTENT_RULES:
            match = pattern.search(data)
            if match and (rel, name) not in allow:
                line = data.count(b"\n", 0, match.start()) + 1
                findings.append(f"{rel}:{line}: {name} (value withheld)")
        for _value, needle in identity_bytes:
            index = data.find(needle)
            if index >= 0:
                line = data.count(b"\n", 0, index) + 1
                findings.append(f"{rel}:{line}: host-identity (value withheld)")
                break
    return findings


def run_gitleaks(contents: dict[str, bytes], mode: str) -> list[str]:
    gitleaks = shutil.which("gitleaks")
    if mode == "off" or (mode == "auto" and not gitleaks):
        return []
    if not gitleaks:
        return ["gitleaks requested but not installed"]
    with tempfile.TemporaryDirectory(prefix="release-scan-") as tmp:
        root = Path(tmp) / "tree"
        for rel, data in contents.items():  # paths were validated by read_members
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        report = Path(tmp) / "gitleaks.json"
        cmd = [gitleaks, "dir", "--no-banner", "--redact", "--exit-code", "1",
               "--report-format", "json", "--report-path", str(report), str(root)]
        config = REPO_ROOT / ".gitleaks.toml"
        if config.is_file():
            cmd[2:2] = ["--config", str(config)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return []
        if result.returncode != 1 or not report.is_file():
            return [f"gitleaks failed to run (exit {result.returncode})"]
        leaks = json.loads(report.read_text() or "[]")
        return [f"{Path(leak.get('File', '?')).relative_to(root) if leak.get('File', '').startswith(str(root)) else leak.get('File')}"
                f":{leak.get('StartLine', '?')}: gitleaks {leak.get('RuleID', '?')} (redacted)" for leak in leaks]


def scan_artifact(artifact: Path, identities: list[str], gitleaks_mode: str = "auto") -> list[str]:
    root = artifact.name.removesuffix(".rejected").removesuffix(".tar.gz")
    contents, problems = read_members(artifact, root)
    if problems:
        return problems
    return scan_contents(contents, identities) + run_gitleaks(contents, gitleaks_mode)


def cmd_scan(args: argparse.Namespace) -> int:
    findings = scan_artifact(Path(args.artifact), host_identities(args.identity or []), args.gitleaks)
    if findings:
        print("FAIL\n  " + "\n  ".join(findings))
        return 1
    print(f"CLEAN {Path(args.artifact).name}")
    return 0


# --- CLI -----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    lock = sub.add_parser("lock", help="resolve hash-pinned runtime locks per platform (needs uv + PyPI)")
    lock.add_argument("--platform")
    lock.add_argument("--exclude-newer", help="ignore packages uploaded after this RFC 3339 timestamp")
    lock.set_defaults(func=cmd_lock)

    for name, func, default_out in (("build", cmd_build, "dist-release"), ("repro", cmd_repro, "dist-release/repro")):
        p = sub.add_parser(name, help="build the artifact" if name == "build" else "build twice and compare digests")
        p.add_argument("--platform")
        p.add_argument("--out", default=str(REPO_ROOT / default_out))
        p.add_argument("--dev", action="store_true",
                       help="allow a dirty or unversioned source tree; the artifact is marked channel=dev")
        p.add_argument("--skip-web-build", action="store_true", help="package the existing apps/web/dist")
        p.add_argument("--source-date-epoch", type=int)
        p.add_argument("--force", action="store_true", help="overwrite an existing artifact in --out")
        p.add_argument("--gitleaks", choices=("auto", "on", "off"), default="auto")
        p.set_defaults(func=func)

    verify = sub.add_parser("verify", help="validate a release manifest and its artifact")
    verify.add_argument("manifest")
    verify.add_argument("--artifact")
    verify.add_argument("--expect-product", choices=("mcd", "rcd"))
    verify.add_argument("--expect-platform", choices=sorted(PLATFORM_OS_ARCH))
    verify.add_argument("--expect-version", help="exact version the manifest must carry, e.g. the release tag without v")
    verify.set_defaults(func=cmd_verify)

    scan = sub.add_parser("scan", help="scan an artifact for secrets, runtime data and host identities")
    scan.add_argument("artifact")
    scan.add_argument("--identity", action="append", help="extra identifying string to forbid (repeatable)")
    scan.add_argument("--gitleaks", choices=("auto", "on", "off"), default="auto")
    scan.set_defaults(func=cmd_scan)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
