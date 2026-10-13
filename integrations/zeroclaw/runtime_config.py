"""Render a minimal, locked-down ZeroClaw ``config.toml`` for exactly one MCD run.

Everything not written here keeps ZeroClaw's defaults, so the file only states what MCD requires:
one provider entry (no ``fallback``/``fallback_models``/``model_routes``), one agent, one risk
profile, one runtime profile. The provider is the loopback admission proxy, never OpenRouter
directly, and the only credential in the file is the per-run proxy token.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

ALIAS = "rcd"
DEFAULT_MAX_TURNS = 200  # the run timeout and the proxy's request cap are the real bounds

# MCD tool vocabulary -> ZeroClaw native tool ids (verified present in zeroclaw 0.8.5).
TOOL_MAP: dict[str, tuple[str, ...]] = {
    "Read": ("file_read",), "Glob": ("glob_search",), "Grep": ("content_search",),
    "Write": ("file_write",), "Edit": ("file_edit",), "Bash": ("shell",),
    "WebFetch": ("web_fetch",), "WebSearch": ("web_search_tool",),
}
# Auto-approved even when the run lists no tools: observation only, confined by workspace_only.
READ_ONLY_TOOLS = ("file_read", "glob_search", "content_search", "memory_recall")
SHELL_ALLOWLIST = ("git", "ls", "cat", "grep", "find", "echo", "pwd", "wc", "head", "tail")
FORBIDDEN_PATHS = ("/etc", "/root", "/proc", "/sys", "/dev", "/boot", "~/.ssh", "~/.gnupg", "~/.aws",
                   "~/.config")


def _s(value: str) -> str:
    return json.dumps(value)  # JSON string escaping is valid TOML basic-string escaping


def _list(values: Sequence[str]) -> str:
    return "[" + ", ".join(_s(v) for v in values) + "]"


def resolve_tools(names: Sequence[str] | None, mcp_servers: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """MCD tool names -> ZeroClaw ids. Raises KeyError(name) for anything that cannot be granted."""
    out: list[str] = []
    for name in names or []:
        if name in TOOL_MAP:
            out.extend(TOOL_MAP[name])
            continue
        for server, spec in mcp_servers.items():
            if name in spec.get("tools", ()):
                out.append(f"{server}__{name}")
                break
        else:
            raise KeyError(name)
    return sorted(set(out))


def render(*, proxy_url: str, token: str, model: str, workspace: str, mode: str,
           allowed: Sequence[str], denied: Sequence[str] = (), always_ask: Sequence[str] = (),
           timeout_s: int, max_tokens: int | None, max_turns: int | None, transient_retries: int,
           mcp_servers: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    servers = dict(mcp_servers or {})
    lines = ["schema_version = 3", "",
             f"[providers.models.custom.{ALIAS}]", f"uri = {_s(proxy_url)}", f"model = {_s(model)}",
             f"api_key = {_s(token)}", f"timeout_secs = {min(max(int(timeout_s), 1), 600)}",
             # Without this the custom provider uses ZeroClaw's text-fallback tool mode, in which the
             # model's second request does not carry the tool exchange (verified on 0.8.5).
             "native_tools = true"]
    if max_tokens:
        lines.append(f"max_tokens = {int(max_tokens)}")
    lines += ["", "[reliability]", f"provider_retries = {int(transient_retries)}", "",
              f"[risk_profiles.{ALIAS}]",
              f"level = {_s('readonly' if mode == 'read' else 'supervised')}", "workspace_only = true",
              f"allowed_commands = {_list(SHELL_ALLOWLIST)}", f"forbidden_paths = {_list(FORBIDDEN_PATHS)}",
              f"auto_approve = {_list(sorted(set(READ_ONLY_TOOLS) | (set(allowed) - set(always_ask))))}",
              f"always_ask = {_list(sorted(always_ask))}",
              f"excluded_tools = {_list(sorted(denied))}"]
    if allowed:
        lines.append(f"allowed_tools = {_list(sorted(set(allowed) | set(READ_ONLY_TOOLS)))}")
    lines += ["", f"[runtime_profiles.{ALIAS}]", "agentic = true",
              f"max_tool_iterations = {int(max_turns or DEFAULT_MAX_TURNS)}",
              f"agentic_timeout_secs = {int(timeout_s)}", "shell_timeout_secs = 60", "",
              f"[agents.{ALIAS}]", f"model_provider = {_s('custom.' + ALIAS)}",
              f"risk_profile = {_s(ALIAS)}", f"runtime_profile = {_s(ALIAS)}"]
    if servers:
        lines.append(f"mcp_bundles = {_list([ALIAS])}")
    lines += ["", f"[agents.{ALIAS}.workspace]", f"path = {_s(workspace)}"]
    if servers:
        lines += ["", "[mcp]", "enabled = true"]
        for name, spec in servers.items():
            lines += ["", "[[mcp.servers]]", f"name = {_s(name)}", f"command = {_s(spec['command'])}",
                      f"args = {_list(spec.get('args', ()))}", 'transport = "stdio"',
                      "tool_timeout_secs = 30"]
            if spec.get("env"):
                lines.append("env = {" + ", ".join(f"{k} = {_s(v)}" for k, v in spec["env"].items()) + "}")
        lines += ["", f"[mcp_bundles.{ALIAS}]", f"servers = {_list(list(servers))}"]
    return "\n".join(lines) + "\n"
