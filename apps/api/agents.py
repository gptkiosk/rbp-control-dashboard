"""Agent adapters: how to run each agent CLI and read what it reports.

Formats were verified on this Mac on 2026-10-09 with one read-only probe per agent:
  claude   -p --output-format stream-json   JSONL: system/init (model, session), assistant,
                                            result (cost, usage, is_error)
  codex    exec --json                      JSONL: thread.started, item.completed,
                                            turn.completed (usage). No model reported.
  hermes   chat -q --oneshot --format stream-json
                                            JSONL: system/init (model, session), text,
                                            result (tokens, exit_code)
  openclaw agent --json                     one JSON document at exit (status, payloads,
                                            meta.agentMeta: provider, model, usage, sessionId)
  grok     -p --output-format streaming-messages-json
                                            JSONL in Claude Code's stream-json shape: system/init
                                            (model, session), assistant, result (cost, usage, is_error).
                                            Verified against xai-org/grok-build 1.0.52 source and
                                            `grok --help`; not run against a signed-in account.

Each parser turns output lines into short human-readable log lines and fills RunMeta.
Fields an agent does not report stay None and the UI shows "not reported".
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import agent_git

PROMPT_PLACEHOLDER = "<prompt>"


@dataclass
class RunMeta:
    model_reported: str | None = None
    provider: str | None = None
    session_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: float | None = None
    result_text: str | None = None
    error: str | None = None
    timed_out: bool = False


class Parser:
    def __init__(self) -> None:
        self.meta = RunMeta()

    def feed(self, line: str) -> list[str]:  # pragma: no cover - overridden
        return [line]

    def finish(self) -> list[str]:
        return []

    def feed_stderr(self, line: str) -> None:
        """Inspect stderr for terminal outcomes; raw output stays in the run log."""


def _json(line: str) -> dict | None:
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _int(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


# ----------------------------------------------------------------------------- Claude Code


class ClaudeParser(Parser):
    def feed(self, line: str) -> list[str]:
        ev = _json(line)
        if ev is None:
            return [line] if line.strip() else []
        kind, sub = ev.get("type"), ev.get("subtype")
        if kind == "system" and sub == "init":
            self.meta.model_reported = ev.get("model")
            self.meta.session_id = ev.get("session_id")
            self.meta.provider = "anthropic"
            return [f"started: model {self.meta.model_reported}, permission mode {ev.get('permissionMode')}"]
        if kind == "system" and sub == "api_retry":
            return [f"retrying after API error: {ev.get('error')}"]
        if kind == "assistant":
            out: list[str] = []
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    out.append(block["text"])
                elif block.get("type") == "tool_use":
                    out.append(f"tool: {block.get('name')}")
            return out
        if kind == "result":
            usage = ev.get("usage") or {}
            ins = [_int(usage.get(k)) for k in
                   ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
            self.meta.input_tokens = sum(i for i in ins if i is not None) if any(i is not None for i in ins) else None
            self.meta.output_tokens = _int(usage.get("output_tokens"))
            self.meta.cached_input_tokens = _int(usage.get("cache_read_input_tokens", usage.get("cached_input_tokens")))
            self.meta.cache_write_tokens = _int(usage.get("cache_creation_input_tokens", usage.get("cache_write_input_tokens")))
            cost = ev.get("total_cost_usd")
            self.meta.cost_usd = float(cost) if isinstance(cost, (int, float)) else None
            self.meta.result_text = ev.get("result")
            if ev.get("is_error"):
                self.meta.error = str(ev.get("result") or "agent reported an error")
                return [f"error: {self.meta.error}"]
            return [f"finished in {ev.get('num_turns')} turn(s)"]
        return []


def build_claude(card, prompt: str, model: str | None, budget: float, binary: str,
                 session_id: str | None = None) -> list[str]:
    mode = "plan" if card.mode == "read" else "acceptEdits"
    grant = None if getattr(card, "output_only", False) else getattr(card, "agent_git_grant", None)
    # Belt and braces: in print mode shell commands are denied unless allowed, and these
    # stay blocked even if a future setting allows Bash. With an operator grant, the blanket
    # `git push` deny gives way to one exact allowed push (a deny would beat the allow).
    denied = (agent_git.claude_denied(grant) if grant else
              ["Bash(git push:*)", "Bash(git merge:*)", "Bash(gh pr merge:*)"])
    argv = [binary, "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--permission-mode", mode, "--disallowedTools", *denied]
    if not getattr(card, 'output_only', False):
        # Print-mode jobs cannot answer native approval prompts. Public research is
        # available without granting shell, credential or publication permissions, unless the
        # operator granted branch-scoped git access for this project.
        argv += ["--allowedTools", "WebSearch", "WebFetch"]
        if grant:
            argv += agent_git.claude_allowed(grant)
        if mode != "plan":
            # An Edit story can run its tests, syntax checks and installs whether or not the project has a git grant; the operator can make this strict (settings.agent_permissions).
            argv += [c for c in getattr(card, "agent_commands", agent_git.CHECK_COMMANDS) if c not in argv]
    if not getattr(card,"subscription_billing",False):
        argv += ["--max-budget-usd", f"{budget:.2f}"]
    if model:
        argv += ["--model", model]
    if session_id:
        argv += ["--resume", session_id]
    if getattr(card, 'output_only', False):
        # MCD saves the approved Markdown artifact. No write, shell, delegation or
        # MCP tools are exposed to the continuation agent.
        argv += ["--tools", "Read,Glob,Grep", "--strict-mcp-config", "--mcp-config",
                 '{"mcpServers":{}}', "--disable-slash-commands"]
    return argv


# ----------------------------------------------------------------------------- Grok Build


class GrokParser(ClaudeParser):
    """Grok Build's `--output-format streaming-messages-json` is Claude Code's stream-json shape
    (system/init, assistant, user tool results, result with usage and total_cost_usd), so the
    Claude parser reads it. What differs is who the provider is, and that an error can arrive as a
    bare `{"type":"error","message":...}` line (for example when nobody is signed in)."""

    def feed(self, line: str) -> list[str]:
        ev = _json(line)
        if ev is not None and ev.get("type") == "error":
            self.meta.error = str(ev.get("message") or "agent reported an error")
            return [f"error: {self.meta.error}"]
        out = super().feed(line)
        if ev is not None and ev.get("type") == "system" and ev.get("subtype") == "init":
            self.meta.provider = "xai"
        return out


# Telemetry and trace upload are the operator's choice, never the agent's: a dashboard-dispatched run
# turns them off and keeps the agent inside a filesystem sandbox. See docs/configuration/grok.md.
GROK_PRIVACY_ENV = {"GROK_TELEMETRY_ENABLED": "false", "GROK_TELEMETRY_TRACE_UPLOAD": "false",
                    "GROK_TELEMETRY_MIXPANEL_ENABLED": "false"}


def build_grok(card, prompt: str, model: str | None, budget: float, binary: str,
               session_id: str | None = None) -> list[str]:
    read_only = card.mode == "read"
    grant = getattr(card, "agent_git_grant", None)
    # Same rules as Claude (Grok accepts Claude's `Bash(cmd:*)` syntax; deny beats allow): git push and
    # merges stay blocked unless the operator granted one exact push for this project.
    denied = (agent_git.claude_denied(grant) if grant else
              ["Bash(git push:*)", "Bash(git merge:*)", "Bash(gh pr merge:*)"])
    argv = [binary, "--no-auto-update", "-p", prompt, "--output-format", "streaming-messages-json",
            "--permission-mode", "plan" if read_only else "acceptEdits",
            # Landlock on Linux, Seatbelt on macOS: read-only for a read task, the working directory
            # (plus /tmp and ~/.grok) for an edit task. Without a profile nothing is restricted.
            "--sandbox", "read-only" if read_only else "workspace"]
    for rule in denied:
        argv += ["--deny", rule]
    if grant:
        for rule in agent_git.claude_allowed(grant):
            if rule != "--allowedTools":
                argv += ["--allow", rule]
    if model:
        argv += ["--model", model]
    if session_id:
        argv += ["--resume", session_id]
    return argv


# ----------------------------------------------------------------------------- Codex


class CodexParser(Parser):
    def feed(self, line: str) -> list[str]:
        ev = _json(line)
        if ev is None:
            return [line] if line.strip() else []
        kind = ev.get("type")
        if kind == "thread.started":
            self.meta.session_id = ev.get("thread_id")
            self.meta.provider = "openai"
            return ["started"]
        if kind == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "agent_message":
                self.meta.result_text = item.get("text")
                return [item.get("text") or ""]
            if item.get("type") == "command_execution":
                return [f"$ {item.get('command')}"]
            return []
        if kind == "turn.completed":
            usage = ev.get("usage") or {}
            self.meta.input_tokens = _int(usage.get("input_tokens"))
            self.meta.output_tokens = _int(usage.get("output_tokens"))
            self.meta.cached_input_tokens = _int(usage.get("cache_read_input_tokens", usage.get("cached_input_tokens")))
            self.meta.cache_write_tokens = _int(usage.get("cache_creation_input_tokens", usage.get("cache_write_input_tokens")))
            return ["turn completed"]
        if kind in ("turn.failed", "error"):
            err = ev.get("error") or ev.get("message")
            self.meta.error = json.dumps(err) if isinstance(err, (dict, list)) else str(err)
            return [f"error: {self.meta.error}"]
        return []


def build_codex(card, prompt: str, model: str | None, budget: float, binary: str,
                session_id: str | None = None) -> list[str]:
    sandbox = "read-only" if card.mode == "read" else "workspace-write"
    grant = getattr(card, "agent_git_grant", None)
    # With an operator grant the plain workspace-write sandbox (read-only .git, no network) is
    # replaced by a permission profile that lets the story commit and reach GitHub only.
    domains = tuple(getattr(card, "agent_domains", agent_git.CODEX_DOMAINS))
    if grant:
        profile = [a for o in agent_git.codex_overrides(domains) for a in ("-c", o)]
    elif card.mode != "read" and getattr(card, "agent_work_profile", False):
        profile = [a for o in agent_git.codex_work_overrides(domains) for a in ("-c", o)]    # the working default: workspace sandbox plus the package indexes and GitHub
    else:
        profile = []
    if session_id:
        # `codex exec resume` has no -s/-C flags, so the sandbox is forced with a config override;
        # otherwise a resumed turn would use whatever sandbox Codex's own config defaults to.
        argv = [binary, *(profile or ["-c", f'sandbox_mode="{sandbox}"']), "exec", "resume", "--json",
                "--skip-git-repo-check"]
        if model:
            argv += ["-m", model]
        return argv + [session_id, prompt]
    argv = [binary, "exec", "--json", "--skip-git-repo-check", *(profile or ["-s", sandbox]), "-C", card.working_dir]
    if model:
        argv += ["-m", model]
    return argv + [prompt]


def codex_default_model(config: Path = Path.home() / ".codex" / "config.toml") -> str | None:
    try:
        return tomllib.loads(config.read_text()).get("model")
    except (OSError, ValueError):
        return None


# ----------------------------------------------------------------------------- Hermes


class HermesParser(Parser):
    def feed(self, line: str) -> list[str]:
        ev = _json(line)
        if ev is None:
            return [line] if line.strip() else []
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            self.meta.model_reported = ev.get("model")
            self.meta.session_id = ev.get("session_id")
            model = self.meta.model_reported or ""
            self.meta.provider = model.split("/", 1)[0] if "/" in model else None
            return [f"started: model {self.meta.model_reported}"]
        if kind == "text":
            return [ev.get("text") or ""]
        if kind == "result":
            if ev.get('model'): self.meta.model_reported = ev['model']
            if ev.get('provider'): self.meta.provider = ev['provider']
            tokens = ev.get("tokens") or {}
            self.meta.input_tokens = _int(tokens.get("input"))
            self.meta.output_tokens = _int(tokens.get("output"))
            self.meta.result_text = ev.get("text")
            if ev.get("exit_code") not in (0, None):
                self.meta.error = f"hermes exit code {ev.get('exit_code')}"
                return [f"error: {self.meta.error}"]
            return ["finished"]
        return []


def build_hermes(card, prompt: str, model: str | None, budget: float, binary: str,
                 session_id: str | None = None) -> list[str]:
    # Hermes' terminal tool starts in the folder set in its own config, not in --in, so files written with relative paths would land there.
    # Tell it the task folder first, for an Edit story that writes files.
    folder = getattr(card, "working_dir", "") or ""
    if folder and getattr(card, "mode", "read") != "read" and not session_id:
        prompt = (f"Task folder: {folder}\nYour terminal may start in a different folder. Begin every shell command with `cd {folder} &&` "
                  f"and keep every file you create or change inside that folder.\n\n{prompt}")
    argv = [binary, "chat", "-q", prompt, "--oneshot", "--format", "stream-json",
            "--in", card.working_dir, "--max-turns", "25", "--run-budget", str(card.timeout_s)]
    if model:
        argv += ["-m", model]
    if session_id:
        argv += ["--resume", session_id]
    return argv


# ----------------------------------------------------------------------------- OpenClaw


class OpenClawParser(Parser):
    """OpenClaw prints one JSON document when the turn ends, so the log stays quiet until then."""

    def __init__(self) -> None:
        super().__init__()
        self._buffer: list[str] = []
        self._gateway_timeout = False
        self._gateway_error = False

    def feed_stderr(self, line: str) -> None:
        # Match the gateway's terminal exception, not warnings or prompt text. Never
        # copy arbitrary stderr into the structured error (it can contain secrets).
        if "GatewayClientRequestError:" in line:
            self._gateway_error = True
            if "LLM request timed out" in line or "Upstream idle timeout exceeded" in line:
                self._gateway_timeout = True

    def feed(self, line: str) -> list[str]:
        self._buffer.append(line)
        return []

    def finish(self) -> list[str]:
        raw = "\n".join(self._buffer)
        start = raw.find("{")
        doc = _json(raw[start:]) if start >= 0 else None
        if doc is None:
            if self._gateway_timeout:
                self.meta.timed_out = True
                self.meta.error = ("OpenClaw provider timed out: the gateway reported an LLM request timeout. "
                                   "No JSON result was returned, so model and usage are not reported. "
                                   "Upstream time limits can still apply despite MCD's timeout setting. "
                                   "Review any partial work before retrying.")
            elif self._gateway_error:
                self.meta.error = "OpenClaw gateway rejected the run without returning JSON. Inspect the gateway error in the run log."
            else:
                self.meta.error = "no JSON result from openclaw"
            return [f"error: {self.meta.error}"]
        result_meta = (doc.get("result") or {}).get("meta") or {}
        meta = result_meta.get("agentMeta") or {}
        usage = meta.get("usage") or {}
        self.meta.model_reported = meta.get("model")
        self.meta.provider = meta.get("provider")
        self.meta.session_id = meta.get("sessionId")
        self.meta.input_tokens = _int(usage.get("input"))
        self.meta.output_tokens = _int(usage.get("output"))
        payloads = (doc.get("result") or {}).get("payloads") or []
        text = "\n".join(p.get("text") or "" for p in payloads if isinstance(p, dict)).strip()
        self.meta.result_text = text or None
        if doc.get("status") == "timeout":
            self.meta.timed_out = True
            phase = doc.get("timeoutPhase") or result_meta.get("timeoutPhase")
            if phase == "provider":
                reason = ("the model stopped responding before its idle limit"
                          if "idle timeout" in text.lower() else "the model request did not finish in time")
                self.meta.error = f"OpenClaw provider timed out: {reason}. Review any partial work before retrying."
            else:
                labels = {"queue": "while waiting to start", "preflight": "before the model request started",
                          "post_turn": "while finalizing the response", "gateway_draining": "while the gateway was shutting down"}
                detail = labels.get(phase, "before the run completed")
                self.meta.error = f"OpenClaw timed out {detail}. Review any partial work before retrying."
            return [f"error: {self.meta.error}"]
        if doc.get("status") != "ok":
            self.meta.error = f"openclaw status {doc.get('status')}"
            return [f"error: {self.meta.error}"]
        return [text] if text else ["finished (no text)"]


def build_openclaw(card, prompt: str, model: str | None, budget: float, binary: str,
                   session_id: str | None = None) -> list[str]:
    # Never --deliver: replies stay in the dashboard and are not posted to any channel.
    argv = [binary, "agent", "--agent", card.agent_target or "mm-main", "-m", prompt,
            "--json", "--timeout", str(card.timeout_s)]
    if model:
        argv += ["--model", model]
    if session_id:
        # OpenClaw takes a caller-chosen session id; chat threads generate one up front.
        argv += ["--session-id", session_id]
    return argv


# ----------------------------------------------------------------------------- registry


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    role: str  # worker | manager
    binary_setting: str
    build: Callable[..., list[str]]
    parser: Callable[[], Parser]
    default_model: Callable[[], str | None] = lambda: None
    enforces_mode: bool = True
    notes: str = ""
    suggested_models: tuple[str, ...] = field(default_factory=tuple)
    # True when the dashboard must choose the session id before the first turn (OpenClaw);
    # False when the agent reports its own session id and we resume it.
    preassigned_session: bool = False
    # Environment this agent's runs always get, on top of the scrubbed one (never from agent output).
    env: dict[str, str] = field(default_factory=dict)

    def binary(self, settings) -> str:
        path = str(getattr(settings, self.binary_setting))
        if not os.path.isabs(path) or self.binary_setting not in getattr(settings, "model_fields_set", set()):
            # Nothing was found at startup. A copy installed since by the Agent tools panel is used without a restart.
            from tool_install import managed_bin
            return managed_bin(getattr(settings, "agent_tools_path", None), Path(path).name) or path
        return path

    def available(self, settings) -> bool:
        path = self.binary(settings)
        return os.path.isfile(path) and os.access(path, os.X_OK)


REGISTRY: dict[str, AgentSpec] = {
    "claude": AgentSpec(
        "claude", "Claude Code", "worker", "claude_path", build_claude, ClaudeParser,
        suggested_models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
        notes="Read = plan mode; Edit = file edits in the working directory only. git push/merge blocked.",
    ),
    "codex": AgentSpec(
        "codex", "Codex", "worker", "codex_path", build_codex, CodexParser,
        default_model=codex_default_model,
        notes="Read = read-only sandbox; Edit = workspace-write sandbox. Model is not reported by Codex.",
    ),
    "grok": AgentSpec(
        "grok", "Grok Build", "worker", "grok_path", build_grok, GrokParser,
        suggested_models=("grok-4.6", "grok-4.5", "grok-build-0.1"),
        notes="Read = plan mode in a read-only sandbox; Edit = file edits in a workspace sandbox. "
              "git push/merge blocked. Sends the task and the files it reads to xAI. Subscription use only: "
              "the CLI has no dollar cap, so an API-billed route is refused.",
        env=GROK_PRIVACY_ENV,
    ),
    "hermes": AgentSpec(
        "hermes", "Hermes", "manager", "hermes_path", build_hermes, HermesParser,
        enforces_mode=False,
        notes="Management agent. Uses its own tool policy; Read/Edit is advisory.",
    ),
    "openclaw": AgentSpec(
        "openclaw", "OpenClaw", "worker", "openclaw_path", build_openclaw, OpenClawParser,
        enforces_mode=False, preassigned_session=True,
        notes="Runs one turn via the OpenClaw gateway (default agent mm-main). Replies are never delivered to a channel.",
    ),
}


# Agents sold as a flat-fee plan, which a subscription account can classify as a subscription route.
SUBSCRIPTION_AGENTS = ("claude", "codex", "grok")
# Every agent with a billing account, in the order the dashboards list them.
BILLED_AGENTS = ("openclaw", "hermes", "claude", "codex", "grok")


def redact(argv: list[str], prompt: str) -> list[str]:
    return [PROMPT_PLACEHOLDER if a == prompt else a for a in argv]
