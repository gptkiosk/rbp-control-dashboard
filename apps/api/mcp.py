"""MCP server management for each agent CLI (Phase 3b).

Reading is safe and cached. Changing anything goes through an McpChange request that the
operator must approve (gate A8); nothing touches an agent's config before that.

Secrets: a request names environment variables (for example GITHUB_TOKEN); their values are read
from ~/.mac-control/.env only when an approved change is applied, passed to the agent CLI, and
never stored, returned, or logged. All CLI output shown in the dashboard is redacted.

Verified on this Mac (2026-10-09):
  claude    mcp list (text: "name: target - status"), add [-s user] [-e K=V] name -- cmd args,
            remove name -s user. "claude.ai ..." entries are account connectors managed in claude.ai.
  codex     mcp list --json, add name [--env K=V] -- cmd args | --url URL, remove name
  hermes    mcp list (text), add name --command cmd [--env K=V ...] --args ..., remove name
  openclaw  mcp list --json, mcp set name '<json>', removal = config unset mcp.servers.<name>,
            then mcp reload
"""

from __future__ import annotations

import json
import re
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

# (pattern, replacement) pairs; order matters only for readability, each is independent.
_SECRET_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}"), r"\1•••"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"), "sk-•••"),
    (re.compile(r"\b(xox[abposr]-)[A-Za-z0-9\-]{8,}"), r"\1•••"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), "AIza•••"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1•••"),
    # FOO_TOKEN=..., API_KEY=..., CLIENT_SECRET=..., DB_PASSWORD=...
    (re.compile(r"\b([A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY)[A-Za-z0-9_]*\s*[=:]\s*)[^\s,;]+",
                re.IGNORECASE), r"\1•••"),
)


def redact(text: str, extra: list[str] | None = None) -> str:
    """Remove secret-looking values, and every known secret string passed in `extra`."""
    out = text or ""
    for value in sorted((v for v in extra or [] if v), key=len, reverse=True):
        out = out.replace(value, "•••")
    for pattern, replacement in _SECRET_RES:
        out = pattern.sub(replacement, out)
    return out


def read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser for ~/.mac-control/.env (comments and blank lines ignored)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


# ----------------------------------------------------------------------------- listing


_CLAUDE_LINE = re.compile(r"^(?P<name>.+?): (?P<target>.+) - (?P<status>.+)$")


def parse_claude_list(text: str) -> list[dict]:
    servers = []
    for line in text.splitlines():
        m = _CLAUDE_LINE.match(line.strip())
        if not m:
            continue
        name = m.group("name")
        target = m.group("target")
        account = name.startswith("claude.ai ")
        servers.append({
            "name": name, "target": redact(target),
            "transport": "http" if target.startswith(("http://", "https://")) else "stdio",
            "status": m.group("status").strip(), "enabled": True,
            "source": "claude.ai account" if account else "Claude Code config",
            "removable": not account,
        })
    return servers


def parse_codex_list(text: str) -> list[dict]:
    data = json.loads(text or "[]")
    servers = []
    for item in data:
        t = item.get("transport") or {}
        if t.get("type") == "stdio":
            target = " ".join([t.get("command") or "", *(t.get("args") or [])]).strip()
        else:
            target = t.get("url") or ""
        servers.append({
            "name": item.get("name"), "target": redact(target), "transport": t.get("type"),
            "status": "enabled" if item.get("enabled") else "disabled", "enabled": bool(item.get("enabled")),
            "source": "Codex config", "removable": True,
            "env_names": sorted((t.get("env") or {}).keys()),
        })
    return servers


def parse_hermes_list(text: str) -> list[dict]:
    """Hermes prints a human table. 'No MCP servers configured' means none; otherwise each row
    starting with a name becomes an entry with the rest of the row as its target."""
    if "No MCP servers configured" in text:
        return []
    servers = []
    for line in text.splitlines():
        row = line.strip()
        if not row or row.lower().startswith(("name", "─", "-", "mcp servers", "add one", "hermes mcp")):
            continue
        parts = row.split(None, 1)
        if parts and NAME_RE.match(parts[0]):
            servers.append({"name": parts[0], "target": redact(parts[1] if len(parts) > 1 else ""),
                            "transport": None, "status": "disabled" if "disabled" in row else "enabled",
                            "enabled": "disabled" not in row,
                            "source": "Hermes config", "removable": True})
    return servers


def hermes_change_saved(action: str, name: str, output: str) -> bool:
    """Hermes can exit zero on cancellation or failed discovery; require its save receipt."""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    if action == "remove":
        return f"Removed '{name}' from config" in clean
    return bool(re.search(r"Saved '" + re.escape(name) + r"' to [^\n]+ \([1-9][0-9]*/[1-9][0-9]* tools enabled\)", clean))


def parse_openclaw_list(text: str) -> list[dict]:
    data = json.loads(text or "{}")
    servers = []
    for name, cfg in (data or {}).items():
        cfg = cfg or {}
        target = cfg.get("url") or " ".join([cfg.get("command") or "", *(cfg.get("args") or [])]).strip()
        servers.append({"name": name, "target": redact(target),
                        "transport": "http" if cfg.get("url") else "stdio",
                        "status": "disabled" if cfg.get("disabled") else "enabled",
                        "enabled": not cfg.get("disabled"), "source": "OpenClaw config",
                        "removable": True, "env_names": sorted((cfg.get("env") or {}).keys())})
    return servers


LIST_COMMANDS = {
    "claude": (["mcp", "list"], parse_claude_list),
    "codex": (["mcp", "list", "--json"], parse_codex_list),
    "hermes": (["mcp", "list"], parse_hermes_list),
    "openclaw": (["mcp", "list", "--json"], parse_openclaw_list),
}


# ----------------------------------------------------------------------------- changes


def validate_spec(agent: str, action: str, name: str, spec: dict) -> None:
    """Raise ValueError with a readable message when a change request is not acceptable."""
    if agent not in LIST_COMMANDS:
        raise ValueError(f"Unknown agent: {agent}")
    if action not in ("add", "remove"):
        raise ValueError("Action must be add or remove")
    if not NAME_RE.match(name or ""):
        raise ValueError("Name may use letters, digits, dot, dash and underscore (max 64)")
    if action == "remove":
        return
    transport = spec.get("transport")
    if transport == "stdio":
        if not (spec.get("command") or "").strip():
            raise ValueError("A stdio server needs a command")
    elif transport == "http":
        url = spec.get("url") or ""
        if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("HTTP servers must use https:// (or a localhost URL)")
    else:
        raise ValueError("Transport must be stdio or http")
    for env_name in spec.get("env_names") or []:
        if not ENV_NAME_RE.match(env_name):
            raise ValueError(f"Environment variable names must be UPPER_SNAKE_CASE: {env_name}")


def apply_argv(agent: str, action: str, name: str, spec: dict, env: dict[str, str],
               binary: str) -> list[list[str]]:
    """The CLI command(s) that perform an approved change. Env values come from ~/.mac-control/.env."""
    pairs = [f"{k}={env[k]}" for k in spec.get("env_names") or []]
    args = list(spec.get("args") or [])
    http = spec.get("transport") == "http"
    if agent == "claude":
        if action == "remove":
            return [[binary, "mcp", "remove", name, "-s", "user"]]
        argv = [binary, "mcp", "add", "-s", "user"]
        for p in pairs:
            argv += ["-e", p]
        if http:
            return [argv + ["-t", "http", name, spec["url"]]]
        return [argv + [name, "--", spec["command"], *args]]
    if agent == "codex":
        if action == "remove":
            return [[binary, "mcp", "remove", name]]
        if http:
            argv = [binary, "mcp", "add", name, "--url", spec["url"]]
            if spec.get("env_names"):
                argv += ["--bearer-token-env-var", spec["env_names"][0]]
            return [argv]
        argv = [binary, "mcp", "add", name]
        for p in pairs:
            argv += ["--env", p]
        return [argv + ["--", spec["command"], *args]]
    if agent == "hermes":
        if action == "remove":
            return [[binary, "mcp", "remove", name]]
        if http:
            return [[binary, "mcp", "add", name, "--url", spec["url"]]]
        argv = [binary, "mcp", "add", name, "--command", spec["command"]]
        if pairs:
            argv += ["--env", *pairs]
        if args:
            argv += ["--args", *args]  # must be the last option
        return [argv]
    if agent == "openclaw":
        if action == "remove":
            return [[binary, "config", "unset", f"mcp.servers.{name}"], [binary, "mcp", "reload"]]
        cfg: dict = {"url": spec["url"]} if http else {"command": spec["command"], "args": args}
        if pairs and not http:
            cfg["env"] = {k: env[k] for k in spec["env_names"]}
        return [[binary, "mcp", "set", name, json.dumps(cfg)], [binary, "mcp", "reload"]]
    raise ValueError(f"Unknown agent: {agent}")
