"""Agent tools installer engine: installs the agent CLIs per user, with no sudo, from pinned sources.

Standard library only and independent of the rest of the app (like update_engine), so the host
helper (tool_install_helper.py) can run it outside the service and the API can read the same
state and build the same plan the helper will run.

What it installs is named in tool_catalog.json, which lives in the repository and ships in the
release. Every source in it is pinned and hash-locked:

    npm-lock        a committed package.json + package-lock.json per tool, installed with `npm ci`
                    (integrity hashes for every package) and `--ignore-scripts`; only the
                    lifecycle scripts the catalog names are run afterwards
    archive         a release archive (Node.js, uv) from an allowlisted host, checked against the
                    sha256 in the catalog and, for Node.js, against nodejs.org's SHASUMS256.txt
    pinned-script   an installer script fetched at a pinned commit and checked against its sha256,
                    run with `--commit` so the code it installs is the pinned commit

Layout under one tools root (owner-only, no symlinked components):

    tools/<id>/versions/<version>-<fingerprint12>/   immutable once its receipt is written
    tools/<id>/current  -> versions/<vid>           what the wrappers run
    tools/<id>/previous -> versions/<vid>           what Roll back flips to
    bin/<name>                                       one small wrapper per command, never changed by a flip
    tmp/ cache/                                      downloads and the shared package cache
    state/tools.json  state/lock  state/history.jsonl  state/receipts/<tx>.json  state/helper.log

Rules, enforced here and not by the callers:
  * nothing is installed outside the tools root, except one file the plan names (the Hermes data
    folder's uv, only when none is there) and the data folders the tools create themselves;
  * no sudo: system packages are only ever shown as a command for the operator to run, and the helper
    process sets no_new_privs so an installer script cannot gain privileges even with passwordless sudo;
  * nothing signs in, reads a key, or touches dispatch, billing or free-only settings;
  * `current` only ever points at a version whose own check passed;
  * every operation is journalled, so a killed helper is cleaned up on the next call.

The same engine serves MCD: a platform is a key in the catalog (`linux-arm64` today), the installers
are a registry keyed by name, and everything platform-specific (archive URLs, commands) is catalog data.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

CATALOG_SCHEMA = "dashboard-tool-catalog/v1"
STATE_SCHEMA = "dashboard-tool-state/v1"
RECEIPT_SCHEMA = "dashboard-tool-receipt/v1"
PLAN_SCHEMA = "dashboard-tool-plan/v1"
VERSION_RECEIPT = ".tool-receipt.json"
WRAPPER_MARK = "# rcd-agent-tools wrapper for"

ACTIONS = ("install", "update", "remove", "rollback")
COMPONENT_ID = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
BIN_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")
VID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,95}$")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
REL_PATH = re.compile(r"^[A-Za-z0-9_@][A-Za-z0-9_@.+/-]{0,200}$")
PLAIN_PATH = re.compile(r"^/[A-Za-z0-9._/+:-]{1,900}$")  # paths end up inside wrapper scripts
PLATFORM_KEY = re.compile(r"^[a-z]+-[a-z0-9_]+$")
SYSTEM_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,40}$")
ALLOWED_HOSTS = frozenset({
    "nodejs.org", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com", "raw.githubusercontent.com", "x.ai", "storage.googleapis.com",
})
INSTALLERS = ("archive", "npm-lock", "pinned-script", "binary")
CATALOG_KEYS = {"schema", "checked", "requirements", "system_packages", "runtimes", "tools"}
REQUIREMENT_KEYS = {"platforms", "min_free_disk_mb", "disk_headroom_mb", "warn_ram_mb", "warn_available_ram_mb"}
COMPONENT_KEYS = {"name", "installer", "version", "size_mb", "note", "archive", "bins", "check", "package",
                  "lock_dir", "lock", "allow_scripts", "requires", "login", "system_packages", "repository", "tag",
                  "commit", "script", "script_args", "binary", "peak_ram_mb", "external_state", "system_packages_note"}
MAX_CATALOG_BYTES = 256 * 1024
MAX_STATE_BYTES = 256 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
MAX_SHASUMS_BYTES = 512 * 1024
HISTORY_MAX_BYTES = 256 * 1024
LOG_MAX_BYTES = 2 * 1024 * 1024
MAX_EXTRACT_MEMBERS = 200_000
MAX_EXTRACT_BYTES = 2 * 1024 ** 3
CHUNK = 64 * 1024
KEEP_VERSIONS = 2  # current and previous
RUN_TIMEOUTS = {"npm-ci": 1800, "script": 3000, "script-step": 600, "check": 90}
UNCHANGED = (
    "Dispatch routes and the free-only setting",
    "Billing mode and prices",
    "Sign-in: nothing is signed in and no key is read or stored",
    "The dashboard service and its data",
)


class ToolError(Exception):
    """The operation was refused or failed. `problems` lists every reason found."""

    def __init__(self, problems: list[str] | str):
        self.problems = [problems] if isinstance(problems, str) else (list(problems) or ["refused"])
        super().__init__("; ".join(self.problems))


# --- configuration ---------------------------------------------------------------------


@dataclass(frozen=True)
class ToolsConfig:
    root: Path
    catalog_dir: Path
    platform_key: str
    home: Path
    product: str = "rcd"

    @property
    def tools(self) -> Path:
        return self.root / "tools"

    @property
    def bin(self) -> Path:
        return self.root / "bin"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    @property
    def sandbox(self) -> Path:
        return self.root / "sandbox"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def hermes_home(self) -> Path:
        # Vendor installer state is separate from native account/configuration data.
        return self.root / "hermes-install-home"

    @property
    def native_hermes_home(self) -> Path:
        return self.home / ".hermes"

    def comp_dir(self, cid: str) -> Path:
        return self.tools / cid

    def version_dir(self, cid: str, vid: str) -> Path:
        return self.tools / cid / "versions" / vid


def config_problems(cfg: ToolsConfig) -> list[str]:
    problems = []
    if not PLAIN_PATH.match(str(cfg.root)):
        problems.append("the tools root must be an absolute path of letters, digits and ._/+:- only")
    if not PLAIN_PATH.match(str(cfg.home)):
        problems.append("the home folder path must be plain letters, digits and ._/+:- only")
    if not PLATFORM_KEY.match(cfg.platform_key):
        problems.append("bad platform key")
    return problems


def check_private_dir(path: Path, create: bool = False) -> None:
    """A real directory (not a symlink) owned by this user and not writable by others."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        if not create:
            raise ToolError(f"{path} does not exist") from None
        os.mkdir(path, 0o700)
        st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise ToolError(f"{path} is not a real directory")
    if st.st_uid != os.geteuid() or st.st_mode & 0o022:
        raise ToolError(f"{path} must be owned by this user and not writable by group or others")


def prepare_layout(cfg: ToolsConfig) -> None:
    problems = config_problems(cfg)
    if problems:
        raise ToolError(problems)
    parent = cfg.root.parent
    if not parent.is_dir():
        # A fresh home has no ~/.local/share yet; create the missing folders, but only inside the user's home.
        if os.path.commonpath([str(parent), str(cfg.home)]) != str(cfg.home):
            raise ToolError(f"{parent} does not exist")
        os.makedirs(parent, mode=0o755, exist_ok=True)
    check_private_dir(cfg.root, create=True)
    for sub in (cfg.tools, cfg.bin, cfg.tmp, cfg.sandbox, cfg.cache, cfg.state_dir, cfg.state_dir / "receipts"):
        check_private_dir(sub, create=True)


# --- catalog ---------------------------------------------------------------------------


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def strict_json(data: bytes, what: str):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ToolError(f"{what} is not valid JSON ({exc})") from None


def read_regular(path: Path, limit: int, what: str) -> bytes:
    """Bytes of a regular, non-symlink file no larger than `limit`."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        raise ToolError(f"{what} could not be opened ({type(exc).__name__})") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise ToolError(f"{what} is not a regular file of at most {limit} bytes")
        with os.fdopen(fd, "rb", closefd=False) as fh:
            data = fh.read(limit + 1)
    finally:
        os.close(fd)
    if len(data) > limit:
        raise ToolError(f"{what} is larger than {limit} bytes")
    return data


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def url_problem(url: object) -> str | None:
    if not isinstance(url, str):
        return "URL is not a string"
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return f"malformed URL {url[:60]!r}"
    if parts.scheme != "https" or port not in (None, 443):
        return f"URL must be plain https: {url[:80]}"
    if parts.username or parts.password or parts.query or parts.fragment:
        return f"URL must not carry credentials, a query or a fragment: {url[:80]}"
    if (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        return f"host {(parts.hostname or '')[:60]!r} is not on the download allowlist"
    return None


def lock_problems(lock: object) -> list[str]:
    """A package-lock.json is hash-locked when every package that is fetched has a sha512 integrity and a registry URL.
    Packages bundled inside another package's tarball are covered by that tarball's integrity."""
    if not isinstance(lock, dict) or type(lock.get("lockfileVersion")) is not int or lock["lockfileVersion"] < 3 \
            or not isinstance(lock.get("packages"), dict):
        return ["package-lock.json must be lockfileVersion 3 with a packages table"]
    out = []
    for name, entry in lock["packages"].items():
        if not name or not isinstance(entry, dict) or entry.get("inBundle") is True:
            continue
        if entry.get("link") is True or not str(entry.get("integrity", "")).startswith("sha512-") \
                or not str(entry.get("resolved", "")).startswith("https://registry.npmjs.org/"):
            out.append(f"{name} is not locked to a registry tarball with a sha512 integrity")
    return out[:5]


def _rel_ok(value: object) -> bool:
    return (isinstance(value, str) and REL_PATH.match(value) is not None and ".." not in value.split("/")
            and not value.startswith("/") and "//" not in value)


def catalog_problems(raw: object, catalog_dir: Path | None = None) -> list[str]:
    """Every reason this catalog is not safe to use. With `catalog_dir`, the lock files are hashed too."""
    if not isinstance(raw, dict):
        return ["catalog is not an object"]
    problems: list[str] = []
    need = lambda ok, why: ok or problems.append(why)  # noqa: E731
    need(set(raw) <= CATALOG_KEYS, f"unknown catalog keys: {sorted(set(raw) - CATALOG_KEYS)}")
    need(raw.get("schema") == CATALOG_SCHEMA, f"schema must be {CATALOG_SCHEMA}")
    req = raw.get("requirements")
    if not isinstance(req, dict) or set(req) != REQUIREMENT_KEYS:
        problems.append(f"requirements must have exactly {sorted(REQUIREMENT_KEYS)}")
    else:
        need(isinstance(req["platforms"], list) and req["platforms"]
             and all(isinstance(p, str) and PLATFORM_KEY.match(p) for p in req["platforms"]), "bad platforms list")
        for key in sorted(REQUIREMENT_KEYS - {"platforms"}):
            need(type(req[key]) is int and 0 < req[key] < 10 ** 6, f"requirements.{key} must be a positive integer")
    packages = raw.get("system_packages")
    if not isinstance(packages, dict):
        problems.append("system_packages must be an object")
        packages = {}
    for name, info in packages.items():
        need(SYSTEM_PACKAGE.match(str(name)) is not None, f"bad system package name {name!r}")
        need(isinstance(info, dict) and set(info) == {"why", "commands"} and isinstance(info.get("why"), str)
             and isinstance(info.get("commands"), list) and info["commands"]
             and all(isinstance(c, str) and BIN_NAME.match(c.replace("+", "p")) for c in info["commands"]),
             f"system package {name!r} needs why and commands")
    runtimes, tools = raw.get("runtimes"), raw.get("tools")
    if not isinstance(runtimes, dict) or not isinstance(tools, dict):
        problems.append("runtimes and tools must be objects")
        return problems
    need(not set(runtimes) & set(tools), "a runtime and a tool share an id")
    platforms = req.get("platforms", []) if isinstance(req, dict) else []
    for cid, comp in {**runtimes, **tools}.items():
        runtime = cid in runtimes
        where = f"{'runtime' if runtime else 'tool'} {cid}"
        need(COMPONENT_ID.match(str(cid)) is not None, f"{where}: bad id")
        if not isinstance(comp, dict):
            problems.append(f"{where} is not an object")
            continue
        need(set(comp) <= COMPONENT_KEYS, f"{where}: unknown keys {sorted(set(comp) - COMPONENT_KEYS)}")
        installer = comp.get("installer")
        need(installer in INSTALLERS, f"{where}: unknown installer {installer!r}")
        need(runtime == (installer == "archive"), f"{where}: runtimes use the archive installer and tools do not")
        need(isinstance(comp.get("name"), str) and 0 < len(comp["name"]) <= 60, f"{where}: needs a name")
        need(isinstance(comp.get("version"), str) and VERSION.match(comp["version"]), f"{where}: bad version")
        need(type(comp.get("size_mb")) is int and 0 < comp["size_mb"] < 100_000, f"{where}: size_mb must be a positive integer")
        check = comp.get("check")
        need(isinstance(check, dict) and set(check) == {"argv", "expect"} and isinstance(check.get("argv"), list)
             and check["argv"] and all(isinstance(a, str) and 0 < len(a) < 80 for a in check["argv"])
             and isinstance(check.get("expect"), str) and check["expect"], f"{where}: check needs argv and expect")
        names = []
        bins = comp.get("bins")
        if not isinstance(bins, list):
            problems.append(f"{where}: bins must be a list")
            bins = []
        for entry in bins:
            ok = (isinstance(entry, dict) and set(entry) <= {"name", "argv", "env_unset"}
                  and isinstance(entry.get("name"), str) and BIN_NAME.match(entry["name"])
                  and isinstance(entry.get("argv"), list) and entry["argv"] and all(_rel_ok(a) for a in entry["argv"])
                  and all(isinstance(v, str) and re.fullmatch(r"[A-Z_]{1,40}", v) for v in entry.get("env_unset", [])))
            need(ok, f"{where}: bad bins entry")
            if ok:
                names.append(entry["name"])
        need(len(names) == len(set(names)), f"{where}: duplicate command names")
        need(bool(names) == (not runtime), f"{where}: a tool needs at least one command and a runtime none")
        if runtime:
            archive = comp.get("archive")
            if not isinstance(archive, dict):
                problems.append(f"{where}: archive must map platform keys to archives")
                archive = {}
            for plat in platforms:
                need(plat in archive, f"{where}: no archive for platform {plat}")
            for plat, a in archive.items():
                need(plat in platforms, f"{where}: archive for undeclared platform {plat}")
                ok = (isinstance(a, dict) and set(a) <= {"url", "sha256", "size", "format", "root", "shasums_url"}
                      and a.get("format") in ("tar.xz", "tar.gz") and _rel_ok(a.get("root"))
                      and isinstance(a.get("sha256"), str) and SHA256.match(a["sha256"])
                      and type(a.get("size")) is int and 0 < a["size"] < 2 * 1024 ** 3)
                need(ok, f"{where}: bad archive entry for {plat}")
                if isinstance(a, dict):
                    for key in ("url", "shasums_url"):
                        if key in a:
                            why = url_problem(a[key])
                            need(why is None, f"{where}: {why}")
                    need("url" in a, f"{where}: archive needs a url")
        else:
            requires = comp.get("requires")
            need(isinstance(requires, list) and all(r in runtimes for r in requires), f"{where}: requires names unknown runtimes")
            login = comp.get("login")
            need(isinstance(login, dict) and set(login) == {"command", "note"}
                 and all(isinstance(v, str) and v for v in login.values()), f"{where}: login needs command and note")
            sysp = comp.get("system_packages")
            need(isinstance(sysp, dict) and set(sysp) == {"required", "recommended"}
                 and all(isinstance(v, list) and all(p in packages for p in v) for v in sysp.values()),
                 f"{where}: system_packages names unknown packages")
            need(comp.get("check", {}).get("argv", [""])[0] in names, f"{where}: check must run one of its commands")
            need(type(comp.get("peak_ram_mb")) is int and 0 < comp["peak_ram_mb"] < 100_000, f"{where}: peak_ram_mb must be a positive integer")
            need(isinstance(comp.get("system_packages_note", ""), str) and len(comp.get("system_packages_note", "")) < 300,
                 f"{where}: bad system_packages_note")
            ext = comp.get("external_state")
            need(ext is None or (isinstance(ext, dict) and set(ext) == {"root", "subdir"} and ext["root"] == "hermes_home"
                                 and re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", str(ext["subdir"]))), f"{where}: bad external_state")
            if installer == "npm-lock":
                need(isinstance(comp.get("package"), str) and re.fullmatch(r"(@[a-z0-9-]+/)?[a-z0-9._-]+", comp["package"]),
                     f"{where}: bad package name")
                need(_rel_ok(comp.get("lock_dir")), f"{where}: bad lock_dir")
                lock = comp.get("lock")
                need(isinstance(lock, dict) and set(lock) == {"package_json_sha256", "package_lock_sha256"}
                     and all(isinstance(v, str) and SHA256.match(v) for v in lock.values()), f"{where}: lock needs two sha256 values")
                scripts = comp.get("allow_scripts")
                need(isinstance(scripts, list) and all(
                    isinstance(s, dict) and set(s) == {"package", "script"} and isinstance(s["package"], str)
                    and _rel_ok(s["package"].replace("@", "a")) and _rel_ok(s["script"]) for s in scripts),
                    f"{where}: allow_scripts needs package and script")
                if catalog_dir is not None and isinstance(lock, dict) and _rel_ok(comp.get("lock_dir")):
                    folder = catalog_dir / comp["lock_dir"]
                    for fname, key in (("package.json", "package_json_sha256"), ("package-lock.json", "package_lock_sha256")):
                        try:
                            got = sha256_file(folder / fname)
                        except OSError:
                            problems.append(f"{where}: {comp['lock_dir']}/{fname} is missing")
                            continue
                        need(got == lock.get(key), f"{where}: {fname} does not match the catalog hash")
                    try:
                        bad = lock_problems(json.loads((folder / "package-lock.json").read_text()))
                        need(not bad, f"{where}: {'; '.join(bad)}")
                    except (OSError, ValueError):
                        pass
                    try:
                        pkg = json.loads((folder / "package.json").read_text())
                        need(pkg.get("dependencies") == {comp.get("package"): comp.get("version")},
                             f"{where}: package.json must depend on exactly {comp.get('package')}@{comp.get('version')}")
                    except (OSError, ValueError):
                        pass
            elif installer == "binary":
                entries = comp.get("binary")
                need(isinstance(entries, dict) and set(entries) == set(platforms), f"{where}: binary must cover declared platforms")
                for plat, entry in (entries.items() if isinstance(entries, dict) else []):
                    ok = (isinstance(entry, dict) and set(entry) == {"url", "sha256", "size"}
                          and SHA256.fullmatch(str(entry.get("sha256")))
                          and type(entry.get("size")) is int and 0 < entry["size"] < 512 * 1024 ** 2)
                    need(ok, f"{where}: bad binary entry for {plat}")
                    if isinstance(entry, dict):
                        need(url_problem(entry.get("url")) is None, f"{where}: binary URL refused")
                need(len(bins) == 1 and bins[0].get("argv") == [bins[0].get("name")], f"{where}: binary needs one direct command")
            elif installer == "pinned-script":
                need(isinstance(comp.get("repository"), str) and comp["repository"].startswith("https://github.com/"),
                     f"{where}: repository must be a GitHub https URL")
                need(isinstance(comp.get("commit"), str) and COMMIT.match(comp["commit"]), f"{where}: commit must be a 40-hex sha")
                need(isinstance(comp.get("tag"), str) and VERSION.match(comp["tag"].lstrip("v")), f"{where}: bad tag")
                script = comp.get("script")
                ok = (isinstance(script, dict) and set(script) == {"url", "sha256", "size"} and SHA256.match(str(script.get("sha256")))
                      and type(script.get("size")) is int and 0 < script["size"] < 2 * 1024 * 1024)
                need(ok, f"{where}: script needs url, sha256 and size")
                if isinstance(script, dict):
                    why = url_problem(script.get("url"))
                    need(why is None, f"{where}: {why}")
                    need(comp.get("commit", "-") in str(script.get("url")), f"{where}: script URL must name the pinned commit")
                args = comp.get("script_args")
                need(isinstance(args, list) and all(isinstance(a, str) and 0 < len(a) < 200 for a in args)
                     and "--commit" in args and "{commit}" in args, f"{where}: script_args must pass --commit {{commit}}")
                if isinstance(args, list):
                    need(all(re.fullmatch(r"[A-Za-z0-9_{}./=:-]+", a) for a in args), f"{where}: script_args has odd characters")
            if installer != "binary":
                need("binary" not in comp, f"{where}: has binary-only keys")
            if installer != "pinned-script":
                need(not ({"repository", "commit", "script", "script_args", "tag"} & set(comp)), f"{where}: has Hermes-only keys")
            if installer != "npm-lock":
                need(not ({"package", "lock_dir", "lock", "allow_scripts"} & set(comp)), f"{where}: has npm-only keys")
    return problems


@dataclass(frozen=True)
class Catalog:
    raw: dict
    dir: Path

    @property
    def requirements(self) -> dict:
        return self.raw["requirements"]

    def component(self, cid: str) -> dict:
        found = self.raw["runtimes"].get(cid) or self.raw["tools"].get(cid)
        if found is None:
            raise ToolError(f"unknown tool {cid!r}")
        return found

    def is_runtime(self, cid: str) -> bool:
        return cid in self.raw["runtimes"]

    def ids(self) -> list[str]:
        return [*self.raw["runtimes"], *self.raw["tools"]]

    def tool_ids(self) -> list[str]:
        return list(self.raw["tools"])

    def fingerprint(self, cid: str, platform_key: str) -> str:
        comp = self.component(cid)
        shape = {k: v for k, v in comp.items() if k != "archive"}
        if "archive" in comp:
            shape["archive"] = comp["archive"].get(platform_key)
        return hashlib.sha256(canonical({"id": cid, "platform": platform_key, "entry": shape})).hexdigest()

    def vid(self, cid: str, platform_key: str) -> str:
        return f"{self.component(cid)['version']}-{self.fingerprint(cid, platform_key)[:12]}"


def load_catalog(catalog_dir: Path | str) -> Catalog:
    catalog_dir = Path(catalog_dir)
    raw = strict_json(read_regular(catalog_dir / "tool_catalog.json", MAX_CATALOG_BYTES, "tool catalog"), "tool catalog")
    problems = catalog_problems(raw, catalog_dir)
    if problems:
        raise ToolError(["the tool catalog is not usable:", *problems])
    return Catalog(raw, catalog_dir)


# --- host ------------------------------------------------------------------------------


@dataclass
class HostFacts:
    system: str
    machine: str
    pointer_bits: int
    os_name: str
    os_family: str
    euid: int
    mem_total_mb: int | None
    mem_available_mb: int | None
    disk_free_mb: int
    commands: dict = field(default_factory=dict)  # command name -> absolute path or None
    elsewhere: dict = field(default_factory=dict)  # tool command -> path of a copy installed outside the tools root
    can_restrict_privileges: bool = True

    @property
    def platform_key(self) -> str:
        arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(self.machine, self.machine)
        return f"{self.system.lower()}-{arch}"


SYSTEM_PATH = ("/usr/local/bin", "/usr/bin", "/bin", "/usr/local/sbin", "/usr/sbin", "/sbin")
PROBED_COMMANDS = ("gcc", "g++", "make", "curl", "git", "rg", "ffmpeg", "bash", "sudo")


def _os_release() -> tuple[str, str]:
    if sys.platform == "darwin":
        return "macOS", "darwin"
    try:
        text = Path("/etc/os-release").read_text(errors="replace")
    except OSError:
        return "unknown", "unknown"
    fields = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key] = value.strip().strip('"')
    family = (fields.get("ID", "") + " " + fields.get("ID_LIKE", "")).lower()
    return fields.get("PRETTY_NAME", fields.get("NAME", "unknown"))[:80], "debian" if "debian" in family else "other"


def _meminfo() -> tuple[int | None, int | None]:
    if sys.platform == "darwin":
        try:
            result = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5, check=True)
            return int(result.stdout.strip()) // (1024 * 1024), None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None, None
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            values[key] = int(rest.split()[0])
        return values["MemTotal"] // 1024, values.get("MemAvailable", values.get("MemFree", 0)) // 1024
    except (OSError, ValueError, KeyError, IndexError):
        return None, None


def detect_host(root: Path, tool_commands: tuple[str, ...] = ()) -> HostFacts:
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    st = os.statvfs(probe)
    name, family = _os_release()
    total, available = _meminfo()
    commands = {}
    for cmd in PROBED_COMMANDS:
        commands[cmd] = next((os.path.join(d, cmd) for d in SYSTEM_PATH
                              if os.path.isfile(os.path.join(d, cmd)) and os.access(os.path.join(d, cmd), os.X_OK)), None)
    managed_bin = os.path.realpath(root / "bin")
    search = [*os.environ.get("PATH", "").split(os.pathsep), str(Path.home() / ".local" / "bin"), str(Path.home() / ".grok" / "bin"), "/opt/homebrew/bin", *SYSTEM_PATH]
    elsewhere = {}
    for cmd in tool_commands:
        for d in search:
            candidate = os.path.join(d, cmd) if d else ""
            if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK) \
                    and os.path.realpath(d) != managed_bin:
                elsewhere[cmd] = candidate
                break
    uname = os.uname()
    return HostFacts(system=uname.sysname, machine=uname.machine, pointer_bits=struct.calcsize("P") * 8, os_name=name,
                     os_family=family, euid=os.geteuid(), mem_total_mb=total, mem_available_mb=available,
                     disk_free_mb=(st.f_bavail * st.f_frsize) // (1024 * 1024), commands=commands, elsewhere=elsewhere,
                     can_restrict_privileges=sys.platform.startswith("linux") or sys.platform == "darwin")


def host_refusals(catalog: Catalog, facts: HostFacts, platform_key: str) -> list[str]:
    out = []
    if facts.pointer_bits != 64 or facts.machine in ("armv6l", "armv7l", "armv8l", "i386", "i686", "arm"):
        out.append(f"This is a 32-bit operating system (machine {facts.machine}, {facts.pointer_bits}-bit userland). "
                   "These tools need 64-bit Raspberry Pi OS (aarch64).")
    if facts.platform_key != platform_key or platform_key not in catalog.requirements["platforms"]:
        out.append(f"This host is {facts.platform_key}; the tool catalog supports "
                   f"{', '.join(catalog.requirements['platforms'])}.")
    if facts.euid == 0:
        out.append("Running as root. Tools are installed per user; sign in to the dashboard service's own user instead.")
    return out


# --- state -----------------------------------------------------------------------------


def empty_state() -> dict:
    return {"schema": STATE_SCHEMA, "tx": None, "last": None, "updated_at": None}


def load_state(cfg: ToolsConfig) -> dict:
    path = cfg.state_dir / "tools.json"
    if not os.path.lexists(path):
        return empty_state()
    state = strict_json(read_regular(path, MAX_STATE_BYTES, "tool state"), "tool state")
    if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA:
        raise ToolError("tool state has an unknown format; inspect it by hand")
    return {**empty_state(), **state}


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(path: Path, data: bytes, mode: int = 0o600) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)


def save_state(cfg: ToolsConfig, state: dict) -> dict:
    state["updated_at"] = int(time.time())
    write_atomic(cfg.state_dir / "tools.json", json.dumps(state, sort_keys=True, indent=1).encode())
    return state


def _history(cfg: ToolsConfig, entry: dict) -> None:
    path = cfg.state_dir / "history.jsonl"
    try:
        if os.path.getsize(path) > HISTORY_MAX_BYTES:
            os.replace(path, path.with_suffix(".jsonl.1"))
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as out:
        out.write(json.dumps(entry, sort_keys=True) + "\n")


def _finish(cfg: ToolsConfig, state: dict, outcome: str, detail: str, **extra) -> dict:
    tx = state.get("tx") or {}
    state["last"] = {"tx": tx.get("id"), "tool": tx.get("tool"), "action": tx.get("action"), "outcome": outcome,
                     "detail": detail[:600], "from": tx.get("from"), "to": tx.get("to"), "at": int(time.time()), **extra}
    state["tx"] = None
    save_state(cfg, state)
    _history(cfg, state["last"])
    write_atomic(cfg.state_dir / "receipts" / f"{state['last']['tx'] or secrets.token_hex(8)}.json",
                 json.dumps({"schema": RECEIPT_SCHEMA, "product": cfg.product, "platform": cfg.platform_key,
                             "outcome": state["last"]}, sort_keys=True, indent=1).encode())
    return state


@contextmanager
def invocation_lock(cfg: ToolsConfig) -> Iterator[None]:
    """One helper invocation at a time. The kernel releases it if the holder dies."""
    fd = os.open(cfg.state_dir / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ToolError("another tool install is already running") from None
        yield
    finally:
        os.close(fd)


def lock_is_held(cfg: ToolsConfig) -> bool:
    """True while a helper holds the lock. Read-only: it never keeps the lock."""
    try:
        fd = os.open(cfg.state_dir / "lock", os.O_RDWR | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


# --- installed view --------------------------------------------------------------------


def read_receipt(cfg: ToolsConfig, cid: str, vid: str) -> dict | None:
    if not VID.match(vid):
        return None
    path = cfg.version_dir(cid, vid) / VERSION_RECEIPT
    try:
        receipt = strict_json(read_regular(path, MAX_RECEIPT_BYTES, "version receipt"), "version receipt")
    except ToolError:
        return None
    ok = (isinstance(receipt, dict) and receipt.get("schema") == RECEIPT_SCHEMA and receipt.get("component") == cid
          and receipt.get("vid") == vid)
    return receipt if ok else None


def _link(cfg: ToolsConfig, cid: str, name: str) -> str | None:
    """The version id a current/previous symlink names, if it is a well-formed link to a real directory."""
    path = cfg.comp_dir(cid) / name
    try:
        target = os.readlink(path)
    except OSError:
        return None
    prefix = "versions/"
    vid = target[len(prefix):] if target.startswith(prefix) else ""
    if not VID.match(vid) or not os.path.isdir(cfg.version_dir(cid, vid)):
        return None
    return vid


def installed_view(cfg: ToolsConfig, cid: str) -> dict:
    """What is installed for one component, read from the links and receipts only."""
    out = {"installed": False, "current": None, "previous": None, "versions": []}
    base = cfg.comp_dir(cid) / "versions"
    try:
        names = sorted(n for n in os.listdir(base) if VID.match(n))
    except OSError:
        names = []
    for name in names:
        receipt = read_receipt(cfg, cid, name)
        out["versions"].append({"vid": name, "complete": receipt is not None,
                                "version": receipt.get("version") if receipt else None})
    for key in ("current", "previous"):
        vid = _link(cfg, cid, key)
        receipt = read_receipt(cfg, cid, vid) if vid else None
        if receipt:
            out[key] = {"vid": vid, "version": receipt["version"], "installed_at": receipt.get("installed_at"),
                        "check": receipt.get("check"), "fingerprint": receipt.get("fingerprint")}
    out["installed"] = out["current"] is not None
    return out


def installed_tools(cfg: ToolsConfig, catalog: Catalog) -> dict:
    return {cid: installed_view(cfg, cid) for cid in catalog.ids()}


# --- plan ------------------------------------------------------------------------------


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def _tool_dependents(catalog: Catalog, installed: dict, runtime: str, ignoring: str | None = None) -> list[str]:
    return [t for t in catalog.tool_ids() if t != ignoring and installed.get(t, {}).get("installed")
            and runtime in catalog.component(t).get("requires", [])]


def _apt_command(missing: list[str], facts: HostFacts) -> str | None:
    if not missing:
        return None
    if facts.os_family == "debian":
        return "sudo apt install -y " + " ".join(sorted(missing))
    if facts.os_family == "darwin":
        return "Install manually on macOS (Xcode Command Line Tools for build-essential; Homebrew for other tools): " + ", ".join(sorted(missing))
    return "Install with your package manager: " + " ".join(sorted(missing))


def system_package_report(catalog: Catalog, facts: HostFacts, required: list[str], recommended: list[str]) -> dict:
    packages = catalog.raw["system_packages"]

    def missing(names):
        return [n for n in names if any(not facts.commands.get(c) for c in packages[n]["commands"])]

    need, want = missing(required), missing([n for n in recommended if n not in required])
    return {"missing_required": need, "missing_recommended": want,
            "apt_command": _apt_command(need + want, facts),
            "details": {n: packages[n]["why"] for n in need + want},
            "note": "The dashboard never runs this. Run it yourself in a terminal if you want these packages."}


def _step_text(step: dict) -> str:
    op = step["op"]
    if op == "download":
        return f"download {step['url']} ({_mb(step['size'])}) and check its sha256 {step['sha256'][:16]}…"
    if op == "verify_shasums":
        return f"check the download against {step['url']}"
    if op == "extract":
        return f"unpack it into {step['dest']}"
    if op == "make_dir":
        return f"create {step['dest']}"
    if op == "install_binary":
        return f"install the verified binary as {step['dest']}/{step['bin']}"
    if op == "copy_lock":
        return f"copy the committed package.json and package-lock.json ({step['lock_dir']}) into {step['dest']}"
    if op in ("run", "check"):
        return " ".join(step["argv"]) + (f"   (in {step['cwd']})" if step.get("cwd") else "")
    if op == "activate":
        return f"point {step['link']} at {step['vid']} and write the command wrapper(s) {', '.join(step['bins']) or '(none)'}"
    if op == "remove":
        return f"delete {step['dir']} and the wrapper(s) {', '.join(step['bins']) or '(none)'}"
    if op == "rollback":
        return f"point {step['link']} back at {step['to_vid']}"
    return op


def _component_install_steps(cfg: ToolsConfig, catalog: Catalog, cid: str, action: str, installed: dict) -> list[dict]:
    comp = catalog.component(cid)
    plat = cfg.platform_key
    vid = catalog.vid(cid, plat)
    vdir = cfg.version_dir(cid, vid)
    steps: list[dict] = []
    installer = comp["installer"]
    node_bin = cfg.comp_dir("node") / "current" / "bin"
    if read_receipt(cfg, cid, vid) is not None:
        # This exact version is already on disk (it was the one rolled back from): just check and switch to it.
        return [{"op": "check", "c": cid, "argv": [*comp["check"]["argv"]], "expect": comp["check"]["expect"], "cwd": str(vdir)},
                {"op": "activate", "c": cid, "vid": vid, "link": str(cfg.comp_dir(cid) / "current"),
                 "bins": [b["name"] for b in comp["bins"]]}]
    if installer == "archive":
        a = comp["archive"][plat]
        name = a["url"].rsplit("/", 1)[1]
        steps.append({"op": "download", "c": cid, "name": name, "url": a["url"], "sha256": a["sha256"], "size": a["size"]})
        if a.get("shasums_url"):
            steps.append({"op": "verify_shasums", "c": cid, "name": name, "url": a["shasums_url"], "sha256": a["sha256"]})
        steps.append({"op": "extract", "c": cid, "name": name, "format": a["format"], "root": a["root"], "dest": str(vdir)})
    elif installer == "npm-lock":
        steps.append({"op": "copy_lock", "c": cid, "lock_dir": comp["lock_dir"], "dest": str(vdir),
                      "package_json_sha256": comp["lock"]["package_json_sha256"],
                      "package_lock_sha256": comp["lock"]["package_lock_sha256"]})
        steps.append({"op": "run", "c": cid, "kind": "npm-ci", "cwd": str(vdir), "timeout": RUN_TIMEOUTS["npm-ci"],
                      "argv": [str(node_bin / "npm"), "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--no-progress",
                               "--loglevel=error"]})
        for script in comp["allow_scripts"]:
            steps.append({"op": "run", "c": cid, "kind": "script-step", "cwd": str(vdir),
                          "timeout": RUN_TIMEOUTS["script-step"],
                          "argv": [str(node_bin / "node"), f"node_modules/{script['package']}/{script['script']}"]})
    elif installer == "binary":
        entry = comp["binary"][plat]
        name = entry["url"].rsplit("/", 1)[1]
        steps.append({"op": "download", "c": cid, "name": name, **entry})
        steps.append({"op": "install_binary", "c": cid, "name": name, "bin": comp["bins"][0]["name"], "dest": str(vdir)})
    else:  # pinned-script
        script = comp["script"]
        steps.append({"op": "make_dir", "c": cid, "dest": str(vdir)})
        steps.append({"op": "download", "c": cid, "name": "install.sh", "url": script["url"], "sha256": script["sha256"],
                      "size": script["size"]})
        args = [a.replace("{commit}", comp["commit"]).replace("{install_dir}", str(vdir / "hermes-agent"))
                .replace("{hermes_home}", str(cfg.hermes_home)) for a in comp["script_args"]]
        steps.append({"op": "run", "c": cid, "kind": "script", "cwd": str(vdir), "timeout": RUN_TIMEOUTS["script"],
                      "argv": ["bash", "<downloaded install.sh>", *args]})
    check_argv = [*comp["check"]["argv"]]
    steps.append({"op": "check", "c": cid, "argv": check_argv, "expect": comp["check"]["expect"], "cwd": str(vdir)})
    steps.append({"op": "activate", "c": cid, "vid": vid, "link": str(cfg.comp_dir(cid) / "current"),
                  "bins": [b["name"] for b in comp["bins"]]})
    return steps


_NATIVE_VERSIONS = {}

def version_key(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?', value or '')
    return (*map(int, match.groups()), 0 if "-" in value.split("+")[0] else 1) if match else None

def native_install(cfg, catalog, facts, cid):
    if cid not in catalog.tool_ids(): return None
    name = catalog.component(cid)['bins'][0]['name']
    path = facts.elsewhere.get(name)
    if not path: return None
    try:
        binary = Path(path)
        if binary.resolve().is_relative_to(cfg.root.resolve()): return None
        stat = binary.stat()
        key = (str(binary), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        cached = _NATIVE_VERSIONS.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            version = cached[1]
        else:
            # Version-only invocation: never pass provider secrets or start an agent session.
            env = {'HOME': str(cfg.home), 'PATH': os.environ.get('PATH', '') + os.pathsep + '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
                   'LANG': 'C.UTF-8'}
            result = subprocess.run([str(binary), '--version'], stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=5, env=env)
            match = re.search(r'(?<![\w.])v?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)', result.stdout[:4096]) if result.returncode == 0 else None
            version = match.group(1) if match else None
            _NATIVE_VERSIONS[key] = (time.monotonic(), version)
        return {'path': str(binary), 'version': version}
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return {'path': str(path), 'version': None}


def login_command(command, path):
    """The sign-in command as it should be typed in a plain shell. A tool this dashboard installed lives in its own `bin`, which is usually not on the
    shell's PATH, so `codex login` fails with "command not found"; then the command starts with the tool's full path."""
    first, _, rest = command.partition(" ")
    if not path or not os.path.isabs(path) or Path(path).name != first:
        return command
    found = shutil.which(first)
    if found and os.path.realpath(found) == os.path.realpath(path):
        return command
    return (shlex.quote(path) + (" " + rest if rest else ""))


def build_plan(cfg: ToolsConfig, catalog: Catalog, facts: HostFacts, cid: str, action: str) -> dict:
    """The exact operation, as the confirmation dialog shows it and the helper will run it.

    `plan_sha256` covers only the static part (versions, sources, commands), never free disk or memory,
    so a plan the operator confirmed is the one that runs, whatever the host does in between.
    """
    if action not in ACTIONS:
        raise ToolError(f"unknown action {action!r}")
    if cid not in catalog.raw["tools"]:
        raise ToolError(f"{cid!r} is not an installable tool")
    comp = catalog.component(cid)
    plat = cfg.platform_key
    installed = installed_tools(cfg, catalog)
    mine = installed[cid]
    refusals = host_refusals(catalog, facts, plat)
    warnings: list[str] = []
    steps: list[dict] = []
    runtimes: list[dict] = []
    removals: list[str] = []
    native = native_install(cfg, catalog, facts, cid) if not mine["installed"] else None
    frm = mine["current"]["version"] if mine["current"] else native["version"] if native else None
    to = comp["version"]
    req = catalog.requirements
    required_mb = 0

    state = load_state(cfg)
    if state.get("tx"):
        refusals.append("An install, update or removal is already in progress or was interrupted. Wait for it, then retry.")

    if action in ("install", "update"):
        if action == "install" and (mine["installed"] or native):
            refusals.append(f"{comp['name']} {frm} is already installed. Use Update when a newer pinned version exists.")
        if action == "update" and not mine["installed"] and not native:
            refusals.append(f"{comp['name']} is not installed. Use Install.")
        if action == "update" and native:
            old, new = version_key(frm), version_key(to)
            if old is None or new is None:
                refusals.append("The native version could not be verified; check it manually before upgrading.")
            elif old >= new:
                refusals.append("The native installation is already at or newer than the latest verified version.")
            warnings.append("This upgrade installs a verified managed copy for dashboard use. The native installation and its account configuration are kept; removing the managed copy restores native discovery.")
        if action == "update" and mine["installed"] and mine["current"]["fingerprint"] == catalog.fingerprint(cid, plat):
            refusals.append(f"{comp['name']} {frm} is already the pinned version.")
        if plat not in req["platforms"]:
            pass  # host_refusals already said so
        else:
            for rid in comp["requires"]:
                rt = catalog.component(rid)
                rview = installed[rid]
                same = rview["installed"] and rview["current"]["fingerprint"] == catalog.fingerprint(rid, plat)
                kind = "present" if same else ("update" if rview["installed"] else "install")
                runtimes.append({"id": rid, "name": rt["name"], "version": rt["version"], "action": kind,
                                 "from": rview["current"]["version"] if rview["installed"] else None})
                if not same:
                    required_mb += rt["size_mb"]
                    steps += _component_install_steps(cfg, catalog, rid, kind, installed)
            required_mb += comp["size_mb"]
            steps += _component_install_steps(cfg, catalog, cid, action, installed)
        free, floor = facts.disk_free_mb, req["min_free_disk_mb"]
        if free < floor:
            refusals.append(f"Only {free} MB of disk is free where the tools are installed; at least {floor} MB is needed.")
        elif free < required_mb + req["disk_headroom_mb"]:
            refusals.append(f"This needs about {required_mb} MB plus {req['disk_headroom_mb']} MB of working room, "
                            f"and only {free} MB is free.")
        sysp = comp["system_packages"]
        report = system_package_report(catalog, facts, sysp["required"], sysp["recommended"])
        for name in report["missing_required"]:
            refusals.append(f"{name} is required ({catalog.raw['system_packages'][name]['why']}) and is not installed. "
                            f"Run: {report['apt_command']}")
        for name in report["missing_recommended"]:
            warnings.append(f"{name} is not installed ({catalog.raw['system_packages'][name]['why']}). {comp['name']} installs and "
                            f"runs without it. {comp.get('system_packages_note', '')}".strip())
        total, avail = facts.mem_total_mb, facts.mem_available_mb
        if total is not None and total < req["warn_ram_mb"]:
            warnings.append(f"This host has {total} MB of memory. 4 GB or more is recommended; "
                            "installing and running several agents may be slow or run out of memory.")
        peak = comp["peak_ram_mb"]
        if avail is not None and avail < max(req["warn_available_ram_mb"], peak):
            warnings.append(f"Only {avail} MB of memory is available right now and installing {comp['name']} can use about "
                            f"{peak} MB. Close other work before installing.")
        if not facts.can_restrict_privileges:
            refusals.append("This host cannot restrict the installer from gaining privileges, so the no-sudo rule "
                            "cannot be enforced here.")
        refusals += wrapper_conflicts(cfg, [b["name"] for b in comp["bins"]])
        for b in comp["bins"]:
            other = facts.elsewhere.get(b["name"])
            if other:
                warnings.append(f"{b['name']} is already installed at {other}; the managed copy is used by the dashboard.")
    elif action == "remove":
        report = system_package_report(catalog, facts, [], [])
        if not mine["installed"] and not mine["versions"]:
            refusals.append(f"{comp['name']} is not installed.")
        steps.append({"op": "remove", "c": cid, "dir": str(cfg.comp_dir(cid)), "bins": [b["name"] for b in comp["bins"]]})
        for rid in comp["requires"]:
            if not _tool_dependents(catalog, installed, rid, ignoring=cid) and (
                    installed[rid]["installed"] or installed[rid]["versions"]):
                steps.append({"op": "remove", "c": rid, "dir": str(cfg.comp_dir(rid)), "bins": []})
                removals.append(f"{catalog.component(rid)['name']} {installed[rid]['current']['version'] if installed[rid]['current'] else ''}".strip()
                                + " (nothing else uses it)")
        if comp.get("external_state"):
            found = [p for v in mine["versions"] for p in (read_receipt(cfg, cid, v["vid"]) or {}).get("external", [])]
            if found:
                removals.append(f"{len(found)} dependency folder(s) {comp['name']} made under {external_root(cfg, comp['external_state'])}")
            warnings.append(f"Your {comp['name']} data in {cfg.hermes_home} (config, sessions, memories, and the Python, Node, ripgrep "
                            "and ffmpeg it downloaded for itself) is kept. Only the program is removed. Delete that folder "
                            "yourself if you want it gone.")
    else:  # rollback
        report = system_package_report(catalog, facts, [], [])
        prev = mine["previous"]
        if not mine["installed"]:
            refusals.append(f"{comp['name']} is not installed.")
        elif not prev:
            refusals.append("No previous version is kept, so there is nothing to roll back to.")
        else:
            to = prev["version"]
            steps.append({"op": "rollback", "c": cid, "link": str(cfg.comp_dir(cid) / "current"), "to_vid": prev["vid"],
                          "from_vid": mine["current"]["vid"], "bins": [b["name"] for b in comp["bins"]],
                          "check": comp["check"]})
    commands = [_step_text(s) for s in steps]
    static = {
        "schema": PLAN_SCHEMA, "product": cfg.product, "platform": plat, "tool": cid, "action": action, "from": frm,
        "to": to if action != "remove" else None, "steps": steps, "runtimes": runtimes, "removes": removals,
    }
    plan = {
        **static, "name": comp["name"], "commands": commands,
        "downloads": [{"url": s["url"], "sha256": s["sha256"], "size": s["size"]} for s in steps if s["op"] == "download"],
        "note": comp.get("note"), "unchanged": list(UNCHANGED), "login": comp["login"] if action in ("install", "update") else None,
        "system_packages": report,
    }
    plan["plan_sha256"] = hashlib.sha256(canonical(static)).hexdigest()
    plan["disk"] = {"free_mb": facts.disk_free_mb, "required_mb": required_mb, "min_free_mb": req["min_free_disk_mb"],
                    "headroom_mb": req["disk_headroom_mb"]}
    plan["memory"] = {"total_mb": facts.mem_total_mb, "available_mb": facts.mem_available_mb,
                      "recommended_mb": 4096}
    plan["host"] = {"os": facts.os_name, "machine": facts.machine, "bits": facts.pointer_bits}
    plan["refusals"], plan["warnings"] = refusals, warnings
    return plan


# --- transport -------------------------------------------------------------------------


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, limit: int = 4):
        self.count, self.limit = 0, limit

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        target = urllib.parse.urljoin(req.full_url, newurl)
        if self.count > self.limit:
            raise ToolError("too many redirects")
        why = url_problem(target.split("?", 1)[0]) if "?" in target else url_problem(target)
        if why:
            raise ToolError(f"redirect refused: {why}")
        return urllib.request.Request(target, method="GET", headers={
            k: v for k, v in req.header_items() if k.lower() in ("accept", "user-agent", "accept-encoding")})


def _open_url(url: str, timeout: float = 30.0):
    why = url_problem(url)
    if why:
        raise ToolError(why)
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/octet-stream",
                                                             "Accept-Encoding": "identity", "User-Agent": "rcd-agent-tools"})
    try:
        resp = urllib.request.build_opener(_Redirects()).open(req, timeout=timeout)
    except ToolError:
        raise
    except urllib.error.HTTPError as exc:
        raise ToolError(f"{url.rsplit('/', 1)[-1]}: the server answered HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ToolError(f"{url.rsplit('/', 1)[-1]}: network error ({type(getattr(exc, 'reason', exc)).__name__})") from None
    if resp.status != 200:
        resp.close()
        raise ToolError(f"{url.rsplit('/', 1)[-1]}: unexpected HTTP status {resp.status}")
    if (resp.headers.get("Content-Encoding") or "identity").lower() != "identity":
        resp.close()
        raise ToolError("refusing a content-encoded download")
    return resp


def fetch_file(url: str, dest: Path, sha256: str, size: int) -> None:
    """Download `url` to `dest`, exactly `size` bytes and exactly `sha256`, or raise and leave nothing."""
    resp = _open_url(url)
    digest, total = hashlib.sha256(), 0
    started = time.monotonic()
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        declared = resp.headers.get("Content-Length")
        if declared is not None and (not declared.isdigit() or int(declared) != size):
            raise ToolError(f"{dest.name}: the server's length differs from the pinned size")
        with os.fdopen(fd, "wb") as out:
            while True:
                if time.monotonic() - started > 3600:
                    raise ToolError(f"{dest.name}: download took too long")
                chunk = resp.read(min(CHUNK, size + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > size:
                    raise ToolError(f"{dest.name}: download is larger than the pinned size")
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if total != size:
            raise ToolError(f"{dest.name}: download ended early ({total} of {size} bytes)")
        if digest.hexdigest() != sha256:
            raise ToolError(f"{dest.name}: sha256 {digest.hexdigest()[:16]}… differs from the pinned {sha256[:16]}…")
    except BaseException as exc:
        try:
            os.unlink(dest)
        except OSError:
            pass
        if isinstance(exc, ToolError) or not isinstance(exc, Exception):
            raise
        raise ToolError(f"{dest.name}: transfer failed ({type(exc).__name__})") from None
    finally:
        resp.close()


def fetch_text(url: str, limit: int = MAX_SHASUMS_BYTES) -> str:
    resp = _open_url(url)
    try:
        data = resp.read(limit + 1)
    except OSError as exc:
        raise ToolError(f"read failed ({type(exc).__name__})") from None
    finally:
        resp.close()
    if len(data) > limit:
        raise ToolError("response is larger than the limit")
    return data.decode("utf-8", "replace")


# --- extraction ------------------------------------------------------------------------


def extract_archive(archive: Path, fmt: str, root: str, dest: Path) -> None:
    """Unpack a tar into `dest` (which must not exist), dropping the leading `root` folder.

    Only plain files, folders and links that stay inside `dest` are accepted; modes lose setuid/setgid
    and group/other write. Anything else, or a path that leaves `dest`, aborts the whole unpack.
    """
    if os.path.lexists(dest):
        raise ToolError(f"{dest} already exists")
    mode = {"tar.xz": "r:xz", "tar.gz": "r:gz"}[fmt]
    os.mkdir(dest, 0o700)
    base = os.path.realpath(dest)
    count = total = 0
    try:
        with tarfile.open(archive, mode) as tf:
            for mem in tf:
                count += 1
                if count > MAX_EXTRACT_MEMBERS:
                    raise ToolError("the archive has too many members")
                name = mem.name
                parts = [p for p in name.split("/") if p not in ("", ".")]
                if name.startswith("/") or "\\" in name or not parts or parts[0] != root or ".." in parts:
                    raise ToolError(f"archive member refused: {name[:80]!r}")
                rel = "/".join(parts[1:])
                if not rel:
                    continue
                target = os.path.join(base, rel)
                if os.path.commonpath([base, os.path.realpath(os.path.dirname(target))]) != base:
                    raise ToolError(f"archive member leaves the folder: {mem.name[:80]!r}")
                if mem.isdir():
                    os.makedirs(target, mode=0o755, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
                if mem.isreg():
                    total += mem.size
                    if total > MAX_EXTRACT_BYTES:
                        raise ToolError("the archive unpacks to more than the limit")
                    src = tf.extractfile(mem)
                    perm = 0o755 if mem.mode & 0o111 else 0o644
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, perm)
                    with os.fdopen(fd, "wb") as out:
                        shutil.copyfileobj(src, out, CHUNK)
                    os.chmod(target, perm)
                elif mem.issym():
                    link = mem.linkname
                    resolved = os.path.normpath(os.path.join(os.path.dirname(target), link))
                    if os.path.isabs(link) or os.path.commonpath([base, resolved]) != base:
                        raise ToolError(f"archive link leaves the folder: {mem.name[:80]!r}")
                    os.symlink(link, target)
                elif mem.islnk():
                    lparts = mem.linkname.split("/")
                    if lparts[0] != root or ".." in lparts:
                        raise ToolError(f"archive hard link refused: {mem.name[:80]!r}")
                    os.link(os.path.join(base, "/".join(lparts[1:])), target)
                else:
                    raise ToolError(f"archive member type refused: {mem.name[:80]!r}")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ToolError(f"the archive could not be unpacked ({type(exc).__name__})") from None


# --- running commands --------------------------------------------------------------------


def harden_process(cfg: ToolsConfig | None = None) -> bool:
    """Set no_new_privs on this process and everything it starts: setuid programs and sudo cannot raise
    privileges any more, even for a user with passwordless sudo. Irreversible for the process."""
    if sys.platform == "darwin":
        if cfg is None:
            return False
        return harden_macos(cfg)
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            return False
        return libc.prctl(39, 0, 0, 0, 0) == 1  # PR_GET_NO_NEW_PRIVS
    except (OSError, AttributeError):
        return False


def macos_profile(cfg: ToolsConfig) -> str:
    """Installer-only Seatbelt profile: write in managed state, no privilege/GUI brokers.
    It is inherited by all descendants; command wrappers used later by the operator are outside it.
    """
    quote = lambda p: json.dumps(str(Path(p).resolve()))
    readable = ["/System", "/usr", "/bin", "/sbin", "/Library", "/opt", "/private/etc", "/private/var/db", "/dev", cfg.root, cfg.hermes_home / 'tools', cfg.hermes_home / 'cache', cfg.hermes_home / 'installs', cfg.hermes_home / 'skills', cfg.catalog_dir]
    reads = " ".join(f"(subpath {quote(p)})" for p in readable)
    writes = " ".join(f"(subpath {quote(p)})" for p in (cfg.root, cfg.hermes_home))
    return f'''(version 1)
(allow default)
(deny file-write*)
(allow file-write* {writes} (literal "/dev/null") (literal "/dev/stdout") (literal "/dev/stderr"))
(deny file-write-setugid)
(deny process-exec (regex #".*/(sudo|su|osascript|authopen|launchctl|open|brew|port|xcode-select|softwareupdate)$"))
(deny mach-lookup (global-name "com.apple.authd") (global-name "com.apple.coreservices.launchservicesd") (global-name "com.apple.lsd") (global-name "com.apple.coreservices.uiagent") (global-name "com.apple.SecurityServer"))
(deny authorization-right-obtain)
(deny system-privilege)
(deny file-read-data (subpath {quote(cfg.home)}))
(allow file-read* {reads})
(allow file-read-data {reads})
(deny file-read-data (literal {quote(cfg.native_hermes_home / ".env")}) (literal {quote(cfg.native_hermes_home / "config.yaml")}))
'''


def harden_macos(cfg: ToolsConfig) -> bool:
    try:
        import ctypes
        library = ctypes.CDLL("/usr/lib/libsandbox.dylib")
        error = ctypes.c_void_p()
        library.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)]
        library.sandbox_init.restype = ctypes.c_int
        result = library.sandbox_init(macos_profile(cfg).encode(), 0, ctypes.byref(error))
        if error.value:
            library.sandbox_free_error.argtypes = [ctypes.c_void_p]
            library.sandbox_free_error(error)
        return result == 0
    except (OSError, AttributeError):
        return False


PASS_THROUGH_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
                    "SSL_CERT_FILE", "SSL_CERT_DIR", "LANG")


def child_env(cfg: ToolsConfig, home: Path, *, hermes: bool = False, node: bool = True) -> dict:
    """What an installer or a tool check is allowed to see: nothing from the service, no keys, no tokens."""
    path = [*([str(cfg.comp_dir("node") / "current" / "bin")] if node else []), *SYSTEM_PATH[:4]]
    env = {"PATH": os.pathsep.join(path), "HOME": str(home), "LC_ALL": "C" if sys.platform == "darwin" else "C.UTF-8", "TMPDIR": str(cfg.tmp),
           "npm_config_cache": str(cfg.cache / "npm"), "npm_config_registry": "https://registry.npmjs.org/",
           "npm_config_update_notifier": "false", "npm_config_audit": "false", "npm_config_fund": "false",
           "UV_CACHE_DIR": str(cfg.cache / "uv"), "UV_NO_CONFIG": "1", "GIT_TERMINAL_PROMPT": "0",
           "GIT_ASKPASS": "/bin/false", "CI": "1", "NO_COLOR": "1", "SHELL": "/bin/bash"}
    for key in PASS_THROUGH_ENV:
        if key in os.environ:
            env[key] = os.environ[key]
    if hermes:
        env["HERMES_HOME"] = str(cfg.hermes_home)
    return env


class Log:
    """Append-only helper log, owner-only, capped by rotation."""

    def __init__(self, path: Path | None):
        self.path, self._lock = path, threading.Lock()
        self.fd = None
        if path is not None:
            try:
                if os.path.getsize(path) > LOG_MAX_BYTES:
                    os.replace(path, path.with_suffix(".log.1"))
            except OSError:
                pass
            self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)

    def line(self, text: str) -> None:
        if self.fd is None:
            return
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            os.write(self.fd, f"{stamp} {text.rstrip()}\n".encode("utf-8", "replace"))

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def run_command(argv: list[str], cwd: Path, env: dict, timeout: int, log: Log, label: str) -> tuple[int, str]:
    """Run one command to completion, streaming its output to the log. Returns (exit code, last output)."""
    log.line(f"$ {' '.join(argv)}   [{label}]")
    try:
        proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    except OSError as exc:
        return 127, f"could not start {argv[0]} ({type(exc).__name__})"
    tail: list[str] = []

    def pump():
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            log.line(f"  {line}")
            tail.append(line)
            del tail[:-40]

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        proc.wait()
        reader.join(5)
        log.line(f"  timed out after {timeout}s")
        return 124, f"timed out after {timeout} seconds"
    reader.join(10)
    return proc.returncode, "\n".join(tail[-12:])[-1500:]


@dataclass
class Ops:
    """Everything that touches the network or starts a process, in one place so tests can replace it."""
    fetch: Callable[[str, Path, str, int], None] = fetch_file
    fetch_text: Callable[[str], str] = fetch_text
    run: Callable[..., tuple[int, str]] = run_command


# --- wrappers and links ----------------------------------------------------------------


def render_wrapper(cfg: ToolsConfig, catalog: Catalog, cid: str, bin_entry: dict, base: Path) -> str:
    comp = catalog.component(cid)
    node = cfg.comp_dir("node") / "current" / "bin"
    lines = ["#!/bin/sh", f"{WRAPPER_MARK} {cid}/{bin_entry['name']}. Written by the dashboard's Agent tools; Remove deletes it."]
    if "node" in comp.get("requires", []):
        lines.append(f'PATH="{node}:$PATH"; export PATH')
    for var in bin_entry.get("env_unset", []):
        lines.append(f"unset {var}")
    if cid == "hermes":
        # Installer checks explicitly supply their isolated HERMES_HOME. Normal
        # operator sessions retain the native account home, including custom profiles.
        lines.append('HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"; export HERMES_HOME')
        lines.append(f'HERMES_RUNTIME_DIR="{cfg.hermes_home / "tools"}"; export HERMES_RUNTIME_DIR')
    argv = " ".join(f'"{base / a}"' for a in bin_entry["argv"])
    lines.append(f'exec {argv} "$@"')
    return "\n".join(lines) + "\n"


def _replace_symlink(path: Path, target: str) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(5)}")
    os.symlink(target, tmp)
    try:
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)


def wrapper_conflicts(cfg: ToolsConfig, names: list[str]) -> list[str]:
    """Commands in the managed bin folder that something other than the Agent tools put there."""
    out = []
    for name in names:
        dest = cfg.bin / name
        if os.path.lexists(dest):
            try:
                text = read_regular(dest, 8192, "wrapper").decode("utf-8", "replace")
            except ToolError:
                text = ""
            if WRAPPER_MARK not in text:
                out.append(f"{dest} already exists and was not written by the Agent tools, so it was left alone.")
    return out


def write_wrappers(cfg: ToolsConfig, catalog: Catalog, cid: str, base: Path, into: Path | None = None) -> None:
    if into is None:
        clash = wrapper_conflicts(cfg, [e["name"] for e in catalog.component(cid)["bins"]])
        if clash:
            raise ToolError(clash)
    for entry in catalog.component(cid)["bins"]:
        dest = (into or cfg.bin) / entry["name"]
        write_atomic(dest, render_wrapper(cfg, catalog, cid, entry, base).encode(), mode=0o755)
        os.chmod(dest, 0o755)


def remove_wrappers(cfg: ToolsConfig, names: list[str]) -> None:
    for name in names:
        path = cfg.bin / name
        try:
            text = read_regular(path, 8192, "wrapper").decode("utf-8", "replace")
        except ToolError:
            continue
        if WRAPPER_MARK in text:
            os.unlink(path)


def flip(cfg: ToolsConfig, cid: str, new_vid: str) -> None:
    """current -> new_vid, previous -> what current was. Safe to repeat; a crash between the two leaves both on the old version."""
    cdir = cfg.comp_dir(cid)
    old = _link(cfg, cid, "current")
    if old and old != new_vid:
        _replace_symlink(cdir / "previous", f"versions/{old}")
    _replace_symlink(cdir / "current", f"versions/{new_vid}")


def external_root(cfg: ToolsConfig, spec: dict) -> Path:
    return {"hermes_home": cfg.hermes_home}[spec["root"]] / spec["subdir"]


def external_children(cfg: ToolsConfig, spec: dict) -> set[str]:
    root = external_root(cfg, spec)
    try:
        return {str(root / n) for n in os.listdir(root) if re.fullmatch(r"[0-9A-Za-z]{8,64}", n) and (root / n).is_dir()}
    except OSError:
        return set()


def remove_externals(cfg: ToolsConfig, catalog: Catalog, cid: str, vids: list[str] | None = None, *, all_versions: bool = False) -> list[str]:
    """Delete the folders a version's installer made outside the tools root, as its receipt recorded them."""
    comp = catalog.component(cid)
    spec = comp.get("external_state")
    if not spec:
        return []
    root = external_root(cfg, spec)
    names = vids if not all_versions else [v["vid"] for v in installed_view(cfg, cid)["versions"]]
    gone = []
    for vid in names:
        for path in (read_receipt(cfg, cid, vid) or {}).get("external", []):
            p = Path(path)
            if p.parent == root and re.fullmatch(r"[0-9A-Za-z]{8,64}", p.name) and p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
                gone.append(str(p))
    return gone


def prune(cfg: ToolsConfig, catalog: Catalog, cid: str) -> list[str]:
    keep = {v for v in (_link(cfg, cid, "current"), _link(cfg, cid, "previous")) if v}
    gone = []
    base = cfg.comp_dir(cid) / "versions"
    if not keep:
        return gone
    for name in sorted(os.listdir(base)):
        path = base / name
        if name not in keep and VID.match(name) and path.is_dir() and not path.is_symlink():
            remove_externals(cfg, catalog, cid, [name])
            shutil.rmtree(path)
            gone.append(name)
    return gone


def _safe_rmtree(cfg: ToolsConfig, path: Path) -> None:
    if os.path.islink(path) or not path.is_dir():
        if os.path.lexists(path):
            raise ToolError(f"{path} is not a real directory; left alone")
        return
    if os.path.commonpath([os.path.realpath(path), os.path.realpath(cfg.tools)]) != os.path.realpath(cfg.tools):
        raise ToolError(f"{path} is outside the tools folder; left alone")
    shutil.rmtree(path)


# --- execution ---------------------------------------------------------------------------


class Executor:
    def __init__(self, cfg: ToolsConfig, catalog: Catalog, ops: Ops, log: Log, txid: str):
        self.cfg, self.catalog, self.ops, self.log, self.txid = cfg, catalog, ops, log, txid
        self.work = cfg.tmp / txid
        self.sand = cfg.sandbox / txid
        self.downloads: dict[str, Path] = {}
        self.vdirs_created: list[tuple[str, Path]] = []
        self.activated: list[str] = []
        self.check_result: dict | None = None
        self.externals: dict[str, list[str]] = {}

    def sandbox_home(self, cid: str, vdir: Path) -> Path:
        """HOME for installers and checks: inside the version folder for Hermes (everything it writes belongs to
        that version), a throwaway folder for the others. The real home is never the installer's HOME."""
        home = (vdir / "home") if cid == "hermes" else (self.sand / f"home-{cid}")
        os.makedirs(home, mode=0o700, exist_ok=True)
        return home

    def external_names(self, comp: dict) -> set[str]:
        spec = comp.get("external_state")
        return set(external_children(self.cfg, spec)) if spec else set()

    def record_external(self, cid: str, comp: dict, before: set[str]) -> None:
        """Folders the installer created outside the tools root (Hermes keeps one dependency state per checkout)."""
        spec = comp.get("external_state")
        if spec:
            made = sorted(external_children(self.cfg, spec) - before)
            self.externals.setdefault(cid, []).extend(made)
            self.log.line(f"  recorded {len(made)} folder(s) the installer made under {external_root(self.cfg, spec)}")

    def start(self) -> None:
        os.makedirs(self.work, mode=0o700, exist_ok=False)
        os.makedirs(self.sand, mode=0o700, exist_ok=False)

    def cleanup(self) -> None:
        """Downloads, sandbox homes and package caches are working space: gone when the operation ends (the lock is held,
        so nothing else is using them). A Pi's disk is better spent on the tools than on a cache of their downloads."""
        for base in (self.cfg.tmp, self.cfg.sandbox, self.cfg.cache):
            try:
                for child in base.iterdir():
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() and not child.is_symlink() else child.unlink()
            except OSError:
                pass

    def run_steps(self, steps: list[dict], on_phase: Callable[[str], None]) -> None:
        for step in steps:
            getattr(self, "do_" + step["op"])(step, on_phase)

    # download ------------------------------------------------------------------------
    def do_download(self, step, on_phase):
        on_phase(f"downloading {step['name']}")
        dest = self.work / f"{step['c']}-{step['name']}"
        self.log.line(f"download {step['url']}")
        self.ops.fetch(step["url"], dest, step["sha256"], step["size"])
        self.downloads[f"{step['c']}:{step['name']}"] = dest
        self.log.line(f"  sha256 and size match the catalog ({step['sha256'][:16]}…)")

    def do_verify_shasums(self, step, on_phase):
        on_phase("checking the download against the publisher's SHASUMS256.txt")
        text = self.ops.fetch_text(step["url"])
        found = [line.split()[0] for line in text.splitlines() if len(line.split()) == 2 and line.split()[1].lstrip("*") == step["name"]]
        if found != [step["sha256"]]:
            raise ToolError(f"{step['name']}: the publisher's SHASUMS256.txt does not list the pinned sha256")
        self.log.line(f"  matches {step['url']}")

    def do_extract(self, step, on_phase):
        on_phase(f"unpacking {step['name']}")
        archive = self.downloads[f"{step['c']}:{step['name']}"]
        dest = Path(step["dest"])
        os.makedirs(dest.parent, mode=0o700, exist_ok=True)
        self.vdirs_created.append((step["c"], dest))
        extract_archive(archive, step["format"], step["root"], dest)

    def do_make_dir(self, step, on_phase):
        dest = Path(step["dest"])
        os.makedirs(dest.parent, mode=0o700, exist_ok=True)
        os.mkdir(dest, 0o700)
        self.vdirs_created.append((step["c"], dest))

    def do_install_binary(self, step, on_phase):
        on_phase("installing the verified native binary")
        dest = Path(step["dest"])
        os.makedirs(dest, mode=0o700)
        self.vdirs_created.append((step["c"], dest))
        source = self.downloads[f"{step['c']}:{step['name']}"]
        shutil.copyfile(source, dest / step["bin"])
        os.chmod(dest / step["bin"], 0o700)

    def do_copy_lock(self, step, on_phase):
        on_phase("copying the pinned package lock")
        dest = Path(step["dest"])
        os.makedirs(dest, mode=0o700)
        self.vdirs_created.append((step["c"], dest))
        for fname, key in (("package.json", "package_json_sha256"), ("package-lock.json", "package_lock_sha256")):
            data = read_regular(self.catalog.dir / step["lock_dir"] / fname, 4 * 1024 * 1024, fname)
            if hashlib.sha256(data).hexdigest() != step[key]:
                raise ToolError(f"{step['lock_dir']}/{fname} changed since the plan was made; nothing was installed")
            write_atomic(dest / fname, data)

    def do_run(self, step, on_phase):
        cid = step["c"]
        vdir = Path(step["cwd"])
        argv = list(step["argv"])
        if step["kind"] == "script":
            argv[1] = str(self.downloads[f"{cid}:install.sh"])
        on_phase({"npm-ci": "installing the pinned npm packages", "script": "running the pinned installer",
                  "script-step": "running the one allowed install script"}[step["kind"]])
        home = self.sandbox_home(cid, vdir)
        comp = self.catalog.component(cid)
        env = child_env(self.cfg, home, hermes=(cid == "hermes"), node="node" in comp["requires"])
        before = self.external_names(comp)
        if sys.platform == "darwin" and step["kind"] == "script":
            # BSD mktemp -d without a template ignores TMPDIR. Keep the pinned installer
            # intact and provide a private compatibility wrapper within managed state.
            helpers = self.work / "helper-bin"
            helpers.mkdir(mode=0o700, exist_ok=True)
            wrapper = helpers / "mktemp"
            wrapper.write_text('#!/bin/sh\nif [ "$#" -eq 1 ] && [ "$1" = "-d" ]; then\n  exec /usr/bin/mktemp -d "$TMPDIR/hermes-bootstrap.XXXXXXXX"\nfi\nexec /usr/bin/mktemp "$@"\n')
            wrapper.chmod(0o700)
            env["PATH"] = str(helpers) + os.pathsep + env["PATH"]
        code, tail = self.ops.run(argv, vdir, env, step["timeout"], self.log, step["kind"])
        self.record_external(cid, comp, before)
        if code != 0:
            raise ToolError(f"{' '.join(step['argv'][:3])[:80]} failed (exit {code}): {tail[-400:]}")

    def _check_argv(self, step, vdir: Path) -> list[str]:
        comp = self.catalog.component(step["c"])
        first = step["argv"][0]
        names = [b["name"] for b in comp["bins"]]
        if first in names:
            bindir = self.work / "bin"
            os.makedirs(bindir, mode=0o700, exist_ok=True)
            write_wrappers(self.cfg, self.catalog, step["c"], vdir, into=bindir)
            return [str(bindir / first), *step["argv"][1:]]
        return [str(vdir / first), *step["argv"][1:]]

    def do_check(self, step, on_phase):
        on_phase("checking the installed version")
        vdir = Path(step["cwd"])
        argv = self._check_argv(step, vdir)
        comp = self.catalog.component(step["c"])
        env = child_env(self.cfg, self.sandbox_home(step["c"], vdir), hermes=(step["c"] == "hermes"),
                        node="node" in comp.get("requires", []))
        code, out = self.ops.run(argv, vdir, env, RUN_TIMEOUTS["check"], self.log, "check")
        if code != 0 or step["expect"] not in out:
            raise ToolError(f"version check failed: {' '.join(step['argv'])} gave exit {code}, "
                            f"expected {step['expect']!r}: {out[-300:]}")
        self.check_result = {"argv": step["argv"], "output": _last_line(out, step["expect"])}
        self.log.line(f"  version check ok: {self.check_result['output']}")

    def do_activate(self, step, on_phase):
        on_phase("switching to the new version")
        cid, vid = step["c"], step["vid"]
        vdir = self.cfg.version_dir(cid, vid)
        comp = self.catalog.component(cid)
        receipt = {"schema": RECEIPT_SCHEMA, "component": cid, "vid": vid, "version": comp["version"],
                   "fingerprint": self.catalog.fingerprint(cid, self.cfg.platform_key),
                   "installed_at": int(time.time()), "platform": self.cfg.platform_key,
                   "check": self.check_result, "tx": self.txid, "external": self.externals.get(cid, [])}
        write_atomic(vdir / VERSION_RECEIPT, json.dumps(receipt, sort_keys=True, indent=1).encode())
        clash = wrapper_conflicts(self.cfg, [b["name"] for b in comp["bins"]])
        if clash:
            raise ToolError(clash)  # before anything is switched
        flip(self.cfg, cid, vid)
        self.activated.append(cid)
        write_wrappers(self.cfg, self.catalog, cid, self.cfg.comp_dir(cid) / "current")
        prune(self.cfg, self.catalog, cid)

    def do_rollback(self, step, on_phase):
        on_phase("rolling back")
        cid, comp = step["c"], self.catalog.component(step["c"])
        flip_back(self.cfg, cid, step["to_vid"])
        self.activated.append(cid)
        first = step["check"]["argv"][0]
        argv = [str(self.cfg.bin / first) if first in step["bins"] else str(self.cfg.comp_dir(cid) / "current" / first),
                *step["check"]["argv"][1:]]
        vdir = self.cfg.version_dir(cid, step["to_vid"])
        env = child_env(self.cfg, self.sandbox_home(cid, vdir), hermes=(cid == "hermes"), node="node" in comp.get("requires", []))
        code, out = self.ops.run(argv, vdir, env, RUN_TIMEOUTS["check"], self.log, "check")
        receipt = read_receipt(self.cfg, cid, step["to_vid"]) or {}
        expect = receipt.get("version") or comp["check"]["expect"]
        if code != 0 or expect not in out:
            flip_back(self.cfg, cid, step["from_vid"])
            raise ToolError(f"the previous version failed its check ({' '.join(step['check']['argv'])} gave exit {code}), "
                            f"so the current version was put back: {out[-200:]}")
        self.check_result = {"argv": step["check"]["argv"], "output": _last_line(out, expect)}

    def do_remove(self, step, on_phase):
        on_phase(f"removing {step['c']}")
        remove_wrappers(self.cfg, step["bins"])
        remove_externals(self.cfg, self.catalog, step["c"], all_versions=True)
        _safe_rmtree(self.cfg, Path(step["dir"]))


def _last_line(text: str, expect: str = "") -> str:
    """The line of command output worth keeping in a receipt: the one naming the version, else the last one."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    pick = next((ln for ln in lines if expect and expect in ln), lines[-1] if lines else "")
    return pick[:200]


def flip_back(cfg: ToolsConfig, cid: str, vid: str) -> None:
    """Rollback: current <-> previous. Both links are rewritten; each rewrite is atomic."""
    cur = _link(cfg, cid, "current")
    if not read_receipt(cfg, cid, vid):
        raise ToolError("that version is not completely installed")
    _replace_symlink(cfg.comp_dir(cid) / "current", f"versions/{vid}")
    if cur and cur != vid:
        _replace_symlink(cfg.comp_dir(cid) / "previous", f"versions/{cur}")


# --- recovery and the top-level operation ------------------------------------------------------


def recover_stale(cfg: ToolsConfig, state: dict, log: Log) -> dict:
    """A journalled operation whose helper died: remove its unfinished folders and say so."""
    tx = state.get("tx")
    if not tx:
        return state
    log.line(f"recovering interrupted {tx.get('action')} of {tx.get('tool')}")
    for entry in tx.get("partials", []):
        cid, vid = entry["c"], entry["vid"]
        if VID.match(vid) and COMPONENT_ID.match(cid) and read_receipt(cfg, cid, vid) is None:
            path = cfg.version_dir(cid, vid)
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
    for base in (cfg.tmp, cfg.sandbox):
        shutil.rmtree(base / re.sub(r"[^0-9a-f]", "", str(tx.get("id", "x")) or "x"), ignore_errors=True)
    return _finish(cfg, state, "interrupted", "The helper stopped before this finished. Unfinished folders were removed; "
                   "the installed version was not changed.")


def run_action(cfg: ToolsConfig, catalog: Catalog, cid: str, action: str, *, expect_plan_sha256: str | None = None,
               ops: Ops | None = None, facts: HostFacts | None = None, log: Log | None = None) -> dict:
    """Plan, check and run one operation under the lock. Returns the outcome; refusals raise ToolError."""
    ops = ops or Ops()
    log = log or Log(None)
    prepare_layout(cfg)
    with invocation_lock(cfg):
        state = load_state(cfg)
        if state.get("tx"):
            state = recover_stale(cfg, state, log)
        facts = facts or detect_host(cfg.root, _tool_commands(catalog))
        plan = build_plan(cfg, catalog, facts, cid, action)
        if plan["refusals"]:
            log.line("refused: " + "; ".join(plan["refusals"]))
            raise ToolError(plan["refusals"])
        if expect_plan_sha256 is not None and plan["plan_sha256"] != expect_plan_sha256:
            raise ToolError("The plan changed since you confirmed it (the pinned versions or the installed state moved). "
                            "Open the confirmation again to see the new plan.")
        txid = secrets.token_hex(8)
        partials = [{"c": s["c"], "vid": Path(s["dest"]).name} for s in plan["steps"]
                    if s["op"] in ("extract", "copy_lock", "make_dir")]
        state["tx"] = {"id": txid, "tool": cid, "action": action, "from": plan["from"], "to": plan["to"],
                       "phase": "starting", "started_at": int(time.time()), "partials": partials,
                       "plan_sha256": plan["plan_sha256"]}
        save_state(cfg, state)
        log.line(f"== {action} {cid} {plan['from'] or ''} -> {plan['to'] or ''} (plan {plan['plan_sha256'][:12]})")
        ex = Executor(cfg, catalog, ops, log, txid)

        def phase(text: str) -> None:
            state["tx"]["phase"] = text
            save_state(cfg, state)
            log.line(f"-- {text}")

        for entry in partials:  # a folder with no receipt is the leftover of an earlier crash
            stale = cfg.version_dir(entry["c"], entry["vid"])
            if read_receipt(cfg, entry["c"], entry["vid"]) is None and stale.is_dir() and not stale.is_symlink():
                shutil.rmtree(stale, ignore_errors=True)
        try:
            ex.start()
            ex.run_steps(plan["steps"], phase)
            detail = {"install": f"Installed {plan['name']} {plan['to']}.",
                      "update": f"Updated {plan['name']} {plan['from']} to {plan['to']}.",
                      "remove": f"Removed {plan['name']}.", "rollback": f"Rolled {plan['name']} back to {plan['to']}."}[action]
            _finish(cfg, state, "done", detail, check=ex.check_result)
            log.line("== done")
        except BaseException as exc:
            problems = exc.problems if isinstance(exc, ToolError) else [f"{type(exc).__name__}: {str(exc)[:200]}"]
            for c, path in ex.vdirs_created:
                if read_receipt(cfg, c, path.name) is None:
                    shutil.rmtree(path, ignore_errors=True)
                    for made in ex.externals.get(c, []):
                        spec = catalog.component(c).get("external_state") or {}
                        if spec and Path(made).parent == external_root(cfg, spec):
                            shutil.rmtree(made, ignore_errors=True)
            _finish(cfg, state, "failed", "; ".join(problems)[:500] + " The version that was working was not changed.")
            log.line("== failed: " + "; ".join(problems))
            if isinstance(exc, ToolError) or not isinstance(exc, Exception):
                raise
            raise ToolError(problems) from None
        finally:
            ex.cleanup()
    return load_state(cfg)["last"]


# --- status ----------------------------------------------------------------------------


def inspect(cfg: ToolsConfig, catalog: Catalog, facts: HostFacts | None = None) -> dict:
    """Everything the panel shows before any button is pressed. Read-only."""
    facts = facts or detect_host(cfg.root, _tool_commands(catalog))
    layout_ok = os.path.isdir(cfg.root)
    installed = installed_tools(cfg, catalog)
    state = load_state(cfg)
    tools = []
    for cid in catalog.tool_ids():
        comp, view = catalog.component(cid), installed[cid]
        current = view["current"]
        native = native_install(cfg, catalog, facts, cid) if not current else None
        present = bool(current or native)
        native_older = bool(native and version_key(native["version"]) and version_key(comp["version"]) and version_key(native["version"]) < version_key(comp["version"]))
        pinned_fp = catalog.fingerprint(cid, cfg.platform_key)
        if not current:
            default = "update" if native_older else None if native else "install"
        elif current["fingerprint"] != pinned_fp:
            default = "update"
        else:
            default = None
        offered = {"install": not present, "update": default == "update",
                   "remove": bool(view["installed"] or view["versions"]), "rollback": bool(view["previous"])}
        actions = {a: (build_plan(cfg, catalog, facts, cid, a)["refusals"] if offered[a] else None) for a in ACTIONS}
        tools.append({"id": cid, "name": comp["name"], "pinned_version": comp["version"], "installed": present, "installation_source": "managed" if current else "native" if native else None,
                      "installed_version": current["version"] if current else native["version"] if native else None,
                      "previous_version": view["previous"]["version"] if view["previous"] else None,
                      "installed_at": current["installed_at"] if current else None,
                      "size_mb": comp["size_mb"], "login": comp["login"], "requires": comp["requires"],
                      "commands": [b["name"] for b in comp["bins"]], "actions": actions,
                      "path": str(cfg.bin / comp["bins"][0]["name"]) if view["installed"] else native["path"] if native else None})
        tools[-1]["login_command"] = login_command(comp["login"]["command"], tools[-1]["path"])
    all_pkgs = sorted({p for cid in catalog.tool_ids() for k in ("required", "recommended")
                       for p in catalog.component(cid)["system_packages"][k]})
    return {"product": cfg.product, "platform": cfg.platform_key, "root": str(cfg.root), "tools": tools,
            "runtimes": [{"id": r, "name": catalog.component(r)["name"], "pinned_version": catalog.component(r)["version"],
                          "installed_version": installed[r]["current"]["version"] if installed[r]["current"] else None}
                         for r in catalog.raw["runtimes"]],
            "host": {"os": facts.os_name, "machine": facts.machine, "bits": facts.pointer_bits,
                     "disk_free_mb": facts.disk_free_mb, "mem_total_mb": facts.mem_total_mb,
                     "mem_available_mb": facts.mem_available_mb},
            "requirements": catalog.requirements,
            "system_packages": system_package_report(catalog, facts, [], all_pkgs),
            "tx": state.get("tx"), "last": state.get("last"), "running": layout_ok and lock_is_held(cfg),
            "catalog_checked": catalog.raw["checked"]}


def _tool_commands(catalog: Catalog) -> tuple[str, ...]:
    return tuple(b["name"] for cid in catalog.tool_ids() for b in catalog.component(cid)["bins"])


def managed_bin(root: Path | None, name: str) -> str | None:
    """Path of a managed command wrapper if it exists and runs; the app uses this to find installed tools."""
    if root is None:
        return None
    path = root / "bin" / name
    return str(path) if os.path.isfile(path) and os.access(path, os.X_OK) else None
