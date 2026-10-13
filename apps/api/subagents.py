"""Sub-agents and live sessions for each agent, shown on the Agents page.

Sources (verified on this Mac, 2026-10-09):
  openclaw  `agents list --json` (configured agents: id, name, model, default, bindings,
            workspace) and `sessions --json --agent <id> --active 1440` (recent sessions)
  hermes    `sessions list --limit N` (a text table: Title, Workspace, Last Active, ID)
  all four  running processes, classified by command line

Privacy: process command lines can contain prompts (for example `hermes chat -q "..."`), so only
the model and session flags are extracted; the command line itself is never returned.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import psutil

_FLAG_RE = {
    "model": re.compile(r"^--model(?:=(.+))?$"),
    "session": re.compile(r"^--(?:resume|session-id)(?:=(.+))?$"),
}


def _flag(argv: list[str], key: str) -> str | None:
    rx = _FLAG_RE[key]
    for i, arg in enumerate(argv):
        m = rx.match(arg)
        if m:
            if m.group(1):
                return m.group(1)
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                return argv[i + 1]
    return None


def classify(argv: list[str]) -> tuple[str, str] | None:
    """(agent, kind) for an agent process, or None. Uses argv only to classify."""
    if not argv:
        return None
    exe = argv[0]
    joined = " ".join(argv[:4])
    if "claude-code/" in exe and exe.endswith("/claude"):
        return "claude", "desktop session"
    if exe.endswith("/bin/claude") or exe == "claude" or exe.endswith("claude.exe"):
        return "claude", "cli session"
    if exe.endswith("/codex") or "codex-cli/bin/codex" in exe:
        return "codex", "exec" if "exec" in argv[1:3] else "session"
    if "hermes_cli.main" in joined:
        return "hermes", "gateway" if "gateway" in argv else "cli"
    if any(a.endswith('/integrations/hermes/mcd-run.py') for a in argv[:3]):
        return 'hermes', 'chat turn'
    if exe.endswith("/hermes") and len(argv) > 1:
        return "hermes", "chat turn" if argv[1] == "chat" else argv[1]
    if any(a.endswith("openclaw/dist/index.js") for a in argv[:3]) or exe.endswith("/openclaw"):
        sub = next((a for a in argv[1:4] if not a.startswith("-") and not a.endswith(".js")), "")
        return "openclaw", sub or "process"
    return None


def running_processes(now: float | None = None) -> dict[str, list[dict[str, Any]]]:
    now = now or time.time()
    out: dict[str, list[dict[str, Any]]] = {"claude": [], "codex": [], "hermes": [], "openclaw": []}
    for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
        argv = proc.info.get("cmdline") or []
        hit = classify(argv)
        if hit is None:
            continue
        agent, kind = hit
        try:
            cwd = proc.cwd()
        except (psutil.Error, OSError):
            cwd = None
        out[agent].append({
            "pid": proc.info["pid"], "kind": kind,
            "running_s": int(now - (proc.info.get("create_time") or now)),
            "model": _flag(argv, "model") or (next((argv[i+1] for i,a in enumerate(argv[:-1]) if a=='-m' and not argv[i+1].startswith('-')),None) if agent=='hermes' else None),
            "session": _flag(argv, "session"), "cwd": cwd,
        })
    for items in out.values():
        items.sort(key=lambda p: p["running_s"])
    return out


def parse_openclaw_agents(text: str) -> list[dict[str, Any]]:
    out = []
    for a in json.loads(text or "[]"):
        out.append({"id": a.get("id"), "name": a.get("name") or a.get("identityName"),
                    "model": a.get("model"), "default": bool(a.get("isDefault")),
                    "bindings": a.get("bindings") if isinstance(a.get("bindings"), int)
                    else len(a.get("bindings") or []),
                    "workspace": a.get("workspace")})
    return out


def summarize_openclaw_sessions(text: str, now_ms: float) -> dict[str, Any]:
    items = json.loads(text or "[]")
    items = items if isinstance(items, list) else items.get("sessions", [])
    updated = [s.get("updatedAt") for s in items if isinstance(s.get("updatedAt"), (int, float))]
    tokens = [s.get("totalTokens") for s in items if isinstance(s.get("totalTokens"), (int, float))]
    return {
        "sessions_24h": len(items),
        "last_active_s": int((now_ms - max(updated)) / 1000) if updated else None,
        "tokens_24h": int(sum(tokens)) if tokens else None,
        "models": sorted({s.get("model") for s in items if s.get("model")}),
    }


def parse_hermes_sessions(text: str) -> list[dict[str, Any]]:
    """Parse the fixed-width table printed by `hermes sessions list`."""
    lines = text.splitlines()
    header = next((i for i, l in enumerate(lines) if l.startswith("Title") and " ID" in l), None)
    if header is None:
        return []
    h = lines[header]
    cols = [h.index("Title"), h.index("Workspace"), h.index("Last Active"), h.index("ID")]
    rows = []
    for line in lines[header + 1:]:
        if not line.strip() or line.lstrip().startswith(("─", "…", "-")):
            continue
        if len(line) < cols[3]:
            continue
        cut = lambda a, b=None: line[a:b].strip()  # noqa: E731
        rows.append({"title": cut(cols[0], cols[1]), "workspace": cut(cols[1], cols[2]),
                     "last_active": cut(cols[2], cols[3]), "id": cut(cols[3])})
    return rows


async def snapshot(run, binaries: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Everything the Agents page shows under each agent. `run` is collector.run_command."""
    procs = running_processes()
    result: dict[str, dict[str, Any]] = {a: {"processes": p} for a, p in procs.items()}

    code, out = await run(binaries["openclaw"], "agents", "list", "--json", timeout=60)
    configured = parse_openclaw_agents(out) if code == 0 else []
    now_ms = time.time() * 1000
    for agent in configured:
        c2, o2 = await run(binaries["openclaw"], "sessions", "--json", "--agent", agent["id"],
                           "--active", "1440", "--limit", "100", timeout=60)
        agent.update(summarize_openclaw_sessions(o2, now_ms) if c2 == 0 else
                     {"sessions_24h": None, "last_active_s": None, "tokens_24h": None, "models": []})
    result["openclaw"]["agents"] = configured

    code, out = await run(binaries["hermes"], "sessions", "list", "--limit", "15", timeout=60)
    result["hermes"]["sessions"] = parse_hermes_sessions(out) if code == 0 else []
    result["checked_at"] = int(time.time())  # type: ignore[assignment]
    return result
