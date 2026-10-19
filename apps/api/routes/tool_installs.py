"""Operator-only Agent tools API: plan, then run, the install/update/remove/rollback of the agent CLIs.

It reads install state and builds the plan the confirmation dialog shows, and it starts the helper
(tool_install_helper.py) outside this service. It never installs anything itself, never signs in to
a tool, never reads a key, and never touches dispatch, billing or free-only settings.

Every route needs a signed-in operator (no agent grant); the operator boundary has already refused agent
processes. With sign-in off, run tool_install_helper.py on the host instead (docs/install/agent-tools.md).
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

import tool_install as ti
import update_engine as ue
from routes.agent_tools import operator
from settings import REPO_ROOT, get_settings

router = APIRouter(prefix="/api/agent-installs")
API_DIR = Path(__file__).resolve().parents[1]  # the immutable version folder once installed from a release
LOG_LINES = 60


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(pattern=r"^[a-z][a-z0-9-]{1,30}$")
    action: str = Field(pattern=r"^(install|update|remove|rollback)$")


class RunIn(PlanIn):
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")  # exactly the plan the operator was shown
    confirm: bool


def _product() -> str:
    return "rcd" if get_settings().product_short_name.upper() == "RCD" else "mcd"


def _context() -> tuple[ti.ToolsConfig, ti.Catalog, ti.HostFacts]:
    settings = get_settings()
    try:
        catalog = ti.load_catalog(API_DIR)
    except ti.ToolError as exc:
        raise HTTPException(503, {"message": "The Agent tools catalog is not usable.", "problems": exc.problems}) from None
    root = settings.agent_tools_path
    facts = ti.detect_host(root, ti._tool_commands(catalog))
    cfg = ti.ToolsConfig(root=root, catalog_dir=API_DIR, platform_key=facts.platform_key, home=Path.home(), product=_product())
    return cfg, catalog, facts


def _log_tail(cfg: ti.ToolsConfig) -> list[str]:
    try:
        data = ti.read_regular(cfg.state_dir / "helper.log", ti.LOG_MAX_BYTES + 1, "helper log")
    except ti.ToolError:
        return []
    return data.decode("utf-8", "replace").splitlines()[-LOG_LINES:]


@router.get("")
def status(request: Request):
    operator(request)
    cfg, catalog, facts = _context()
    try:
        body = ti.inspect(cfg, catalog, facts)
    except ti.ToolError as exc:
        raise HTTPException(409, {"message": "Install state is unreadable.", "problems": exc.problems}) from None
    body["log"] = _log_tail(cfg)
    body["notes"] = {tid: catalog.component(tid).get("note") for tid in catalog.tool_ids()}
    return body


@router.get("/health")
def health(request: Request, tool: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9-]{1,30}$")):
    """Read-only follow-up check of every installed tool: runs, which version answers, reachable by name, next steps."""
    operator(request)
    cfg, catalog, facts = _context()
    try:
        return {"checks": ti.health(cfg, catalog, facts, tool)}
    except ti.ToolError as exc:
        raise HTTPException(409, {"message": "Install state is unreadable.", "problems": exc.problems}) from None


@router.post("/plan")
def plan(request: Request, body: PlanIn):
    """Read-only: exactly what the helper would do, with the versions, sources, disk and memory it would see."""
    operator(request)
    cfg, catalog, facts = _context()
    try:
        return ti.build_plan(cfg, catalog, facts, body.tool, body.action)
    except ti.ToolError as exc:
        raise HTTPException(422, exc.problems[0]) from None


@router.post("/run", status_code=202)
def run(request: Request, body: RunIn):
    operator(request)
    if not body.confirm:
        raise HTTPException(422, "Explicit confirmation is required.")
    cfg, catalog, facts = _context()
    try:
        current = ti.build_plan(cfg, catalog, facts, body.tool, body.action)
    except ti.ToolError as exc:
        raise HTTPException(422, exc.problems[0]) from None
    if current["refusals"]:
        raise HTTPException(409, {"message": "This cannot run.", "problems": current["refusals"]})
    if current["plan_sha256"] != body.plan_sha256:
        raise HTTPException(409, {"message": "The plan changed since you confirmed it. Open the confirmation again.",
                                  "problems": []})
    busy = _update_in_progress()
    if busy:
        raise HTTPException(409, {"message": busy, "problems": []})
    return _spawn(cfg, body)


def _update_in_progress() -> str | None:
    """A dashboard update that is switching versions must finish first. Best effort: no updater, no check."""
    root = get_settings().update_root
    if root is None:
        return None
    try:
        kind, _ = ue.install_kind(REPO_ROOT, root)
        if kind != "release":
            return None
        cfg = ue.load_config(root / "helper" / "helper.json")
        return "A dashboard update is in progress or was interrupted. Finish it first." if ue.load_state(cfg).get("tx") else None
    except (ue.UpdateError, OSError):
        return None


def _systemd_run() -> str | None:
    """systemd-run, when this service runs inside a systemd user session that can start transient units."""
    found = next((p for p in ("/usr/bin/systemd-run", "/bin/systemd-run") if os.path.isfile(p)), None)
    return found if found and os.environ.get("XDG_RUNTIME_DIR") else None


def _helper_argv(cfg: ti.ToolsConfig, body: RunIn) -> list[str]:
    return [sys.executable, "-I", str(API_DIR / "tool_install_helper.py"), "--root", str(cfg.root), "run", body.tool,
            body.action, "--plan-sha256", body.plan_sha256]


def _spawn(cfg: ti.ToolsConfig, body: RunIn) -> dict:
    """Start the helper outside this service, so restarting the service cannot stop an install half way."""
    try:
        ti.prepare_layout(cfg)
    except (ti.ToolError, OSError) as exc:
        raise HTTPException(409, {"message": "The install folder is not usable.", "problems": getattr(exc, "problems", [str(exc)])}) from None
    log = cfg.state_dir / "helper.log"
    argv = _helper_argv(cfg, body)
    systemd_run = _systemd_run()
    if systemd_run:
        # A child of this service would die with its cgroup; run it as its own transient unit, at low priority, and
        # let the kernel kill it before the dashboard if memory runs out. NoNewPrivileges backs up the helper's own
        # no_new_privs: nothing the installers start can use sudo.
        argv = [systemd_run, "--user", "--collect", "--quiet", f"--unit=rcd-tool-install-{secrets.token_hex(4)}",
                "-p", "Nice=10", "-p", "OOMScoreAdjust=500", "-p", "NoNewPrivileges=yes",
                "-p", f"StandardOutput=append:{log}", "-p", f"StandardError=append:{log}", "--", *argv]
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home()), "LC_ALL": "C"}
    for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XDG_DATA_HOME"):
        if key in os.environ:
            env[key] = os.environ[key]
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, env=env, cwd=str(cfg.root),
                         start_new_session=True, close_fds=True)
    except OSError:
        raise HTTPException(409, "The helper could not be started.") from None
    finally:
        os.close(fd)
    return {"started": f"{body.action} {body.tool}", "poll": "/api/agent-installs"}
