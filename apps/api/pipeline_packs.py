"""Pipeline packs: optional, data-only add-ons that teach the planner a kind of deliverable for one service (for example a upubhub class).

A pack is JSON and Markdown only: a `pack.json`, project types in the same schema as packs/project-types/, and short format guides.
Nothing in a pack runs. Checks and service connectors are app code a pack names; a name this dashboard does not have makes the pack
unusable with a plain reason, never half-used.

Packs come from the public packs repository's latest GitHub release: one signed index (`pipeline-packs.json` plus its `.sig`, signed
with the same dashboard-release key as app updates) lists each pack archive with its sha256. An install verifies the index signature
against the release public key below, then the archive digest, then every file, before anything is written. The key ships inside this
file, which the installed dashboard already verified, so packs check the same way on an install that pins release digests (MCD) as on
one that checks signatures (RCD). Installed packs live
in <data>/packs/<id>/<version>/ with <data>/packs/<id>/active naming the version in use; the operator's own project types still win.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

PACKS_REPOSITORY = "gptkiosk/dashboard-pipeline-packs"
INDEX_ASSET = "pipeline-packs.json"
FORMAT = ("dashboard-pipeline-pack", "0.1")
INDEX_FORMAT = ("dashboard-pipeline-pack-index", "0.1")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
VERSION_RE = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")            # a tool a template requires, as in the store's platform/tools.json
REQUIRE_KINDS = ("agents", "system_tools", "providers", "checks", "services")
GUIDE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.md$")
MAX_FILE_BYTES = 40_000
MAX_FILES = 40
MAX_ARCHIVE_BYTES = 1_000_000
MAX_INDEX_BYTES = 256 * 1024
# What a pack may name. Grows as the app learns checks and connectors; a pack naming anything else waits for a newer dashboard.
# packaging/allowed_signers; a test keeps the two identical.
RELEASE_SIGNER = ('dashboard-release namespaces="dashboard-release" ssh-ed25519 '
                  'AAAAC3NzaC1lZDI1NTE5AAAAINrWOiSyq/L4xNRGHAf7s8ZujXlun9TnuRHJ9X25Ef2z dashboard-release')
RELEASE_IDENTITY = "dashboard-release"
KNOWN_CHECKS: frozenset[str] = frozenset({"course-package"})
KNOWN_CONNECTORS: frozenset[str] = frozenset()


class PackError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(x) for x in value.split("."))


def validate(files: dict[str, bytes], app_version: str) -> tuple[dict, list[str]]:
    """Check a pack's files (relative path -> bytes). Returns its manifest and every problem found, so one review lists them all."""
    import project_types
    import profiles
    import standards
    problems: list[str] = []
    if len(files) > MAX_FILES:
        problems.append(f"A pack holds at most {MAX_FILES} files.")
    for rel, data in files.items():
        if len(data) > MAX_FILE_BYTES:
            problems.append(f"{rel} is larger than {MAX_FILE_BYTES // 1000} KB.")
        top, _, name = rel.partition("/")
        allowed = rel == "pack.json" or (top == "project-types" and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}\.json", name)) \
            or (top == "guides" and GUIDE_RE.fullmatch(name))
        if not allowed:
            problems.append(f"{rel} is not a file a pack may contain (pack.json, project-types/<id>.json, guides/<name>.md).")
    try:
        manifest = json.loads(files["pack.json"].decode("utf-8"))
    except KeyError:
        return {}, problems + ["The pack has no pack.json."]
    except (ValueError, UnicodeError):
        return {}, problems + ["pack.json is not valid JSON."]
    if not isinstance(manifest, dict):
        return {}, problems + ["pack.json must be an object."]
    if (manifest.get("format"), manifest.get("version")) != FORMAT:
        problems.append("pack.json is not a dashboard-pipeline-pack 0.1 manifest.")
    if not ID_RE.fullmatch(str(manifest.get("id", ""))):
        problems.append("The pack id must be lowercase letters, digits and dashes.")
    if not VERSION_RE.fullmatch(str(manifest.get("pack_version", ""))):
        problems.append("pack_version must look like 1.2.3.")
    if not isinstance(manifest.get("label"), str) or not manifest.get("label", "").strip():
        problems.append("The pack needs a label.")
    app_min = str(manifest.get("app_min", "0.0.0"))
    if not VERSION_RE.fullmatch(app_min):
        problems.append("app_min must look like 1.2.3.")
    elif _version_tuple(app_min) > _version_tuple(app_version.split("-")[0].split("+")[0]):
        problems.append(f"This pack needs dashboard {app_min} or newer; this one is {app_version}.")
    service = manifest.get("service")
    if service is not None:
        if not isinstance(service, dict) or not ID_RE.fullmatch(str(service.get("id", ""))) or not isinstance(service.get("label"), str):
            problems.append("service needs an id and a label.")
        elif service.get("credential") and service["credential"] not in profiles.PROVIDERS:
            problems.append(f"This pack needs a {service['credential']} credential, which this dashboard cannot store yet. Update the dashboard.")
    lists = {}
    for key in ("project_types", "guides", "general_guides", "checks", "connectors"):
        value = manifest.get(key, [])
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            problems.append(f"{key} must be a list of names.")
            value = []
        lists[key] = value
    if not lists["project_types"]:
        problems.append("A pack must provide at least one project type.")
    for type_id in lists["project_types"]:
        data = files.get(f"project-types/{type_id}.json")
        if data is None:
            problems.append(f"project-types/{type_id}.json is missing.")
            continue
        try:
            t = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeError):
            problems.append(f"project-types/{type_id}.json is not valid JSON.")
            continue
        if not isinstance(t, dict) or t.get("id") != type_id or not project_types._valid(t):
            problems.append(f"project-types/{type_id}.json is not a usable project type.")
        elif any(g not in standards.GUIDES and g not in lists["guides"] for g in t.get("guides", [])):
            problems.append(f"project-types/{type_id}.json names a guide the pack does not include.")
    extra_types = {rel for rel in files if rel.startswith("project-types/")} - {f"project-types/{t}.json" for t in lists["project_types"]}
    if extra_types:
        problems.append("Every project type file must be listed in project_types: " + ", ".join(sorted(extra_types)) + ".")
    for name in lists["guides"]:
        if not GUIDE_RE.fullmatch(name) or f"guides/{name}" not in files:
            problems.append(f"guides/{name} is missing.")
        elif name in standards.GUIDES:
            problems.append(f"{name} would replace a shipped guide; give it its own name.")
    bad_general = [g for g in lists["general_guides"] if g not in standards.GUIDES]
    if bad_general:
        problems.append("general_guides may only name shipped guides: " + ", ".join(bad_general) + ".")
    unknown = [c for c in lists["checks"] if c not in KNOWN_CHECKS] + [c for c in lists["connectors"] if c not in KNOWN_CONNECTORS]
    if unknown:
        problems.append("This pack uses features this dashboard does not have yet (" + ", ".join(unknown) + "). Update the dashboard.")
    return manifest, problems


# ------------------------------------------------------------------------------------------------ installed packs


def root(settings) -> Path:
    return Path(settings.data_dir) / "packs"


def _active_version(folder: Path) -> str | None:
    try:
        value = (folder / "active").read_text("utf-8").strip()
    except OSError:
        return None
    return value if VERSION_RE.fullmatch(value) else None


def installed(settings) -> list[dict]:
    """Installed packs whose active version is still valid on disk: manifest, folder and version."""
    out = []
    base = root(settings) if settings is not None else None
    if base is None or not base.is_dir():
        return out
    for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink() and ID_RE.fullmatch(p.name)):
        version = _active_version(folder)
        path = folder / version if version else None
        if path is None or not path.is_dir() or path.is_symlink():
            continue
        try:
            manifest = json.loads((path / "pack.json").read_text("utf-8"))
        except (OSError, ValueError, UnicodeError):
            continue
        if isinstance(manifest, dict) and manifest.get("id") == folder.name and manifest.get("pack_version") == version:
            out.append({"manifest": manifest, "path": path, "version": version})
    return out


def type_dirs(settings) -> list[Path]:
    return [p["path"] / "project-types" for p in installed(settings)]


def guide_path(name: str, settings) -> Path | None:
    """The installed pack file for a pack guide, or None when no active pack declares it."""
    for pack in installed(settings):
        if name in pack["manifest"].get("guides", []) and GUIDE_RE.fullmatch(name):
            path = pack["path"] / "guides" / name
            if path.is_file() and not path.is_symlink():
                return path
    return None


def general_guides_for(type_id: str, settings) -> list[str] | None:
    """The general guides a pack chose for one of its types (replacing the software ones), or None to keep the default."""
    for pack in installed(settings):
        m = pack["manifest"]
        if type_id in m.get("project_types", []) and isinstance(m.get("general_guides"), list):
            return list(m["general_guides"])
    return None


def checks_for(type_id: str, settings) -> list[str]:
    """The named checks an installed pack runs for one of its project types (for example course-package)."""
    for pack in installed(settings):
        m = pack["manifest"]
        if type_id in m.get("project_types", []):
            return [c for c in m.get("checks", []) if c in KNOWN_CHECKS]
    return []


def install(settings, files: dict[str, bytes], app_version: str) -> dict:
    """Validate and install one pack version, then make it active. The previous version stays on disk for a rollback."""
    manifest, problems = validate(files, app_version)
    if problems:
        raise PackError(" ".join(problems))
    folder = root(settings) / manifest["id"]
    target = folder / manifest["pack_version"]
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".install-", dir=folder))
    try:
        for rel, data in files.items():
            path = staging / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    tmp = folder / "active.tmp"
    tmp.write_text(manifest["pack_version"] + "\n", "utf-8")
    os.replace(tmp, folder / "active")
    return manifest


def remove(settings, pack_id: str) -> None:
    if not ID_RE.fullmatch(pack_id):
        raise PackError("Unknown pack.", 404)
    folder = root(settings) / pack_id
    if not folder.is_dir() or folder.is_symlink():
        raise PackError("That pack is not installed.", 404)
    shutil.rmtree(folder)


# ------------------------------------------------------------------------------------------------ the signed index and archives


def read_archive(data: bytes) -> dict[str, bytes]:
    """A pack archive's files. Regular files only, no links or absolute or parent paths, within the size limits; one top folder allowed."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise PackError("The pack archive is too large.")
    try:
        raw = gzip.decompress(data)
    except (OSError, EOFError):
        raise PackError("The pack archive is not a gzip file.") from None
    if len(raw) > 4 * MAX_ARCHIVE_BYTES:
        raise PackError("The pack archive expands too far.")
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
            for member in tar.getmembers():
                if member.isdir():
                    continue
                if not member.isfile():
                    raise PackError(f"{member.name} is not a regular file.")
                name = member.name.removeprefix("./")
                if name.startswith("/") or ".." in name.split("/"):
                    raise PackError(f"{member.name} is outside the pack.")
                handle = tar.extractfile(member)
                files[name] = handle.read(MAX_FILE_BYTES + 1) if handle else b""
    except tarfile.TarError:
        raise PackError("The pack archive could not be read.") from None
    tops = {n.split("/", 1)[0] for n in files if "/" in n} | {n for n in files if "/" not in n}
    if "pack.json" not in files and len(tops) == 1:
        prefix = tops.pop() + "/"
        files = {n.removeprefix(prefix): d for n, d in files.items()}
    return files


def parse_index(data: bytes) -> list[dict]:
    try:
        index = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise PackError("The pack index is not valid JSON.") from None
    if not isinstance(index, dict) or (index.get("format"), index.get("version")) != INDEX_FORMAT or not isinstance(index.get("packs"), list):
        raise PackError("The pack index is not a dashboard-pipeline-pack-index 0.1 file.")
    packs = []
    for entry in index["packs"]:
        if not isinstance(entry, dict) or not ID_RE.fullmatch(str(entry.get("id", ""))) or not VERSION_RE.fullmatch(str(entry.get("pack_version", ""))) \
                or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))) or entry.get("archive") != f"{entry.get('id')}-{entry.get('pack_version')}.tar.gz":
            continue
        item = {k: entry.get(k) for k in ("id", "pack_version", "label", "summary", "service", "archive", "sha256", "app_min")}
        # Store fields (template store 1.0). The index is signed, but keep only the expected shapes so the page shows nothing else.
        item["author"] = entry["author"] if isinstance(entry.get("author"), str) and re.fullmatch(r"[A-Za-z0-9-]{1,39}", entry["author"]) else None
        item["trust"] = entry.get("trust") if entry.get("trust") in ("official", "community") else None
        requires = entry.get("requires") if isinstance(entry.get("requires"), dict) else {}
        item["requires"] = {k: [x for x in v if isinstance(x, str) and NAME_RE.fullmatch(x)][:12] for k, v in requires.items()
                            if k in REQUIRE_KINDS and isinstance(v, list)}
        item["settings"] = [x[:100] for x in entry.get("settings", []) if isinstance(x, str)][:40] if isinstance(entry.get("settings"), list) else []
        packs.append(item)
    return packs


def parse_tools(data: bytes) -> dict[str, list[dict]]:
    """The approved tools the signed index lists, by kind, as the store's Tools tab shows them."""
    try:
        tools = json.loads(data.decode("utf-8")).get("tools")
    except (ValueError, UnicodeError, AttributeError):
        return {}
    out = {}
    for kind in REQUIRE_KINDS:
        rows = tools.get(kind) if isinstance(tools, dict) and isinstance(tools.get(kind), list) else []
        out[kind] = [{"id": t["id"], "name": str(t.get("name") or t["id"])[:80], "description": str(t.get("description") or "")[:400],
                      "app_min": t.get("app_min") if VERSION_RE.fullmatch(str(t.get("app_min", ""))) else None}
                     for t in rows if isinstance(t, dict) and isinstance(t.get("id"), str) and NAME_RE.fullmatch(t["id"])][:60]
    return out


def verify_archive(entry: dict, data: bytes) -> dict[str, bytes]:
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise PackError("The downloaded pack does not match the signed index. Nothing was installed.")
    files = read_archive(data)
    try:
        manifest = json.loads(files.get("pack.json", b"{}").decode("utf-8"))
    except (ValueError, UnicodeError):
        manifest = {}
    if manifest.get("id") != entry["id"] or manifest.get("pack_version") != entry["pack_version"]:
        raise PackError("The pack's own manifest does not match the signed index. Nothing was installed.")
    return files


def _fetch_config(**overrides):
    import release_fetch as rf
    return rf.FetchConfig(product="pipeline-packs", platform="any", inbox=Path(tempfile.gettempdir()), **overrides)


def _get(cfg, url: str, accept: str, limit: int, opener=None) -> bytes:
    import time
    import release_fetch as rf
    try:
        return rf._read_capped(rf._request(cfg, url, accept, opener), limit, time.monotonic() + cfg.limits.total_seconds)
    except rf.FetchError as exc:
        raise PackError(f"Could not reach the packs repository: {exc}", 502) from None


def _authenticator(signer: str):
    import release_verify as rv
    folder = Path(tempfile.mkdtemp(prefix="pack-signers-"))
    path = folder / "allowed_signers"
    path.write_text(signer + "\n", "utf-8")
    path.chmod(0o600)
    return rv.SshSignature(path, RELEASE_IDENTITY), folder


def available(opener=None, signer: str = RELEASE_SIGNER, **overrides) -> dict:
    """The packs in the latest release of the packs repository, from its signed index, checked against the dashboard release key."""
    import release_verify as rv
    cfg = _fetch_config(**overrides)
    try:
        release = json.loads(_get(cfg, f"{cfg.api_base}/repos/{PACKS_REPOSITORY}/releases/latest", "application/vnd.github+json", 1_000_000, opener))
    except ValueError:
        raise PackError("The packs repository answered with something that is not a release.", 502) from None
    assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets", []) if isinstance(a, dict)} if isinstance(release, dict) else {}
    if INDEX_ASSET not in assets or INDEX_ASSET + ".sig" not in assets:
        raise PackError("The latest packs release has no signed index.", 502)
    index = _get(cfg, assets[INDEX_ASSET], "application/octet-stream", MAX_INDEX_BYTES, opener)
    signature = _get(cfg, assets[INDEX_ASSET + ".sig"], "application/octet-stream", 16 * 1024, opener)
    authenticate, keys = _authenticator(signer)
    try:
        authenticate(index, signature)
    except rv.AuthenticityError as exc:
        raise PackError(f"The pack index is not signed by the dashboard release key ({exc}). Nothing was listed.", 502) from None
    finally:
        shutil.rmtree(keys, ignore_errors=True)
    packs = parse_index(index)
    for entry in packs:
        entry["url"] = assets.get(entry["archive"])
    return {"release": str(release.get("tag_name") or ""), "packs": [p for p in packs if p["url"]], "tools": parse_tools(index)}


def download_and_install(settings, entry: dict, app_version: str, opener=None, **overrides) -> dict:
    """Install one pack from a signed listing entry: download, check its digest against the index, validate, then write."""
    data = _get(_fetch_config(**overrides), entry["url"], "application/octet-stream", MAX_ARCHIVE_BYTES, opener)
    return install(settings, verify_archive(entry, data), app_version)
