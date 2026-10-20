"""MCP panel API: list servers per agent; request, approve or reject changes (gate A8)."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import mcp
from agents import REGISTRY
from collector import run_command
from deps import get_session
from models import McpChange
from settings import get_settings

router = APIRouter(prefix="/api/mcp")

_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_S = 60.0
ERROR_DETAIL_LIMIT = 500


async def _run_list_command(binary: str, *args: str, timeout: float = 90.0) -> tuple[int, str]:
    """Run an MCP inventory command while retaining safe, bounded failure diagnostics."""
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 127, ""
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, ""
    output = (stderr or stdout).decode("utf-8", "replace").strip()
    if proc.returncode:
        # CLI diagnostics can echo credentials. Redact recognizable tokens and values
        # configured in RCD's private environment file before returning them to the UI.
        secrets = list(mcp.read_env_file(get_settings().data_dir / ".env").values())
        output = mcp.redact(output, secrets)
        output = " ".join(output.split())[:ERROR_DETAIL_LIMIT]
    return proc.returncode or 0, output


class ChangeIn(BaseModel):
    agent: str
    action: str
    name: str = Field(max_length=64)
    transport: str | None = None
    command: str | None = Field(default=None, max_length=500)
    args: list[str] = Field(default_factory=list, max_length=40)
    url: str | None = Field(default=None, max_length=500)
    env_names: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=500)


def _change_dict(c: McpChange) -> dict:
    return {"id": c.id, "agent": c.agent, "action": c.action, "name": c.name,
            "spec": json.loads(c.spec), "status": c.status, "output": c.output, "note": c.note,
            "created_at": c.created_at, "decided_at": c.decided_at}


async def list_for(agent: str, refresh: bool = False) -> dict:
    spec = REGISTRY.get(agent)
    if spec is None or agent not in mcp.LIST_COMMANDS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent}")
    cached = _CACHE.get(agent)
    if cached and not refresh and time.time() - cached[0] < CACHE_S:
        return cached[1]
    args, parse = mcp.LIST_COMMANDS[agent]
    code, out = await _run_list_command(spec.binary(get_settings()), *args, timeout=90)
    now = int(time.time())
    if code == 127:
        # The command is not on this host: an agent the operator does not use here. That is a state, not a failure.
        result = {"agent": agent, "servers": [], "error": None, "installed": False, "checked_at": now}
    elif code != 0:
        error = f"list failed (exit {code})"
        if code == 124:
            error += ": command timed out after 90 seconds"
        elif out:
            error += f": {out}"
        result = {"agent": agent, "servers": [], "error": error, "installed": True, "checked_at": now}
    else:
        try:
            result = {"agent": agent, "servers": parse(out), "error": None, "installed": True, "checked_at": now}
        except ValueError:
            result = {"agent": agent, "servers": [], "error": "could not parse the list output", "installed": True,
                      "checked_at": now}
    _CACHE[agent] = (time.time(), result)
    return result


@router.get("/servers")
async def all_servers(refresh: bool = Query(False)):
    results = await asyncio.gather(*(list_for(a, refresh) for a in mcp.LIST_COMMANDS))
    return {"agents": list(results)}


@router.get("/env-names")
def env_names():
    """Names (never values) of variables available in ~/.mac-control/.env for MCP servers."""
    return {"names": sorted(mcp.read_env_file(get_settings().data_dir / ".env"))}


@router.get("/changes")
def list_changes(s: Session = Depends(get_session)):
    rows = s.execute(select(McpChange).order_by(McpChange.id.desc()).limit(100)).scalars().all()
    return {"changes": [_change_dict(c) for c in rows]}


@router.post("/changes", status_code=201)
async def request_change(body: ChangeIn, s: Session = Depends(get_session)):
    spec = {"transport": body.transport, "command": body.command, "args": body.args,
            "url": body.url, "env_names": body.env_names}
    try:
        mcp.validate_spec(body.agent, body.action, body.name, spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.action == "remove":
        listing = await list_for(body.agent)
        entry = next((x for x in listing["servers"] if x["name"] == body.name), None)
        if entry is not None and not entry.get("removable", True):
            raise HTTPException(status_code=422, detail=f"{body.name} is managed in claude.ai, not here.")
    change = McpChange(agent=body.agent, action=body.action, name=body.name, spec=json.dumps(spec),
                       status="pending", note=body.note, created_at=int(time.time()))
    s.add(change)
    s.commit()
    return _change_dict(change)


@router.post("/changes/{change_id}/reject")
def reject_change(change_id: int, s: Session = Depends(get_session)):
    c = s.get(McpChange, change_id)
    if c is None or c.status != "pending":
        raise HTTPException(status_code=409, detail="That change is not pending.")
    c.status, c.decided_at = "rejected", int(time.time())
    s.commit()
    return _change_dict(c)


@router.post("/changes/{change_id}/approve")
async def approve_change(change_id: int, s: Session = Depends(get_session)):
    """Approval applies the change immediately (gate A8). Output is redacted before it is stored."""
    c = s.get(McpChange, change_id)
    if c is None or c.status != "pending":
        raise HTTPException(status_code=409, detail="That change is not pending.")
    settings = get_settings()
    spec = json.loads(c.spec)
    env_file = mcp.read_env_file(settings.data_dir / ".env")
    missing = [n for n in spec.get("env_names") or [] if n not in env_file]
    c.decided_at = int(time.time())
    if missing:
        c.status = "failed"
        c.output = "Missing in ~/.mac-control/.env: " + ", ".join(missing)
        s.commit()
        return _change_dict(c)
    env = {n: env_file[n] for n in spec.get("env_names") or []}
    secrets = list(env.values())
    binary = REGISTRY[c.agent].binary(settings)
    outputs, ok = [], True
    for argv in mcp.apply_argv(c.agent, c.action, c.name, spec, env, binary):
        # Hermes 0.21.5 prompts after discovery and exits zero even on EOF/cancel.
        # One empty answer accepts discovered tools/removal; overwrite and failed-probe
        # save prompts default to No. Never send an unbounded stream of confirmations.
        options = {"input_data": b"\n"} if c.agent == "hermes" else {}
        code, out = await run_command(*argv, timeout=180, **options)
        shown = [mcp.redact(a, secrets) for a in argv]
        outputs.append(f"$ {' '.join(shown)}\n(exit {code})\n{mcp.redact(out, secrets).strip()}")
        if code != 0 or (c.agent == "hermes" and not mcp.hermes_change_saved(c.action, c.name, out)):
            ok = False
            break
    if ok and c.agent == "hermes":
        listing = await list_for("hermes", refresh=True)
        entry = next((r for r in listing["servers"] if r["name"] == c.name), None)
        ok = not listing["error"] and (bool(entry and entry["enabled"]) if c.action == "add" else entry is None)
        if not ok:
            outputs.append("Verification failed: Hermes did not persist the approved registration change.")
    c.status = "applied" if ok else "failed"
    c.output = "\n\n".join(outputs)[:20000]
    s.commit()
    _CACHE.pop(c.agent, None)
    return _change_dict(c)
