"""Transactional install engine for verified release packages.

Standard library only and independent of the rest of the app (like release_verify), so the
host helper (update_helper.py) runs it from its own pinned copy outside the version
directories it replaces, and the API can read the same state without importing app code.

Layout under one install root (owner-only, no symlinked components):

    versions/<version>-<artifact sha256[:12]>/   immutable once its receipt is written
    current  -> versions/<id>                   the service runs <root>/current/...
    previous -> versions/<id>                   the version current replaced
    inbox/                                       operator-placed packages, by base name
    helper/                                      pinned helper copy (installed by hand)
    state/install.json                           transaction journal, replaced atomically
    state/lock                                   one invocation at a time (flock)
    state/backups/                               database copy taken before each switch (data-<tx>.db)
                                                 and its metadata (data-<tx>.json: checksum, schema
                                                 revision, helper configuration; never app secrets)
    state/receipts/<tx>.json                     one audit receipt per finished transaction
    state/history.jsonl                          capped outcome log

Every change is journalled before it is made, so recover() can finish or undo an update that
was interrupted at any point. Nothing here stops an agent, job or approval: an update is
refused until they are drained, and the drain check runs again after the service is stopped.
A checkout (dev install) or an unmanaged package gets manual instructions only.

Data is never removed by an update. The database is restored automatically only when its schema is
the one the snapshot was taken on and the older version knows that schema. Otherwise the database
is left as it is, and an operator restores a snapshot with restore_snapshot(), which needs the
snapshot id echoed back because it discards writes made after the snapshot. Profiles, keys, tokens,
reports and logs live outside the root and are never opened here.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import release_verify as rv

STATE_SCHEMA = "dashboard-install-state/v1"
CONFIG_SCHEMA = "dashboard-update-helper/v1"
RECEIPT = ".install-receipt.json"
RUNTIME_DIR = "runtime"
VERSION_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,95}$")  # never "." or ".."
INBOX_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,150}$")
LAUNCHD_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SYSTEMD_UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,120}\.service$")
CONFIG_KEYS = {"schema", "product", "platform", "root", "db_path", "health_url", "service", "python",
               "trust", "readiness_timeout_s", "keep_versions", "allow_prerelease", "allow_downgrade"}
MAX_CONFIG_BYTES = 64 * 1024
MAX_STATE_BYTES = 256 * 1024
MAX_HEALTH_BYTES = 64 * 1024
HISTORY_MAX_BYTES = 256 * 1024
MAX_MIGRATION_BYTES = 256 * 1024
MAX_SNAPSHOT_META_BYTES = 64 * 1024
BACKUP_SCHEMA = "dashboard-data-snapshot/v1"
RECEIPT_SCHEMA = "dashboard-update-receipt/v1"
SNAPSHOT_ID = re.compile(r"^[0-9a-f]{16}$")
MIGRATION_REVISION = re.compile(r"""^revision\s*(?::\s*str\s*)?=\s*["']([0-9A-Za-z_]{1,64})["']""", re.M)
PHASES = ("staging", "prepared", "switching", "starting", "rolling_back", "restoring")
COMMAND_ENV = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}


class UpdateError(Exception):
    """The update was refused or failed. `problems` lists every reason found."""

    def __init__(self, problems: list[str] | str):
        self.problems = [problems] if isinstance(problems, str) else (list(problems) or ["refused"])
        super().__init__("; ".join(self.problems))


# --- configuration ---------------------------------------------------------------------


@dataclass(frozen=True)
class HelperConfig:
    product: str
    platform: str
    root: Path
    db_path: Path
    health_url: str
    service: dict
    python: str
    trust: dict
    readiness_timeout_s: int = 90
    keep_versions: int = 3
    allow_prerelease: bool = False
    allow_downgrade: bool = False

    @property
    def versions(self) -> Path:
        return self.root / "versions"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"


def _absolute(value: object) -> bool:
    return isinstance(value, str) and value.startswith("/") and "\x00" not in value and len(value) < 1024


def _within(child: str, parent: str) -> bool:
    child, parent = os.path.abspath(child), os.path.abspath(parent)
    return os.path.commonpath([child, parent]) == parent


def _loopback_health(url: object) -> bool:
    if not isinstance(url, str):
        return False
    u = urllib.parse.urlsplit(url)
    try:
        port = u.port
    except ValueError:
        return False
    return (u.scheme == "http" and u.hostname in ("127.0.0.1", "::1", "localhost") and port is not None
            and u.path == "/healthz" and not (u.query or u.fragment or u.username or u.password))


def config_problems(raw: object) -> list[str]:
    if not isinstance(raw, dict):
        return ["helper configuration is not an object"]
    problems = []
    need = lambda ok, why: ok or problems.append(why)  # noqa: E731
    need(set(raw) <= CONFIG_KEYS, f"unknown keys: {sorted(set(raw) - CONFIG_KEYS)}")
    need(raw.get("schema") == CONFIG_SCHEMA, f"schema must be {CONFIG_SCHEMA}")
    need((raw.get("product"), raw.get("platform")) in rv.SUPPORTED, "unsupported product/platform")
    for key in ("root", "db_path", "python"):
        need(_absolute(raw.get(key)), f"{key} must be an absolute path")
    if _absolute(raw.get("root")) and _absolute(raw.get("db_path")):
        need(not _within(raw["db_path"], raw["root"]), "db_path must be outside the update root")
    need(_loopback_health(raw.get("health_url")), "health_url must be http://<loopback>:<port>/healthz")
    service = raw.get("service")
    if not isinstance(service, dict):
        problems.append("service must be an object")
    elif service.get("kind") == "launchd":
        need(set(service) == {"kind", "label", "plist"}, "launchd service needs exactly label and plist")
        need(LAUNCHD_LABEL.match(str(service.get("label", ""))), "bad launchd label")
        need(_absolute(service.get("plist")) and str(service.get("plist")).endswith(".plist"), "bad plist path")
    elif service.get("kind") == "systemd-user":
        need(set(service) == {"kind", "unit"}, "systemd-user service needs exactly unit")
        need(SYSTEMD_UNIT.match(str(service.get("unit", ""))), "bad systemd unit name")
    else:
        problems.append("service kind must be launchd or systemd-user")
    trust = raw.get("trust")
    if not isinstance(trust, dict):
        problems.append("trust must be an object")
    elif trust.get("kind") == "ssh-signature":
        need(set(trust) == {"kind", "allowed_signers", "identity"}, "ssh-signature trust needs allowed_signers and identity")
        need(_absolute(trust.get("allowed_signers")), "allowed_signers must be an absolute path")
        need(rv.SIGNER_IDENTITY.match(str(trust.get("identity", ""))), "bad signer identity")
    elif trust.get("kind") == "pinned-digest":
        need(set(trust) == {"kind"}, "pinned-digest trust takes no other keys")
    else:
        problems.append("trust kind must be ssh-signature or pinned-digest")
    timeout = raw.get("readiness_timeout_s", 90)
    need(type(timeout) is int and 10 <= timeout <= 600, "readiness_timeout_s must be 10-600")
    keep = raw.get("keep_versions", 3)
    need(type(keep) is int and 2 <= keep <= 10, "keep_versions must be 2-10")
    for key in ("allow_prerelease", "allow_downgrade"):
        need(type(raw.get(key, False)) is bool, f"{key} must be true or false")
    return problems


def load_config(path: Path | str) -> HelperConfig:
    """Read the helper configuration: a regular, owner-only file owned by this user."""
    try:
        data, st = rv.read_regular(path, MAX_CONFIG_BYTES, "helper configuration")
        raw = rv.strict_json(data, "helper configuration")
    except rv.VerificationError as exc:
        raise UpdateError(exc.problems) from None
    if st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise UpdateError("helper configuration must be owned by this user and not readable by others")
    problems = config_problems(raw)
    if problems:
        raise UpdateError(problems)
    return HelperConfig(
        product=raw["product"], platform=raw["platform"], root=Path(raw["root"]), db_path=Path(raw["db_path"]),
        health_url=raw["health_url"], service=dict(raw["service"]), python=raw["python"], trust=dict(raw["trust"]),
        readiness_timeout_s=raw.get("readiness_timeout_s", 90), keep_versions=raw.get("keep_versions", 3),
        allow_prerelease=raw.get("allow_prerelease", False), allow_downgrade=raw.get("allow_downgrade", False),
    )


def check_private_dir(path: Path, create: bool = False) -> None:
    """A real directory (not a symlink) owned by this user and not writable by others."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        if not create:
            raise UpdateError(f"{path} does not exist") from None
        os.mkdir(path, 0o700)
        st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise UpdateError(f"{path} is not a real directory")
    if st.st_uid != os.geteuid() or st.st_mode & 0o022:
        raise UpdateError(f"{path} must be owned by this user and not writable by group or others")


def prepare_layout(cfg: HelperConfig) -> None:
    check_private_dir(cfg.root)
    for sub in (cfg.versions, cfg.state_dir, cfg.inbox, cfg.state_dir / "backups", cfg.state_dir / "receipts"):
        check_private_dir(sub, create=True)


# --- journal ---------------------------------------------------------------------------


def empty_state() -> dict:
    return {"schema": STATE_SCHEMA, "current": None, "previous": None, "staged": [], "tx": None,
            "last": None, "updated_at": None}


def load_state(cfg: HelperConfig) -> dict:
    path = cfg.state_dir / "install.json"
    if not os.path.lexists(path):
        return empty_state()
    try:
        data, _ = rv.read_regular(path, MAX_STATE_BYTES, "install state")
        state = rv.strict_json(data, "install state")
    except rv.VerificationError as exc:
        raise UpdateError(["install state is unreadable; inspect it by hand"] + exc.problems) from None
    if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA:
        raise UpdateError("install state has an unknown format; inspect it by hand")
    return {**empty_state(), **state}


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
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


def save_state(cfg: HelperConfig, state: dict, now: float | None = None) -> dict:
    state["updated_at"] = int(now if now is not None else time.time())
    _write_atomic(cfg.state_dir / "install.json", json.dumps(state, sort_keys=True, indent=1).encode())
    return state


def _history(cfg: HelperConfig, entry: dict) -> None:
    path = cfg.state_dir / "history.jsonl"
    try:
        if os.path.getsize(path) > HISTORY_MAX_BYTES:
            os.replace(path, path.with_suffix(".jsonl.1"))
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as out:
        out.write(json.dumps(entry, sort_keys=True) + "\n")


def _receipt(cfg: HelperConfig, last: dict) -> None:
    """Small audit record of one finished transaction. Written atomically, owner-only."""
    receipt = {"schema": RECEIPT_SCHEMA, "product": cfg.product, "platform": cfg.platform, "outcome": last}
    _write_atomic(cfg.state_dir / "receipts" / f"{last.get('tx') or secrets.token_hex(8)}.json",
                  json.dumps(receipt, sort_keys=True, indent=1).encode())


def _finish(cfg: HelperConfig, state: dict, outcome: str, detail: str, **extra) -> dict:
    tx = state.get("tx") or {}
    state["last"] = {"tx": tx.get("id"), "kind": tx.get("kind"), "outcome": outcome, "detail": detail[:500],
                     "target": tx.get("target"), "from": tx.get("from"), "at": int(time.time()), **extra}
    state["tx"] = None
    save_state(cfg, state)
    _history(cfg, state["last"])
    _receipt(cfg, state["last"])
    OperationLog.attach(cfg).on_finish(tx, outcome, detail)
    return state


# --- operation record -------------------------------------------------------------------
# A private, best-effort record of one update that the Updates page reads: ordered steps with their state, and a plain log. It never
# affects the update: every write is wrapped, and a failure to record is ignored. The page also works without it (older helpers).

OP_STEPS = ("fetch", "verify", "stage", "safety", "snapshot", "switch", "health", "finish")
OP_FINAL = ("succeeded", "rolled_back", "failed")
OP_MAX_LOG = 200_000
OP_REUSE_S = 30 * 60


class OperationLog:
    def __init__(self, cfg: HelperConfig):
        self.cfg, self.data = cfg, None
        self.path, self.log_path = cfg.state_dir / "operation.json", cfg.state_dir / "operation.log"

    @classmethod
    def begin(cls, cfg: HelperConfig, version: str) -> "OperationLog":
        """Start recording an update to `version`, or carry on with the one that staged it a moment ago."""
        op = cls(cfg)
        try:
            current = op._read()
            now = int(time.time())
            if current and current.get("version") == version and current.get("state") in ("running", "staged") and now - int(current.get("updated_at") or 0) < OP_REUSE_S:
                op.data = current
                op.data.update(state="running", message="")
            else:
                op.data = {"id": secrets.token_hex(4), "version": version, "state": "running", "message": "", "steps": [], "started_at": now, "updated_at": now}
                fd = os.open(op.log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            op._save()
        except Exception:  # noqa: BLE001 - recording never affects an update
            op.data = None
        return op

    @classmethod
    def attach(cls, cfg: HelperConfig) -> "OperationLog":
        """The record in progress, if any (used where only the transaction is at hand)."""
        op = cls(cfg)
        try:
            current = op._read()
            op.data = current if current and current.get("state") in ("running", "staged") else None
        except Exception:  # noqa: BLE001
            op.data = None
        return op

    def _read(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _save(self) -> None:
        self.data["updated_at"] = int(time.time())
        tmp = self.path.with_name(f"operation.json.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(self.data, handle, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def step(self, name: str, state: str, detail: str = "") -> None:
        if self.data is None:
            return
        try:
            steps = [s for s in self.data["steps"] if s["name"] != name]
            steps.append({"name": name, "state": state, "detail": detail[:300], "at": int(time.time())})
            self.data["steps"] = sorted(steps, key=lambda s: OP_STEPS.index(s["name"]) if s["name"] in OP_STEPS else 99)
            self.write_log(f"{name}: {state}{' - ' + detail if detail else ''}")
            self._save()
        except Exception:  # noqa: BLE001
            pass

    def write_log(self, text: str) -> None:
        if self.data is None:
            return
        try:
            if self.log_path.stat().st_size > OP_MAX_LOG:
                return
            fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "a") as handle:
                handle.write(f"{time.strftime('%H:%M:%S')}  {text[:300]}\n")
        except Exception:  # noqa: BLE001
            pass

    def finish(self, state: str, message: str) -> None:
        if self.data is None or self.data.get("state") in OP_FINAL:
            return
        try:
            self.data.update(state=state, message=message[:300], finished_at=int(time.time()))
            self.write_log(f"result: {state} - {message}")
            self._save()
        except Exception:  # noqa: BLE001
            pass

    def on_finish(self, tx: dict, outcome: str, detail: str) -> None:
        """Called when a transaction ends, so every way of ending is reflected, including rollbacks and aborts."""
        if self.data is None:
            return
        kind = (tx or {}).get("kind")
        if kind == "stage":
            if outcome == "staged":
                self.step("stage", "ok", detail)
                self.data["state"], self.data["message"] = "staged", "Verified and staged. It is not installed until you install it."
                self.write_log("staged: not installed yet")
                self._save()
            else:
                self.step("stage", "failed", detail)
                self.finish("failed", detail)
        elif kind == "switch":
            if outcome == "committed":
                self.step("health", "ok", detail)
                self.step("finish", "ok", detail)
                self.finish("succeeded", detail)
            elif outcome == "rolled_back":
                self.step("health", "failed", detail)
                self.step("finish", "failed", "rolled back to the previous version")
                self.finish("rolled_back", "The new version did not pass its health check and the previous version was restored. " + detail)
            else:
                self.step("switch", "failed", detail)
                self.finish("failed", detail)


HELPER_FILES = ("update_helper.py", "update_engine.py", "release_fetch.py", "release_verify.py", "update_recovery.py")


def refresh_helper(cfg: HelperConfig, source: Path | None = None) -> dict:
    """Bring the pinned helper copy up to the code of the current, sealed version, on the operator's explicit command.

    An update never replaces the helper (that is the point of pinning it), so a host installed with an older helper keeps its old
    behaviour until this is run. The source must be the current version's own apps/api folder, whose package was verified and sealed
    when it was staged; the old copies are kept in helper/previous."""
    prepare_layout(cfg)
    with invocation_lock(cfg):
        _require_no_tx(load_state(cfg))
        current = _link_target(cfg, "current")
        if not current or not read_receipt(cfg, current):
            raise UpdateError("no managed current version to take the helper from")
        src = Path(source) if source else cfg.versions / current / "apps" / "api"
        expected = (cfg.versions / current / "apps" / "api").resolve()
        if src.resolve() != expected:
            raise UpdateError("the helper can only be refreshed from the current version's own apps/api folder")
        helper_dir = cfg.root / "helper"
        check_private_dir(helper_dir)
        previous = helper_dir / "previous"
        previous.mkdir(mode=0o700, exist_ok=True)
        changed = []
        for name in HELPER_FILES:
            data, _ = rv.read_regular(src / name, 2 * 1024 * 1024, f"{name} of the current version")
            target = helper_dir / name
            old = target.read_bytes() if target.is_file() else None
            if old == data:
                continue
            if old is not None:
                _write_private(previous / name, old)
            _write_private(target, data)
            changed.append(name)
        return {"refreshed": changed, "from": current, "kept_previous_in": str(previous)}


def operation_status(cfg: HelperConfig, log_lines: int = 80) -> dict:
    """What the Updates page shows: the latest operation record, whether a helper is working right now, and the log tail.
    A record still marked running while no helper holds the lock is reported as failed instead of spinning forever."""
    op = OperationLog(cfg)
    data = op._read()
    active = False
    try:
        fd = os.open(cfg.state_dir / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            active = True
        finally:
            os.close(fd)
    except OSError:
        pass
    if data and data.get("state") == "running" and not active and time.time() - int(data.get("updated_at") or 0) > 20:
        data = {**data, "state": "failed", "message": "The update helper stopped without reporting a result. Check the log, then recovery on the host."}
    lines: list[str] = []
    if data:
        try:
            lines = [line[:300] for line in op.log_path.read_text(errors="replace").splitlines()[-log_lines:]]
        except OSError:
            pass
    return {"operation": data, "active": active, "log": lines}


@contextmanager
def invocation_lock(cfg: HelperConfig) -> Iterator[None]:
    """One helper invocation at a time. The kernel releases it if the holder dies."""
    fd = os.open(cfg.state_dir / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateError("another update or recovery is in progress") from None
        yield
    finally:
        os.close(fd)


# --- versions --------------------------------------------------------------------------


def version_id(release: rv.VerifiedRelease) -> str:
    vid = f"{release.version}-{release.artifact_sha256[:12]}"
    if not VERSION_ID.match(vid):
        raise UpdateError("release version cannot name a version directory")
    return vid


def read_receipt(cfg: HelperConfig, vid: str) -> dict | None:
    """The receipt of a completely staged version, or None if it is partial or tampered."""
    if not isinstance(vid, str) or not VERSION_ID.match(vid):
        return None
    try:
        data, st = rv.read_regular(cfg.versions / vid / RECEIPT, MAX_CONFIG_BYTES, "install receipt")
        receipt = rv.strict_json(data, "install receipt")
    except rv.VerificationError:
        return None
    if (st.st_mode & 0o222 or not isinstance(receipt, dict) or receipt.get("id") != vid
            or receipt.get("product") != cfg.product or receipt.get("platform") != cfg.platform):
        return None
    return receipt


def _link_target(cfg: HelperConfig, name: str) -> str | None:
    """Version id a root symlink points at, or None when absent or not a version link."""
    try:
        target = os.readlink(cfg.root / name)
    except (FileNotFoundError, OSError):
        return None
    parts = target.split("/")
    return parts[1] if len(parts) == 2 and parts[0] == "versions" and VERSION_ID.match(parts[1]) else None


def _point(cfg: HelperConfig, name: str, vid: str | None) -> None:
    """Atomically repoint root/<name> at versions/<vid> (or remove it): rename over the old link."""
    link = cfg.root / name
    if vid is None:
        try:
            os.unlink(link)
        except FileNotFoundError:
            pass
        _fsync_dir(cfg.root)
        return
    if not (cfg.versions / vid).is_dir():
        raise UpdateError(f"version {vid} is not staged")
    tmp = cfg.root / f".{name}.{secrets.token_hex(6)}"
    os.symlink(f"versions/{vid}", tmp)
    try:
        os.replace(tmp, link)  # rename(2): readers see the old or the new link, never neither
    except BaseException:
        os.unlink(tmp)
        raise
    _fsync_dir(cfg.root)


def _walk_modes(path: Path, writable: bool) -> None:
    """Seal (read-only) or unseal a version tree without following symlinks."""
    def mode(st_mode: int) -> int:
        base = stat.S_IMODE(st_mode)
        return (base | stat.S_IWUSR) if writable else (base & ~0o222)
    if writable:
        os.chmod(path, mode(os.lstat(path).st_mode))
    for top, dirs, files, top_fd in os.fwalk(path, follow_symlinks=False):
        for name in dirs + files:
            st = os.lstat(name, dir_fd=top_fd)
            if stat.S_ISLNK(st.st_mode):
                continue
            os.chmod(name, mode(st.st_mode), dir_fd=top_fd)
    if not writable:
        os.chmod(path, mode(os.lstat(path).st_mode))


def remove_version(cfg: HelperConfig, vid: str) -> None:
    if not VERSION_ID.match(vid) or vid in (_link_target(cfg, "current"), _link_target(cfg, "previous")):
        raise UpdateError(f"refusing to remove version {vid}")
    path = cfg.versions / vid
    if not os.path.lexists(path):
        return
    if not stat.S_ISDIR(os.lstat(path).st_mode):
        os.unlink(path)
        return
    _walk_modes(path, writable=True)
    if not shutil.rmtree.avoids_symlink_attacks:
        raise UpdateError("this platform has no symlink-safe tree removal; remove the version by hand")
    shutil.rmtree(path)


def _run(argv: list[str], timeout: int, env: dict | None = None, what: str = "command") -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                env=env or dict(COMMAND_ENV), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"{what} could not run ({type(exc).__name__})") from None
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        raise UpdateError(f"{what} failed (exit {result.returncode}): {' | '.join(tail)[:400]}")
    return result.stdout


def build_runtime(cfg: HelperConfig, app_dir: Path, release: rv.VerifiedRelease) -> None:
    """Create <version>/runtime and install the release lock: exact versions, sha256 hashes,
    prebuilt wheels only and no dependency resolution, so no package build script runs."""
    if not os.path.isfile(cfg.python):
        raise UpdateError("the configured Python interpreter does not exist")
    have = _run([cfg.python, "-I", "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], 30,
                what="Python version check").strip()
    if have != release.manifest["runtime"]["python"]:
        raise UpdateError(f"release needs Python {release.manifest['runtime']['python']}, the helper has {have}")
    venv = app_dir / RUNTIME_DIR
    _run([cfg.python, "-I", "-m", "venv", str(venv)], 300, what="runtime creation")
    env = {**COMMAND_ENV, "HOME": str(Path.home()), "PIP_CONFIG_FILE": os.devnull, "PIP_NO_INPUT": "1"}
    _run([str(venv / "bin" / "python"), "-I", "-m", "pip", "install", "--disable-pip-version-check",
          "--no-cache-dir", "--require-hashes", "--only-binary", ":all:", "--no-deps",
          "-r", str(app_dir / "apps" / "api" / "requirements.release.txt")], 1800, env, "dependency install")
    _run([str(venv / "bin" / "python"), "-I", "-m", "compileall", "-q", str(app_dir / "apps" / "api")], 300,
         what="byte compilation")


RuntimeBuilder = Callable[[HelperConfig, Path, rv.VerifiedRelease], None]


# --- trust -----------------------------------------------------------------------------


def authenticator(cfg: HelperConfig, manifest_sha256: str | None = None) -> rv.Authenticator:
    if cfg.trust["kind"] == "ssh-signature":
        return rv.SshSignature(Path(cfg.trust["allowed_signers"]), cfg.trust["identity"])
    if not manifest_sha256:
        raise UpdateError("enter the manifest sha256 from the release page to stage this package")
    try:
        return rv.PinnedDigest(manifest_sha256, "operator-entered release digest")
    except ValueError as exc:
        raise UpdateError(str(exc)) from None


def inbox_paths(cfg: HelperConfig, name: str) -> tuple[Path, Path, Path | None]:
    if not isinstance(name, str) or not INBOX_NAME.match(name) or ".." in name:
        raise UpdateError("package name must be a plain release base name from the inbox")
    manifest, artifact = cfg.inbox / f"{name}.manifest.json", cfg.inbox / f"{name}.tar.gz"
    signature = cfg.inbox / f"{name}.manifest.json.sig"
    return manifest, artifact, signature if os.path.lexists(signature) else None


# --- drain -----------------------------------------------------------------------------

# Tasks an update would interrupt: running ones, and queued ones that could start (a project story only while its project is active).
BLOCKING_TASKS = ("c.\"column\" IN ('queued', 'running') AND NOT (c.\"column\" = 'queued' AND EXISTS "
                  "(SELECT 1 FROM project_task t JOIN project p ON p.id = t.project_id WHERE t.card_id = c.id AND p.state NOT IN ('dispatching', 'active')))")

DRAIN_COUNTS = (
    ("SELECT count(*) FROM run WHERE ended_at IS NULL", "agent runs",
     "{n} agent or chat run(s) still running: let them finish or cancel them"),
    # A run left in awaiting_approval on a story that is already done or failed has nothing left to decide
    # (a later run completed it); only waits on stories still open, or on no story at all, block an update.
    ("SELECT count(*) FROM run r LEFT JOIN card c ON c.id = r.card_id WHERE r.stage = 'awaiting_approval' "
     "AND (c.id IS NULL OR c.\"column\" NOT IN ('done', 'failed'))", "approval waits",
     "{n} run(s) waiting on a human decision: decide or reject them first"),
    # A queued project story starts only while its project is active (projects.claim_context), so a queued story of a project in any
    # other state (paused, closed, complete, waiting for review, failed) is not work an update would interrupt. Project stories cannot be
    # moved to Backlog by hand, so counting them would block every update until each such project was closed.
    ("SELECT count(*) FROM card c WHERE " + BLOCKING_TASKS, "queued tasks",
     "{n} task(s) queued or running: let them finish or move them to Backlog"),
    ("SELECT count(*) FROM project WHERE state IN ('dispatching', 'active')", "projects",
     "{n} project(s) in progress: pause them (Pause dispatch, or Pause these projects for the update below) and resume them afterwards; queued stories of a paused project do not block an update"),
)


def drain_blockers(db_path: Path, now: float | None = None) -> list[str]:
    """Work that an update would interrupt. Read-only; any failure to check is a blocker."""
    now = int(now if now is not None else time.time())
    blockers: list[str] = []
    try:
        uri = "file:" + urllib.parse.quote(str(db_path)) + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as exc:
        return [f"the task database could not be opened read-only ({type(exc).__name__})"]
    try:
        for sql, what, message in DRAIN_COUNTS:
            try:
                n = int(con.execute(sql).fetchone()[0])
            except sqlite3.Error as exc:
                blockers.append(f"could not check {what} ({type(exc).__name__})")
                continue
            if n:
                text = message.format(n=n)
                if what == "queued tasks":
                    # Name them, so the operator knows where to look instead of guessing (at most five).
                    try:
                        rows = con.execute("SELECT c.id, c.title, c.\"column\" FROM card c WHERE " + BLOCKING_TASKS + " ORDER BY c.id LIMIT 5").fetchall()
                        text += ": " + "; ".join(f"#{i} {str(t)[:60]} ({col})" for i, t, col in rows) + (" and more" if n > 5 else "")
                    except sqlite3.Error:
                        pass
                blockers.append(text)
        # The current task schema represents approval with ``needs_approval`` and
        # ``approved_at``; it has never contained the historical ``approval_grant``
        # column. Approved work is already blocked above while it is queued or
        # running, so querying that retired column would fail closed and make every
        # managed update impossible.
    finally:
        con.close()
    return blockers


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_revision(db_path: Path) -> str | None:
    """Migration revision the database is on, or None when it has no migration table yet. Read-only.
    Any failure to read raises: an unknown schema must never look like an empty one."""
    if not os.path.lexists(db_path):
        return None
    uri = "file:" + urllib.parse.quote(str(db_path)) + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise UpdateError(f"the schema revision could not be read ({type(exc).__name__})") from None
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'").fetchone():
            return None
        rows = con.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.Error as exc:
        raise UpdateError(f"the schema revision could not be read ({type(exc).__name__})") from None
    finally:
        con.close()
    if len(rows) > 1:
        raise UpdateError("the schema revision table is ambiguous")
    return str(rows[0][0]) if rows else None


def known_revisions(version_dir: Path) -> set[str]:
    """Migration revisions a version understands, read from its own sealed migration files."""
    folder = version_dir / "apps" / "api" / "migrations" / "versions"
    if not folder.is_dir():
        return set()
    revisions: set[str] = set()
    for name in os.listdir(folder):
        if not name.endswith(".py"):
            continue
        try:
            data, _ = rv.read_regular(folder / name, MAX_MIGRATION_BYTES, "migration")
        except rv.VerificationError as exc:
            raise UpdateError(exc.problems) from None
        match = MIGRATION_REVISION.search(data.decode("utf-8", "replace"))
        if match:
            revisions.add(match.group(1))
    return revisions


def schema_compatible(revision: str | None, revisions: set[str]) -> bool:
    """A database with no migration table yet, or one on a revision the version knows, can run on it."""
    return revision is None or revision in revisions


def config_snapshot(cfg: HelperConfig) -> dict:
    """Helper configuration at snapshot time. The schema allows only paths, service names, trust
    identities and numbers, so this holds no secret and is copied as it is."""
    return {"product": cfg.product, "platform": cfg.platform, "root": str(cfg.root), "db_path": str(cfg.db_path),
            "health_url": cfg.health_url, "service": dict(cfg.service), "python": cfg.python,
            "trust": dict(cfg.trust), "readiness_timeout_s": cfg.readiness_timeout_s,
            "keep_versions": cfg.keep_versions, "allow_prerelease": cfg.allow_prerelease,
            "allow_downgrade": cfg.allow_downgrade}


def backup_database(cfg: HelperConfig, tx_id: str, from_vid: str | None = None) -> dict | None:
    """Consistent copy of the (stopped, drained) database plus its metadata, kept for rollback.
    Only the database file is read from the data folder; nothing else there is opened."""
    if not cfg.db_path.exists():
        return None
    dest = cfg.state_dir / "backups" / f"data-{tx_id}.db"
    src = sqlite3.connect("file:" + urllib.parse.quote(str(cfg.db_path)) + "?mode=ro", uri=True, timeout=10)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    with open(dest, "rb") as fh:
        os.fsync(fh.fileno())
    meta = {"schema": BACKUP_SCHEMA, "tx": tx_id, "created_at": int(time.time()), "file": dest.name,
            "bytes": dest.stat().st_size, "sha256": _sha256(dest),
            "schema_revision": database_revision(dest),  # read from the copy, the file that will be restored
            "from": from_vid, "from_version": (read_receipt(cfg, from_vid) or {}).get("version") if from_vid else None,
            "config": config_snapshot(cfg)}
    _write_atomic(dest.with_suffix(".json"), json.dumps(meta, sort_keys=True, indent=1).encode())
    return {**meta, "path": str(dest)}


def load_snapshot(cfg: HelperConfig, tx_id: str) -> dict:
    """Metadata of a kept snapshot. Refuses an id that does not name exactly one snapshot file."""
    if not isinstance(tx_id, str) or not SNAPSHOT_ID.match(tx_id):
        raise UpdateError("snapshot id must be the 16-character id printed by the update")
    try:
        data, _ = rv.read_regular(cfg.state_dir / "backups" / f"data-{tx_id}.json", MAX_SNAPSHOT_META_BYTES,
                                  "snapshot metadata")
        meta = rv.strict_json(data, "snapshot metadata")
    except rv.VerificationError as exc:
        raise UpdateError(["snapshot not found (it may have been pruned)"] + exc.problems) from None
    if (not isinstance(meta, dict) or meta.get("schema") != BACKUP_SCHEMA or meta.get("tx") != tx_id
            or meta.get("file") != f"data-{tx_id}.db"):
        raise UpdateError("snapshot metadata does not match its id")
    return meta


def snapshots(cfg: HelperConfig, limit: int = 20) -> list[dict]:
    """Newest kept snapshots, for display. Read-only."""
    folder = cfg.state_dir / "backups"
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("data-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            meta = load_snapshot(cfg, path.stem[len("data-"):])
        except UpdateError:
            continue
        found.append({k: meta.get(k) for k in ("tx", "created_at", "schema_revision", "bytes", "from_version")})
    return found


def restore_database(cfg: HelperConfig, backup: str | None, sha256: str | None = None) -> bool:
    """Put a snapshot back over the database. Only called while the service is stopped. The copy is
    checked against its recorded checksum before it replaces anything."""
    if not backup:
        return False
    src = Path(backup)
    if src.parent != cfg.state_dir / "backups" or not src.is_file():
        raise UpdateError("the database snapshot is missing; restore by hand")
    tmp = cfg.db_path.with_name(f".{cfg.db_path.name}.restore")
    shutil.copyfile(src, tmp, follow_symlinks=False)
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    if sha256 is not None and _sha256(tmp) != sha256:
        os.unlink(tmp)
        raise UpdateError("the database snapshot failed its checksum; the database was not changed")
    for suffix in ("-wal", "-shm"):
        try:
            os.unlink(f"{cfg.db_path}{suffix}")
        except FileNotFoundError:
            pass
    os.replace(tmp, cfg.db_path)
    _fsync_dir(cfg.db_path.parent)
    return True


def prune_backups(cfg: HelperConfig, keep: int) -> None:
    backups = sorted((cfg.state_dir / "backups").glob("data-*.db"), key=lambda p: p.stat().st_mtime)
    for old in backups[:-keep] if keep else backups:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)


# --- service control -------------------------------------------------------------------


class ServiceControl:
    """Stop and start the dashboard service. Fixed argv, system binaries, minimal env."""

    def stop(self) -> None: raise NotImplementedError
    def start(self) -> None: raise NotImplementedError


class LaunchdService(ServiceControl):
    LAUNCHCTL = "/bin/launchctl"

    def __init__(self, label: str, plist: str):
        self.target = f"gui/{os.getuid()}/{label}"
        self.domain = f"gui/{os.getuid()}"
        self.plist = plist

    def loaded(self) -> bool:
        try:
            return subprocess.run([self.LAUNCHCTL, "print", self.target], capture_output=True, timeout=15,
                                  env=dict(COMMAND_ENV), stdin=subprocess.DEVNULL).returncode == 0
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(f"launchctl could not run ({type(exc).__name__})") from None

    def stop(self) -> None:
        if not self.loaded():
            return
        try:
            subprocess.run([self.LAUNCHCTL, "bootout", self.target], capture_output=True, timeout=60,
                           env=dict(COMMAND_ENV), stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(f"launchctl could not run ({type(exc).__name__})") from None
        deadline = time.monotonic() + 60
        while self.loaded():  # bootout returns before launchd finishes tearing the job down
            if time.monotonic() > deadline:
                raise UpdateError("the service did not stop within 60 s")
            time.sleep(0.5)

    def start(self) -> None:
        if self.loaded():
            _run([self.LAUNCHCTL, "kickstart", self.target], 30, what="service start")
        else:
            _run([self.LAUNCHCTL, "bootstrap", self.domain, self.plist], 60, what="service start")


class SystemdUserService(ServiceControl):
    def __init__(self, unit: str):
        self.unit = unit
        self.systemctl = next((p for p in ("/usr/bin/systemctl", "/bin/systemctl") if os.path.isfile(p)), None)

    def _env(self) -> dict:
        env = dict(COMMAND_ENV)
        for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def _call(self, verb: str) -> None:
        if not self.systemctl:
            raise UpdateError("systemctl is not available at a system path")
        _run([self.systemctl, "--user", verb, self.unit], 120, self._env(), f"service {verb}")

    def stop(self) -> None:
        self._call("stop")

    def start(self) -> None:
        # A release that crash-looped leaves the unit failed with its start-rate limit used up, and the
        # rollback's own start would then be refused ("repeated too quickly"). Clear the counter first.
        try:
            self._call("reset-failed")
        except UpdateError:
            pass
        self._call("start")


def service_for(cfg: HelperConfig) -> ServiceControl:
    if cfg.service["kind"] == "launchd":
        return LaunchdService(cfg.service["label"], cfg.service["plist"])
    return SystemdUserService(cfg.service["unit"])


# --- readiness -------------------------------------------------------------------------


def health_readiness(cfg: HelperConfig, version: str, started: float) -> tuple[bool, str]:
    """Poll the public health endpoint until the expected version answers healthy and fresh."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + cfg.readiness_timeout_s
    detail = "no answer"
    while True:
        try:
            with opener.open(cfg.health_url, timeout=3) as resp:
                body = json.loads(resp.read(MAX_HEALTH_BYTES + 1)[:MAX_HEALTH_BYTES])
            uptime = body.get("uptime_s")
            if body.get("status") != "ok":
                detail = "health status is not ok"
            elif body.get("version") != version:
                detail = f"health reports version {str(body.get('version'))[:40]}, expected {version}"
            elif not (isinstance(uptime, (int, float)) and uptime <= time.time() - started + 5):
                detail = "the answering process predates the restart"
            elif body.get("web_built") is not True or body.get("data_dir_writable") is not True:
                detail = "web build or data folder is not ready"
            else:
                return True, f"version {version} healthy"
        except (OSError, ValueError, AttributeError) as exc:
            detail = f"health check failed ({type(exc).__name__})"
        if time.monotonic() >= deadline:
            return False, detail
        time.sleep(1)


Readiness = Callable[[HelperConfig, str, float], "tuple[bool, str]"]


# --- install kind and status (read-only; used by the API) -------------------------------


def install_kind(app_root: Path, root: Path | None) -> tuple[str, str]:
    """release: a packaged version under the configured root; dev: a source checkout or a
    dev/dirty build; unmanaged: a package not run from the configured root."""
    if (app_root / ".git").exists():
        return "dev", "this is a source checkout"
    try:
        info = json.loads((app_root / "BUILD_INFO.json").read_text())
    except (OSError, ValueError):
        return "dev", "no release build information"
    if not isinstance(info, dict) or info.get("channel") not in ("stable", "prerelease") or info.get("source_dirty"):
        return "dev", "a development or dirty build"
    if root is None:
        return "unmanaged", "no update root is configured"
    try:
        if app_root.resolve().parent != (root / "versions").resolve():
            return "unmanaged", "not running from the update root"
    except OSError:
        return "unmanaged", "the update root is not readable"
    return "release", f"packaged version {info.get('version')}"


def manual_instructions(kind: str, product: str) -> list[str]:
    service = "systemctl --user restart rcd-api" if product == "rcd" else "scripts/install-launchagent.sh"
    if kind == "release":
        return []
    steps = ["Automatic updates are off for this install. Update it by hand:",
             "1. Let running tasks finish, pause active projects and move queued tasks to Backlog.",
             "2. Back up the data folder (it holds data.db).",
             "3. In the checkout, review and commit or stash local changes, then fetch the reviewed release tag.",
             "4. Run scripts/bootstrap.sh to rebuild the API environment and web app.",
             f"5. Restart the service ({service}) and check /healthz reports the new version."]
    if kind == "unmanaged":
        steps.append("To enable managed updates, set up an update root as described in packaging/README.md.")
    return steps


def status(cfg: HelperConfig) -> dict:
    """State for display. Takes no lock; the journal is replaced atomically."""
    state = load_state(cfg)
    versions = []
    if cfg.versions.is_dir():
        for entry in sorted(os.listdir(cfg.versions)):
            receipt = read_receipt(cfg, entry)
            versions.append({"id": entry, "complete": receipt is not None,
                             "version": receipt.get("version") if receipt else None,
                             "channel": receipt.get("channel") if receipt else None,
                             "change": receipt.get("change") if receipt else None,
                             "repository": receipt.get("repository") if receipt else None,
                             "authenticity": receipt.get("authenticity") if receipt else None,
                             "staged_at": receipt.get("staged_at") if receipt else None})
    return {"current": _link_target(cfg, "current"), "previous": _link_target(cfg, "previous"),
            "versions": versions, "tx": state["tx"], "last": state["last"], "snapshots": snapshots(cfg),
            "needs_recovery": state["tx"] is not None}


# --- trust ------------------------------------------------------------------------------

SIGNER_NAMESPACE = "dashboard-release"
KEY_TYPES = ("ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521", "ssh-rsa")
FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")


def signer_fingerprints(signers: bytes) -> list[str]:
    """Fingerprints of the keys an allowed_signers file trusts, read with the system ssh-keygen.
    Anything that is not one plain line for the release signer in the release namespace is refused."""
    ssh_keygen = next((c for c in rv.SshSignature.CANDIDATES if os.path.isfile(c)), None)
    if not ssh_keygen:
        raise UpdateError("ssh-keygen is not available, so the release key cannot be checked")
    lines = [line.strip() for line in signers.decode("utf-8", "replace").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise UpdateError("the allowed signers file has no key")
    prints = []
    for line in lines:
        parts = line.split()
        key_at = next((i for i, part in enumerate(parts) if part in KEY_TYPES), None)
        if key_at is None or key_at + 1 >= len(parts) or key_at == 0:
            raise UpdateError("the allowed signers file has a line that is not a signer and a public key")
        principals, options = parts[0], " ".join(parts[1:key_at])
        if not rv.SIGNER_IDENTITY.match(principals) or f'namespaces="{SIGNER_NAMESPACE}"' not in options:
            raise UpdateError(f'every signer must be limited to namespaces="{SIGNER_NAMESPACE}"')
        with tempfile.TemporaryDirectory(prefix="signer-key-") as tmp:
            pub = Path(tmp) / "key.pub"
            pub.write_text(f"{parts[key_at]} {parts[key_at + 1]}\n")
            result = subprocess.run([ssh_keygen, "-l", "-f", str(pub)], capture_output=True, text=True, timeout=15,
                                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        found = re.search(r"\b(SHA256:[A-Za-z0-9+/]{43})\b", result.stdout)
        if result.returncode or not found:
            raise UpdateError("a public key in the allowed signers file could not be read")
        prints.append(found.group(1))
    return prints


def _write_private(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def enable_signed_updates(config_path: Path, cfg: HelperConfig, source: Path, fingerprint: str) -> dict:
    """Switch this host from a pasted digest to the release signature, as an explicit operator decision.

    The operator names the key by its fingerprint (published beside each release); the key file is copied
    into the helper folder, where no update can replace it, and helper.json is rewritten to use it.
    Nothing is switched while an update is in progress."""
    if not FINGERPRINT.match(fingerprint or ""):
        raise UpdateError("pass the release key fingerprint as SHA256:<43 characters>")
    prepare_layout(cfg)
    try:
        signers, _ = rv.read_regular(source, 64 * 1024, "allowed signers file")
    except rv.VerificationError as exc:
        raise UpdateError(exc.problems) from None
    prints = signer_fingerprints(signers)
    if prints != [fingerprint]:
        raise UpdateError([f"the key in that file is {', '.join(prints)}, not {fingerprint}; nothing was changed"])
    with invocation_lock(cfg):
        _require_no_tx(load_state(cfg))
        raw_bytes, _ = rv.read_regular(config_path, MAX_CONFIG_BYTES, "helper configuration")
        raw = rv.strict_json(raw_bytes, "helper configuration")
        target = Path(config_path).resolve().parent / "allowed_signers"
        raw["trust"] = {"kind": "ssh-signature", "allowed_signers": str(target), "identity": "dashboard-release"}
        problems = config_problems(raw)
        if problems:
            raise UpdateError(problems)
        _write_private(target, signers)
        _write_private(Path(config_path), (json.dumps(raw, indent=2, sort_keys=True) + "\n").encode())
    return {"trust": "ssh-signature", "fingerprint": fingerprint, "allowed_signers": str(target)}


# --- operations (helper only; each takes the invocation lock) ---------------------------


def _require_no_tx(state: dict) -> None:
    if state.get("tx"):
        raise UpdateError("an earlier update was interrupted; run recovery first")


def stage(cfg: HelperConfig, name: str, manifest_sha256: str | None = None,
          builder: RuntimeBuilder = build_runtime) -> dict:
    """Verify an inbox package and install it as a new immutable version directory."""
    prepare_layout(cfg)
    with invocation_lock(cfg):
        state = load_state(cfg)
        _require_no_tx(state)
        current = _link_target(cfg, "current")
        installed = (read_receipt(cfg, current) or {}).get("version") if current else None
        manifest, artifact, signature = inbox_paths(cfg, name)
        policy = rv.TrustPolicy(product=cfg.product, platform=cfg.platform,
                                authenticator=authenticator(cfg, manifest_sha256), installed_version=installed,
                                allow_prerelease=cfg.allow_prerelease, allow_downgrade=cfg.allow_downgrade)
        op = None
        try:
            release = rv.verify_release(manifest, artifact, policy, signature)
        except rv.VerificationError as exc:
            op = OperationLog.begin(cfg, name)
            op.step("verify", "failed", "; ".join(exc.problems)[:300])
            op.finish("failed", "The package was refused: " + "; ".join(exc.problems)[:250])
            raise UpdateError(["package refused"] + exc.problems) from None
        vid = version_id(release)
        op = OperationLog.begin(cfg, release.version)
        op.step("verify", "ok", release.authenticity)
        if read_receipt(cfg, vid):
            op.step("stage", "ok", "already staged on this host")
            if op.data is not None:
                op.data["state"], op.data["message"] = "staged", "Already staged."
                op._save()
            return {"id": vid, "version": release.version, "already_staged": True}
        if os.path.lexists(cfg.versions / vid):
            raise UpdateError(f"a partial copy of {vid} exists; run recovery first")
        state["tx"] = {"id": secrets.token_hex(8), "kind": "stage", "phase": "staging", "target": vid,
                       "from": current, "started_at": int(time.time())}
        save_state(cfg, state)
        op.step("stage", "running", "extracting and building the runtime; on a Raspberry Pi this takes a few minutes")
        try:
            rv.extract(release, cfg.versions / vid)
            builder(cfg, cfg.versions / vid, release)
            receipt = {"id": vid, "product": release.product, "platform": release.platform,
                       "version": release.version, "channel": release.channel, "change": release.change,
                       "repository": release.repository, "authenticity": release.authenticity,
                       "manifest_sha256": release.manifest_sha256, "artifact_sha256": release.artifact_sha256,
                       "staged_at": int(time.time())}
            fd = os.open(cfg.versions / vid / RECEIPT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "wb") as out:
                out.write(json.dumps(receipt, sort_keys=True, indent=1).encode())
                out.flush()
                os.fsync(out.fileno())
            _walk_modes(cfg.versions / vid, writable=False)  # the receipt is valid only once sealed
            _fsync_dir(cfg.versions)
        except BaseException as exc:
            try:
                remove_version(cfg, vid)
                _finish(cfg, state, "failed", f"staging failed: {exc}")
            except Exception:  # noqa: BLE001 - leave the journal for recovery
                pass
            raise
        state["staged"] = sorted(set(state.get("staged") or []) | {vid})
        _finish(cfg, state, "staged", f"version {release.version} verified and staged ({release.authenticity})")
        return {"id": vid, "version": release.version, "already_staged": False}


def activate_initial(cfg: HelperConfig, vid: str) -> dict:
    """First managed install: point `current` at a staged version. The operator then points
    the service at <root>/current and starts it by hand. Refused once `current` exists."""
    prepare_layout(cfg)
    with invocation_lock(cfg):
        state = load_state(cfg)
        _require_no_tx(state)
        if os.path.lexists(cfg.root / "current"):
            raise UpdateError("a current version already exists; use apply")
        if not read_receipt(cfg, vid):
            raise UpdateError(f"version {vid} is not completely staged")
        _point(cfg, "current", vid)
        state["current"] = vid
        save_state(cfg, state)
        return {"current": vid}


def apply(cfg: HelperConfig, vid: str, service: ServiceControl | None = None,
          readiness: Readiness = health_readiness, blockers: Callable[[Path], list[str]] = drain_blockers) -> dict:
    """Switch the service to a staged version. Refused unless everything is drained."""
    prepare_layout(cfg)
    service = service or service_for(cfg)
    with invocation_lock(cfg):
        state = load_state(cfg)
        _require_no_tx(state)
        receipt = read_receipt(cfg, vid)
        current = _link_target(cfg, "current")
        if not receipt:
            raise UpdateError(f"version {vid} is not completely staged")
        if current is None or not read_receipt(cfg, current):
            raise UpdateError("no managed current version; this install is updated by hand")
        if current == vid:
            raise UpdateError(f"version {vid} is already current")
        op = OperationLog.begin(cfg, receipt["version"])
        op.step("safety", "running", "checking that nothing is running or waiting and the database fits the new version")
        try:
            schema = database_revision(cfg.db_path)
            if not schema_compatible(schema, known_revisions(cfg.versions / vid)):
                raise UpdateError(f"the database is on schema {schema}, which version {vid} does not know; "
                                  "apply a version that knows it, or restore a matching snapshot explicitly")
            found = blockers(cfg.db_path)
            if found:
                raise UpdateError(["drain first; nothing was stopped"] + found)
        except UpdateError as exc:
            reason = "; ".join(exc.problems)[:280]
            op.step("safety", "failed", reason)
            op.finish("failed", "Nothing was stopped or changed. " + reason)
            raise
        op.step("safety", "ok", "nothing running or waiting; the database fits the new version")

        tx_id = secrets.token_hex(8)
        state["tx"] = {"id": tx_id, "kind": "switch", "phase": "prepared", "target": vid, "from": current,
                       "backup": None, "backup_meta": None, "started_at": int(time.time())}
        save_state(cfg, state)
        try:
            service.stop()
            found = blockers(cfg.db_path)  # anything that started between the check and the stop
            if found:
                service.start()
                _finish(cfg, state, "aborted", "work started while stopping; nothing was switched")
                raise UpdateError(["work started during the update; nothing was switched"] + found)
            op.write_log("service stopped")
            op.step("snapshot", "running", "saving a consistent copy of your data")
            backup = backup_database(cfg, tx_id, current)
            op.step("snapshot", "ok", ("saved " + Path(backup["path"]).name) if backup else "no database to back up")
            op.step("switch", "running", "pointing the service at the new version")
            state["tx"].update(phase="switching", backup=backup["path"] if backup else None,
                               backup_meta={"sha256": backup["sha256"], "schema_revision": backup["schema_revision"]}
                               if backup else None)
            save_state(cfg, state)
            _point(cfg, "previous", current)
            _point(cfg, "current", vid)
            state["tx"]["phase"] = "starting"
            save_state(cfg, state)
            started = time.time()
            op.step("switch", "ok", "the new version is in place")
            op.step("health", "running", "starting the service and waiting for the new version to report healthy")
            service.start()
        except UpdateError:
            if state.get("tx"):
                if _link_target(cfg, "current") == vid:
                    _rollback(cfg, state, service, readiness, "service start failed")
                else:
                    _recover_switch(cfg, state, service, readiness)
            raise
        except BaseException:
            _recover_switch(cfg, state, service, readiness)
            raise
        ok, detail = readiness(cfg, receipt["version"], started)
        if ok:
            return _commit(cfg, state, detail)
        _rollback(cfg, state, service, readiness, f"readiness failed: {detail}")
        raise UpdateError([f"version {vid} did not become ready and was rolled back", detail])


def _revision_for_receipt(cfg: HelperConfig) -> str | None:
    """Schema revision for the audit receipt. 'unreadable' rather than an error, so it never blocks."""
    try:
        return database_revision(cfg.db_path)
    except UpdateError:
        return "unreadable"


def _commit(cfg: HelperConfig, state: dict, detail: str) -> dict:
    tx = state["tx"]
    state["current"], state["previous"] = tx["target"], tx["from"]
    state["staged"] = [v for v in state.get("staged") or [] if v != tx["target"]]
    _finish(cfg, state, "committed", detail, schema_before=(tx.get("backup_meta") or {}).get("schema_revision"),
            schema_after=_revision_for_receipt(cfg), snapshot=tx.get("id") if tx.get("backup") else None)
    prune(cfg)
    return {"current": tx["target"], "previous": tx["from"], "detail": detail}


def _restore_on_rollback(cfg: HelperConfig, tx: dict) -> tuple[bool, str]:
    """Restore the pre-update snapshot only when the schema is still the snapshot's and the older
    version knows it. Otherwise the database is left alone and the receipt says what to do."""
    backup, meta = tx.get("backup"), tx.get("backup_meta") or {}
    if not backup:
        return False, ""
    snap = meta.get("schema_revision")
    try:  # the service is already stopped, so nothing here may raise past the restart
        now = database_revision(cfg.db_path)
        if now == snap and schema_compatible(snap, known_revisions(cfg.versions / tx["from"])):
            return restore_database(cfg, backup, meta.get("sha256")), ""
    except UpdateError as exc:  # the database is unchanged; the old version still starts
        return False, f"; snapshot {tx.get('id')} not restored: {exc}"
    return False, (f"; database left on schema {now or 'none'} (snapshot taken on {snap or 'none'}), not restored "
                   f"automatically: restore snapshot {tx.get('id')} explicitly with confirmation")


def _rollback(cfg: HelperConfig, state: dict, service: ServiceControl, readiness: Readiness, why: str) -> None:
    tx = state["tx"]
    tx["phase"], tx["reason"] = "rolling_back", why[:300]
    save_state(cfg, state)
    service.stop()
    _point(cfg, "current", tx["from"])
    restored, note = _restore_on_rollback(cfg, tx)
    started = time.time()
    service.start()
    back = read_receipt(cfg, tx["from"]) or {}
    ok, detail = readiness(cfg, back.get("version", ""), started)
    _finish(cfg, state, "rolled_back", f"{why}; code returned to {tx['from']}{note}"
            + ("" if ok else f" but it is not healthy either: {detail}"), database_restored=restored,
            snapshot=tx.get("id") if tx.get("backup") else None, schema_after=_revision_for_receipt(cfg))


def _recover_switch(cfg: HelperConfig, state: dict, service: ServiceControl, readiness: Readiness) -> str:
    tx = state["tx"]
    phase, target, previous = tx.get("phase"), tx.get("target"), tx.get("from")
    current = _link_target(cfg, "current")
    if phase == "prepared" or (phase == "switching" and current == previous):
        # Nothing the new version could have touched: put the old version back on.
        _point(cfg, "current", previous)
        service.start()
        _finish(cfg, state, "aborted", f"interrupted before the switch; {previous} restarted")
        return "aborted"
    if phase in ("switching", "starting") and current == target:
        try:
            service.start()
        except UpdateError:
            pass  # readiness decides
        # started=0: the service may have been up for a while; the version match is what counts.
        ok, detail = readiness(cfg, (read_receipt(cfg, target) or {}).get("version", ""), 0.0)
        if ok:
            _commit(cfg, state, f"recovered: {detail}")
            return "committed"
        _rollback(cfg, state, service, readiness, f"interrupted update was not healthy: {detail}")
        return "rolled_back"
    # rolling_back, or a link the journal does not explain: finish returning to the old version.
    _rollback(cfg, state, service, readiness, tx.get("reason") or f"interrupted in phase {phase}")
    return "rolled_back"


def recover(cfg: HelperConfig, service: ServiceControl | None = None,
            readiness: Readiness = health_readiness) -> str:
    """Finish or undo an interrupted update. Safe to run at any time and repeatedly."""
    prepare_layout(cfg)
    with invocation_lock(cfg):
        state = load_state(cfg)
        tx = state.get("tx")
        if not tx:
            return "nothing to recover"
        if tx.get("kind") == "stage":
            target = tx.get("target")
            if target and not read_receipt(cfg, target) and target not in (
                    _link_target(cfg, "current"), _link_target(cfg, "previous")):
                remove_version(cfg, target)
            _finish(cfg, state, "aborted", "staging was interrupted; the partial version was removed")
            return "aborted"
        if tx.get("kind") == "restore":
            service = service or service_for(cfg)
            try:
                service.start()
            except UpdateError:
                pass  # readiness decides
            current = _link_target(cfg, "current")
            ok, detail = readiness(cfg, (read_receipt(cfg, current) or {}).get("version", ""), 0.0)
            _finish(cfg, state, "restore_interrupted", f"snapshot {tx.get('snapshot')} restore was interrupted; the "
                    f"database is either the snapshot or the pre-restore copy {tx.get('pre_restore')}; {detail}")
            return "restore_interrupted"
        return _recover_switch(cfg, state, service or service_for(cfg), readiness)


def restore_snapshot(cfg: HelperConfig, tx_id: str, confirm: str | None, service: ServiceControl | None = None,
                     readiness: Readiness = health_readiness,
                     blockers: Callable[[Path], list[str]] = drain_blockers) -> dict:
    """Explicit database rollback to a kept snapshot. It discards every write made after the snapshot,
    so it is refused unless `confirm` repeats the snapshot id. The current database is copied first,
    and the service must be drained and stopped before anything is replaced."""
    prepare_layout(cfg)
    service = service or service_for(cfg)
    with invocation_lock(cfg):
        state = load_state(cfg)
        _require_no_tx(state)
        meta = load_snapshot(cfg, tx_id)
        current = _link_target(cfg, "current")
        if not current or not read_receipt(cfg, current):
            raise UpdateError("no managed current version; this install is updated by hand")
        if not schema_compatible(meta["schema_revision"], known_revisions(cfg.versions / current)):
            raise UpdateError(f"snapshot {tx_id} is on schema {meta['schema_revision']}, which the current "
                              f"version {current} does not know")
        if confirm != tx_id:
            raise UpdateError([
                f"WARNING: restoring snapshot {tx_id} discards every change made to the database since it was "
                f"taken (unix time {meta['created_at']}), including writes made by the newer version.",
                f"A copy of the current database is kept first. To confirm, run again with "
                f"--confirm-data-loss {tx_id}."])
        snapshot_file = cfg.state_dir / "backups" / meta["file"]
        if not snapshot_file.is_file() or _sha256(snapshot_file) != meta["sha256"]:
            raise UpdateError(f"snapshot {tx_id} is missing or failed its checksum; nothing was changed")
        found = blockers(cfg.db_path)
        if found:
            raise UpdateError(["drain first; nothing was stopped"] + found)

        restore_id = secrets.token_hex(8)
        state["tx"] = {"id": restore_id, "kind": "restore", "phase": "restoring", "target": current,
                       "from": current, "backup": None, "snapshot": tx_id, "pre_restore": None,
                       "started_at": int(time.time())}
        save_state(cfg, state)
        service.stop()
        found = blockers(cfg.db_path)  # anything that started between the check and the stop
        if found:
            service.start()
            _finish(cfg, state, "aborted", "work started while stopping; nothing was restored")
            raise UpdateError(["work started during the restore; nothing was restored"] + found)
        schema_before = _revision_for_receipt(cfg)
        pre = backup_database(cfg, restore_id, current)
        state["tx"]["pre_restore"] = pre["file"] if pre else None
        save_state(cfg, state)
        try:
            restore_database(cfg, str(snapshot_file), meta["sha256"])
        except BaseException as exc:
            service.start()
            _finish(cfg, state, "restore_failed", f"restore of snapshot {tx_id} failed: {exc}; the pre-restore "
                    f"copy is {pre['file'] if pre else 'absent'}")
            raise
        started = time.time()
        service.start()
        ok, detail = readiness(cfg, (read_receipt(cfg, current) or {}).get("version", ""), started)
        _finish(cfg, state, "restored" if ok else "restored_unhealthy",
                f"database restored from snapshot {tx_id}; {detail}", snapshot=tx_id, database_restored=True,
                data_loss_confirmed=True, schema_before=schema_before, schema_after=_revision_for_receipt(cfg),
                pre_restore=pre["file"] if pre else None)
        if not ok:
            raise UpdateError(["database restored, but the version is not healthy", detail])
        return {"current": current, "snapshot": tx_id, "detail": detail}


def prune(cfg: HelperConfig) -> list[str]:
    """Keep current, previous, staged-but-unused and the newest keep_versions versions."""
    state = load_state(cfg)
    keep = {_link_target(cfg, "current"), _link_target(cfg, "previous"), *(state.get("staged") or [])}
    complete = [v for v in os.listdir(cfg.versions) if read_receipt(cfg, v)]
    complete.sort(key=lambda v: read_receipt(cfg, v)["staged_at"], reverse=True)
    keep |= set(complete[:cfg.keep_versions])
    removed = []
    for vid in complete:
        if vid not in keep:
            remove_version(cfg, vid)
            removed.append(vid)
    prune_backups(cfg, cfg.keep_versions)
    return removed
