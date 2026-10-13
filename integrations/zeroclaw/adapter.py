"""ZeroClaw implementation of ``rcd.adapter.v1`` (free-only OpenRouter policy).

One ``zeroclaw agent -m`` process per MCD run, in its own session/process group, with a private
per-run config directory. The model call path is ``zeroclaw -> loopback ProviderProxy -> OpenRouter``
so that admission (assigned model only, verified zero-priced only), served-model metadata, usage and
cost come from the provider boundary and never from the runtime's own report of itself.

Approvals use ZeroClaw's own tool-permission prompt: the adapter answers it on stdin only after a
``resume`` decision, so ``suspend_modes`` is ``["live"]``. A live approval cannot survive an adapter
or host restart; ``recover`` reports such runs as interrupted instead of replaying them.

Gaps against the contract are listed in README.md next to this file.
"""
from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import time
from typing import Any, AsyncIterator, Mapping

from adapter_contract import (AgentAdapter, AdapterError, CancelRequest, Capabilities, Decision, Event,
                              Heartbeat, RecoveredRun, RunResult, RunSpec, RunStatus, SCHEMA_VERSION,
                              TERMINAL, can_transition, digest, error, spec_digest)

from . import callid
from .admission import FreeModelCatalog, Refusal
from .proxy import ProviderProxy
from .runtime_config import ALIAS, TOOL_MAP, render, resolve_tools

try:  # optional: the adapter validates structured output when jsonschema is installed
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only on minimal installs
    Draft202012Validator = None

MAX_PROMPT_BYTES = 100_000  # Linux MAX_ARG_STRLEN is 128 KiB for one argv string
_TERMINAL = {str(s) for s in TERMINAL}
_PROMPT = re.compile(r"Agent wants to execute: (?P<tool>\S+)\n(?P<args>.*?)\n\s*\[Y\]es / \[N\]o / \[A\]lways for (?P=tool): ",
                     re.DOTALL)
_BILLING_OK = {"free", "openrouter", "api"}  # all are served $0: anything else is refused


@dataclass(frozen=True)
class ZeroClawConfig:
    """Operator-controlled executable, private durable state and the shared provider boundary."""
    state_dir: Path
    proxy: ProviderProxy
    catalog: FreeModelCatalog
    executable: str = "zeroclaw"
    assigned_agents: tuple[str, ...] = ("zeroclaw",)
    use_systemd_scope: bool = False        # per-run cgroup (MemoryMax from limits.memory_limit_bytes)
    keep_run_dirs: bool = False            # debugging only: trace files contain model output
    tick_s: float = 0.05
    max_requests_per_run: int = 400        # hard stop on a runaway tool loop, enforced at the proxy
    mcp_servers: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # test/driver tools only


_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}
_SCAN_LIMIT, _HASH_LIMIT = 20000, 10 * 1024 * 1024


def _scan(root: str) -> dict[str, tuple[int, int]] | None:
    """(size, mtime_ns) per file, or None if the tree is too large to compare honestly."""
    found: dict[str, tuple[int, int]] = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            path = os.path.join(dirpath, name)
            try:
                stat = os.lstat(path)
            except OSError:
                continue
            found[os.path.relpath(path, root)] = (stat.st_size, stat.st_mtime_ns)
            if len(found) > _SCAN_LIMIT:
                return None
    return found


def _artifacts(root: str, before: dict[str, tuple[int, int]] | None) -> list[dict[str, Any]]:
    after = _scan(root)
    if before is None or after is None:
        return []
    out: list[dict[str, Any]] = []
    for rel in sorted(set(before) | set(after)):
        if rel in before and rel in after and before[rel] == after[rel]:
            continue
        item: dict[str, Any] = {"kind": "file", "path": rel,
                                "change": "deleted" if rel not in after else "created" if rel not in before else "modified"}
        if rel in after:
            item["bytes"] = after[rel][0]
            if after[rel][0] <= _HASH_LIMIT:
                try:
                    item["sha256"] = hashlib.sha256(Path(root, rel).read_bytes()).hexdigest()
                except OSError:
                    pass
        out.append(item)
    return out[:500]


def _redact_summary(tool: str, arguments: str) -> str:
    try:
        keys = sorted(json.loads(arguments))
        return f"{tool}({', '.join(str(k) for k in keys)[:200]})"
    except (ValueError, TypeError):
        return tool


class ZeroClawAdapter(AgentAdapter):
    name = "zeroclaw"

    def __init__(self, config: ZeroClawConfig) -> None:
        self.config = config
        config.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._runs: dict[str, dict[str, Any]] = {}
        self._keys: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._version: str | None = None

    # ------------------------------------------------------------------ capabilities
    def capabilities(self) -> Capabilities:
        if self._version is None:
            self._version = self._detect_version()
        return {"schema_version": SCHEMA_VERSION, "adapter": self.name, "runtime_version": self._version,
                "pins_model": True, "reports_model": "at_end", "disables_native_fallback": True,
                "enforces_mode": True, "structured_output": "prompted_json", "streams_events": True,
                "tool_events": True, "session": "none", "suspend_modes": ["live"], "reports_cost": True,
                "enforces_budget": "adapter",
                "resource_measurement": "cgroup" if self.config.use_systemd_scope else "psutil_tree",
                "default_model": None}

    def _detect_version(self) -> str | None:
        import subprocess
        try:
            out = subprocess.run([self.config.executable, "--version"], capture_output=True, text=True,
                                 timeout=5, check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return out[:120] or None

    # ------------------------------------------------------------------ persistence / events
    def _path(self, run_id: str) -> Path:
        return self.config.state_dir / f"{run_id}.json"

    def _run_dir(self, run_id: str) -> Path:
        return self.config.state_dir / f"{run_id}.d"

    def _save(self, run: dict[str, Any]) -> None:
        serial = {k: v for k, v in run.items() if k not in _VOLATILE}
        serial["cancel_ids"] = sorted(run["cancel_ids"])
        target = self._path(run["spec"]["run_id"])
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(serial, sort_keys=True))
        temp.chmod(0o600)
        temp.replace(target)

    def _event(self, run: dict[str, Any], kind: str, data: dict[str, Any]) -> None:
        # Any runtime evidence (trace, tool, provider receipt, prompt) is progress for
        # the per-story idle watchdog.  Wall-clock accounting remains independent.
        run["last_activity_at"] = time.monotonic()
        event = {"schema_version": SCHEMA_VERSION, "run_id": run["spec"]["run_id"], "seq": len(run["events"]) + 1,
                 "segment": run["segment"], "ts": int(time.time()), "type": kind, "data": deepcopy(data)}
        run["events"].append(event)
        run["changed"].set()
        self._save(run)

    def _set_status(self, run: dict[str, Any], new: str) -> None:
        old = run["status"]
        if not can_transition(RunStatus(old) if old else None, RunStatus(new)):
            raise RuntimeError(f"invalid local state transition {old!r}->{new!r}")
        run["status"] = new
        self._event(run, "status", {"from": old, "to": new})

    def _finish(self, run: dict[str, Any], status: str, code: str | None = None, message: str = "") -> None:
        if run["status"] in _TERMINAL:
            return
        if run["status"] == "awaiting_approval" and run.get("approval_future") and not run["approval_future"].done():
            run["approval_future"].cancel()
        self.config.proxy.close_run(run["spec"]["run_id"])
        self._collect_receipts(run)
        if run["workspace_before"] is not None:  # synchronous so the terminal result is stable
            run["artifacts"] = ([] if run["workspace_before"] is False else
                                _artifacts(run["spec"]["workspace"]["path"], run["workspace_before"]))
            run["workspace_before"] = None
            for artifact in run["artifacts"]:
                self._event(run, "artifact", artifact)
        if code:
            run["error"] = error(code, message or "ZeroClaw run did not complete")
            self._event(run, "error", run["error"])
        run["ended_at"] = int(time.time())
        self._set_status(run, status)
        self._cleanup(run["spec"]["run_id"])

    def _cleanup(self, run_id: str) -> None:
        if not self.config.keep_run_dirs:
            shutil.rmtree(self._run_dir(run_id), ignore_errors=True)

    # ------------------------------------------------------------------ start
    async def start(self, spec: RunSpec) -> dict[str, Any]:
        required = {"run_id", "idempotency_key", "prompt", "workspace", "model_policy", "limits", "budget", "context"}
        if not required <= set(spec):
            raise AdapterError("INVALID_RUN_SPEC", "Run specification is incomplete")
        async with self._lock:
            prior_id = self._keys.get(spec["idempotency_key"])
            if prior_id:
                prior = self._runs[prior_id]
                if spec_digest(prior["spec"]) != spec_digest(spec):
                    raise AdapterError("IDEMPOTENCY_CONFLICT", "Idempotency key has a different run specification")
                return {"run_id": prior_id, "status": prior["status"], "replayed": True}
            if spec["run_id"] in self._runs:
                raise AdapterError("IDEMPOTENCY_CONFLICT", "Run id already exists")
            run = {"spec": deepcopy(spec), "status": None, "events": [], "segment": 1, "started_at": int(time.time()),
                   "ended_at": None, "error": None, "output": None, "result_text": None, "exit_code": None,
                   "pid": None, "usage": {}, "cost": None, "model_report": None, "approval": None,
                   "decisions": {}, "approvals_seen": 0, "resources": {"measured_by": "not_measured"},
                   "cancel_ids": set(), "tool_calls": 0, "last_activity_at": int(time.time()),
                   "running_s": 0.0, "peak_rss": 0, "receipts_seen": 0, "trace_offset": 0, "call_seen": {},
                   "workspace_before": None, "artifacts": [], "clock": 0.0,
                   "task": None, "process": None, "changed": asyncio.Event(), "approval_future": None,
                   "pending_tools": {}}
            self._runs[spec["run_id"]] = run
            self._keys[spec["idempotency_key"]] = spec["run_id"]
            self._set_status(run, "queued")
            refusal = self._preflight(spec)
            if refusal:
                self._finish(run, "failed", *refusal)
            else:
                self._set_status(run, "running")
                run["clock"] = time.monotonic()  # the wall-clock limit includes process start-up
                before = _scan(spec["workspace"]["path"])
                run["workspace_before"] = before if before is not None else False  # False: too large to compare
                run["task"] = asyncio.create_task(self._execute(run))
            return {"run_id": spec["run_id"], "status": run["status"], "replayed": False}

    def _preflight(self, spec: RunSpec) -> tuple[str, str] | None:
        route = spec["model_policy"]["assigned"]
        if (route.get("agent") not in self.config.assigned_agents or not route.get("model")
                or spec["model_policy"].get("allow_runtime_fallback") is not False):
            return "MODEL_NOT_ALLOWED", "Run is not assigned to ZeroClaw with a model"
        if not Path(spec["workspace"]["path"]).is_dir():
            return "WORKSPACE_REJECTED", "Workspace does not exist"
        if spec["budget"].get("billing") not in _BILLING_OK:
            return "BUDGET_EXCEEDED", "Only zero-priced OpenRouter models are authorised"
        from apps.api.openrouter_costs import amount
        if amount(spec["budget"].get("max_cost_usd")) is None:
            return "BUDGET_EXCEEDED", "A finite approved run cap is required"
        try:
            self.config.catalog.admit(route["model"])
            self.config.proxy.admit_account()
        except Refusal as refusal:
            return refusal.code, refusal.message
        if spec.get("session", {}).get("mode") == "resume":
            return "RUNTIME_INCOMPATIBLE", "ZeroClaw one-shot runs have no resumable session"
        if len(spec["prompt"].encode()) > MAX_PROMPT_BYTES:
            return "INVALID_RUN_SPEC", "Prompt exceeds the ZeroClaw command-line limit"
        try:
            resolve_tools(spec["workspace"].get("allowed_tools"), self.config.mcp_servers)
        except KeyError:
            return "TOOL_DENIED", "Run requests a tool ZeroClaw cannot grant"
        return None

    # ------------------------------------------------------------------ execution
    def _argv(self, spec: RunSpec, run_dir: Path, envelope: str) -> list[str]:
        argv = [self.config.executable, "agent", "--config-dir", str(run_dir), "-a", ALIAS,
                "-m", envelope, "--model", spec["model_policy"]["assigned"]["model"]]
        if self.config.use_systemd_scope:
            prefix = ["systemd-run", "--user", "--scope", "--quiet", "-p", "TasksMax=256"]
            if spec["limits"].get("memory_limit_bytes"):
                prefix += ["-p", f"MemoryMax={int(spec['limits']['memory_limit_bytes'])}"]
            argv = prefix + ["--"] + argv
        return argv

    def _write_config(self, run: dict[str, Any]) -> Path:
        spec = run["spec"]
        run_id = spec["run_id"]
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(mode=0o700, exist_ok=True)
        model = spec["model_policy"]["assigned"]["model"]
        token = self.config.proxy.register(run_id, model, max_tokens=spec["budget"].get("max_output_tokens"),
                                           max_requests=self.config.max_requests_per_run)
        servers = {name: {**server, "env": {k: str(v).replace("{run_id}", run_id)
                                            for k, v in server.get("env", {}).items()}}
                   for name, server in self.config.mcp_servers.items()}
        allowed = resolve_tools(spec["workspace"].get("allowed_tools"), servers)
        # Denied names that ZeroClaw has no equivalent for are already unreachable; skip them.
        denied = resolve_tools([t for t in spec["workspace"].get("denied_tools", []) if t in TOOL_MAP], {})
        text = render(proxy_url=self.config.proxy.base_url, token=token, model=model,
                      workspace=spec["workspace"]["path"], mode=spec["workspace"]["mode"], allowed=allowed,
                      denied=denied, timeout_s=spec["limits"]["timeout_s"],
                      max_tokens=spec["budget"].get("max_output_tokens"), max_turns=spec["limits"].get("max_turns"),
                      transient_retries=spec["limits"].get("max_transient_retries", 2), mcp_servers=servers)
        path = run_dir / "config.toml"
        path.write_text(text)
        path.chmod(0o600)
        return run_dir

    async def _execute(self, run: dict[str, Any]) -> None:
        spec = run["spec"]
        try:
            run_dir = self._write_config(run)
            envelope = spec["prompt"]
            if spec["output"].get("format") == "json":
                envelope += ("\n\nReturn ONLY one JSON object matching this schema as your final answer: " +
                             json.dumps(spec["output"].get("json_schema", {"type": "object"}), separators=(",", ":")))
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(run_dir), "LANG": "C.UTF-8",
                   "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""), "NO_COLOR": "1"}
            proc = await asyncio.create_subprocess_exec(
                *self._argv(spec, run_dir, envelope), cwd=spec["workspace"]["path"], env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True)
            run["process"], run["pid"] = proc, proc.pid
            self._event(run, "log", {"stream": "adapter", "text": f"process started pid={proc.pid}"})
            stdout_task = asyncio.create_task(proc.stdout.read())
            stderr_task = asyncio.create_task(self._pump_stderr(run, proc))
            try:
                await self._supervise(run, proc)
            finally:
                for task in (stderr_task,):
                    task.cancel()
            stdout = b""
            try:
                stdout = await asyncio.wait_for(stdout_task, 2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                stdout_task.cancel()
            self._drain(run, run_dir)
            if run["status"] not in _TERMINAL and not run.get("stopping"):
                self._conclude(run, stdout.decode("utf-8", "replace").strip())
        except FileNotFoundError:
            self._finish(run, "failed", "RUNTIME_UNAVAILABLE", "ZeroClaw executable was not found")
        except asyncio.CancelledError:
            raise
        except Exception:  # never leak internals; the run record carries the failure
            self._finish(run, "failed", "ADAPTER_INTERNAL", "Adapter failed while supervising ZeroClaw")

    async def _supervise(self, run: dict[str, Any], proc: asyncio.subprocess.Process) -> None:
        spec, run_dir = run["spec"], self._run_dir(run["spec"]["run_id"])
        limits, last = spec["limits"], run["clock"]
        approval_started = 0.0
        while proc.returncode is None and run["status"] not in _TERMINAL:
            wait = self.config.tick_s
            if run["status"] == "running":  # wake exactly at the deadline, not up to a tick late
                wait = min(wait, max(0.001, limits["timeout_s"] - run["running_s"] - (time.monotonic() - last)))
            try:
                await asyncio.wait_for(proc.wait(), wait)
            except asyncio.TimeoutError:
                pass
            now = time.monotonic()
            self._drain(run, run_dir)
            flags = self.config.proxy.flags(spec["run_id"])
            if flags:
                await self._terminate(run)
                code = ("MODEL_MISMATCH" if "model_mismatch" in flags else
                        "BUDGET_EXCEEDED" if "cost_breach" in flags else "RESULT_INVALID")
                self._finish(run, "failed", code, "Provider boundary rejected a response")
                return
            if run["status"] == "running":
                run["running_s"] += now - last
                if run["running_s"] >= limits["timeout_s"]:
                    await self._terminate(run)
                    self._finish(run, "timed_out", "TIMEOUT", "Run exceeded its wall-clock limit")
                    return
                idle = limits.get("idle_timeout_s")
                if idle and now - run["last_activity_at"] >= idle:
                    await self._terminate(run)
                    self._finish(run, "timed_out", "TIMEOUT", "Run exceeded its idle time limit")
                    return
            elif run["status"] == "awaiting_approval":
                approval_started = approval_started or now
                if limits.get("approval_timeout_s") and now - approval_started >= limits["approval_timeout_s"]:
                    await self._terminate(run)
                    self._finish(run, "timed_out", "APPROVAL_TIMEOUT", "No human decision arrived in time")
                    return
            if run["status"] != "awaiting_approval":
                approval_started = 0.0
            last = now

    async def _pump_stderr(self, run: dict[str, Any], proc: asyncio.subprocess.Process) -> None:
        buffer, consumed = "", 0
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                return
            buffer = (buffer + chunk.decode("utf-8", "replace"))[-65536:]
            match = _PROMPT.search(buffer, consumed)
            while match:
                consumed = match.end()
                await self._await_decision(run, proc, match["tool"], match["args"])
                match = _PROMPT.search(buffer, consumed)

    async def _await_decision(self, run: dict[str, Any], proc: asyncio.subprocess.Process, tool: str, args: str) -> None:
        if run["status"] != "running":
            return
        run["approvals_seen"] += 1
        approval = {"approval_id": f"{run['spec']['run_id']}:{run['approvals_seen']}", "kind": "tool_permission",
                    "question": f"ZeroClaw wants to run tool {tool}: {args.strip()[:2000]}",
                    "options": [{"id": "approve", "label": "Run the tool"}, {"id": "reject", "label": "Cancel the run"}],
                    "resume_mode": "live", "requested_at": int(time.time())}
        run["approval"], run["approval_future"] = approval, asyncio.get_running_loop().create_future()
        self._set_status(run, "awaiting_approval")
        self._event(run, "approval_requested", approval)
        try:
            verdict = await run["approval_future"]
        except asyncio.CancelledError:
            return
        if verdict == "approve" and proc.stdin and proc.returncode is None:
            proc.stdin.write(b"y\n")
            await proc.stdin.drain()
        run["approval_future"] = None

    def _drain(self, run: dict[str, Any], run_dir: Path) -> None:
        """Pull new runtime-trace lines and provider receipts into events, once each, in order."""
        trace = run_dir / "data" / "state" / "runtime-trace.jsonl"
        try:
            with trace.open("rb") as handle:
                handle.seek(run["trace_offset"])
                data = handle.read()
        except OSError:
            data = b""
        end = data.rfind(b"\n") + 1  # never parse a half-written line
        run["trace_offset"] += end
        for line in data[:end].splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            self._trace_event(run, record)
        self._collect_receipts(run)
        self._sample_resources(run)

    def _trace_event(self, run: dict[str, Any], record: Mapping[str, Any]) -> None:
        attrs, message = record.get("attributes", {}), record.get("message")
        tool = str(attrs.get("tool", ""))
        server, _, bare = tool.partition("__")
        name = bare if bare and server in self.config.mcp_servers else tool
        if message == "tool_call_start":
            run["tool_calls"] += 1
            call_id = callid.call_id(run["spec"]["run_id"], name, attrs.get("arguments", ""), run["call_seen"])
            run["pending_tools"].setdefault(tool, deque()).append(call_id)
            self._event(run, "tool_call", {"call_id": call_id, "name": name,
                                           "summary": _redact_summary(name, attrs.get("arguments", ""))})
        elif message == "tool_call_result":
            pending = run["pending_tools"].get(tool)
            call_id = pending.popleft() if pending else callid.call_id(run["spec"]["run_id"], name, "", run["call_seen"])
            reason = attrs.get("error_reason")
            data = {"call_id": call_id, "ok": reason is None,
                    "summary": f"{name} {'ok' if reason is None else 'failed'}"}
            if reason and "denied" in str(reason).lower():
                data["denied"] = True
            self._event(run, "tool_result", data)
        run["last_activity_at"] = int(time.time())

    def _collect_receipts(self, run: dict[str, Any]) -> None:
        receipts = self.config.proxy.receipts(run["spec"]["run_id"])
        new_receipts = receipts[run["receipts_seen"]:]
        for index in range(run["receipts_seen"], len(receipts)):
            receipt = receipts[index]
            if index == 0:
                self._event(run, "model", {"requested": run["spec"]["model_policy"]["assigned"]["model"],
                                           "reported": receipt["model"], "provider": receipt["provider"],
                                           "session_id": None})
        if len(receipts) > run["receipts_seen"]:
            run["receipts_seen"] = len(receipts)
            run["usage"] = {"input_tokens": sum(r["usage"]["input_tokens"] for r in receipts),
                            "output_tokens": sum(r["usage"]["output_tokens"] for r in receipts),
                            "requests": len(receipts), "tool_calls": run["tool_calls"]}
            run["cost"] = {"usd": sum(r["cost_usd"] for r in receipts),
                           "source": "reported" if all(r["cost_source"] == "reported" for r in receipts) else "estimated",
                           "billing": "free", "limit_usd": run["spec"]["budget"].get("max_cost_usd")}
            run["model_report"] = {"reported": receipts[-1]["model"], "provider": receipts[-1]["provider"]}
            self._event(run, "usage", {"cumulative": run["usage"], "cost": run["cost"],
                                       "provider_receipts": new_receipts})
        elif run["usage"]:
            run["usage"]["tool_calls"] = run["tool_calls"]

    def _sample_resources(self, run: dict[str, Any]) -> None:
        pid = run.get("pid")
        if not pid or run["status"] in _TERMINAL:
            return
        try:
            if self.config.use_systemd_scope:
                group = Path("/sys/fs/cgroup") / Path(f"/proc/{pid}/cgroup").read_text().strip().split("::")[-1].lstrip("/")
                current = int((group / "memory.current").read_text())
                peak = int((group / "memory.peak").read_text()) if (group / "memory.peak").exists() else current
                cpu = dict(line.split() for line in (group / "cpu.stat").read_text().splitlines())
                run["resources"] = {"measured_by": "cgroup", "rss_bytes": current, "peak_rss_bytes": peak,
                                    "cpu_user_s": int(cpu["user_usec"]) / 1e6, "cpu_system_s": int(cpu["system_usec"]) / 1e6}
            else:
                import psutil
                root = psutil.Process(pid)
                tree = [root, *root.children(recursive=True)]
                rss = sum(p.memory_info().rss for p in tree)
                run["peak_rss"] = max(run["peak_rss"], rss)
                times = [p.cpu_times() for p in tree]
                run["resources"] = {"measured_by": "psutil_tree", "rss_bytes": rss, "peak_rss_bytes": run["peak_rss"],
                                    "cpu_user_s": sum(t.user for t in times), "cpu_system_s": sum(t.system for t in times),
                                    "processes": len(tree)}
        except Exception:  # measurement must never affect the run
            pass

    def _conclude(self, run: dict[str, Any], stdout: str) -> None:
        spec, run_id = run["spec"], run["spec"]["run_id"]
        proc = run["process"]
        run["exit_code"] = proc.returncode
        proxy = self.config.proxy
        if proc.returncode:
            refusals, statuses = proxy.refusals(run_id), [s for s in proxy.statuses(run_id) if s >= 400]
            if refusals:
                code, message = refusals[-1]
                self._finish(run, "failed", code if code in _SAFE_REFUSALS else "AGENT_ERROR", message)
            elif statuses:
                code = _STATUS_CODES.get(statuses[-1], "PROVIDER_ERROR" if statuses[-1] >= 500 else "AGENT_ERROR")
                self._finish(run, "failed", code, f"Provider returned HTTP {statuses[-1]}")
            else:
                self._finish(run, "failed", "AGENT_ERROR", "ZeroClaw exited with a failure status")
            return
        if not proxy.receipts(run_id) and spec["model_policy"].get("require_model_report"):
            self._finish(run, "failed", "MODEL_NOT_ENFORCEABLE", "No provider response proves which model served the run")
            return
        run["result_text"] = stdout[:300000] or None
        if not stdout:
            self._finish(run, "failed", "RESULT_MISSING", "ZeroClaw produced no final answer")
            return
        if spec["output"].get("format") == "json":
            try:
                parsed = json.loads(stdout[stdout.find("{"):stdout.rfind("}") + 1])
                if Draft202012Validator and spec["output"].get("json_schema"):
                    Draft202012Validator(spec["output"]["json_schema"]).validate(parsed)
            except Exception:
                self._finish(run, "failed", "RESULT_INVALID", "Final answer is not valid JSON for the requested schema")
                return
            run["output"] = parsed
        self._finish(run, "succeeded")

    async def _terminate(self, run: dict[str, Any]) -> None:
        proc = run.get("process")
        if not proc or proc.returncode is not None:
            return
        run["stopping"] = True  # whoever stopped it records the outcome; _execute must not conclude
        self.config.proxy.close_run(run["spec"]["run_id"])
        grace = run["spec"]["limits"].get("kill_grace_s", 5)
        for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 5)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(proc.wait(), wait)
                return
            except asyncio.TimeoutError:
                continue

    # ------------------------------------------------------------------ queries
    def _get(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if not run:
            raise AdapterError("UNKNOWN_RUN", "Unknown ZeroClaw run")
        return run

    async def events(self, run_id: str, after_seq: int = 0) -> AsyncIterator[Event]:
        run = self._get(run_id)
        cursor = after_seq
        while True:
            run["changed"].clear()
            for event in list(run["events"]):
                if event["seq"] > cursor:
                    cursor = event["seq"]
                    yield deepcopy(event)
            if run["status"] in _TERMINAL or run["status"] == "awaiting_approval":
                return
            await run["changed"].wait()

    async def result(self, run_id: str) -> RunResult:
        run = self._get(run_id)
        if run["status"] in {"queued", "running"}:
            raise AdapterError("INVALID_TRANSITION", "Result is not ready")
        spec = run["spec"]
        report = run["model_report"] or {}
        requested = spec["model_policy"]["assigned"]["model"]
        # No provider response means no inference happened: zero spend, and nothing was reported.
        cost = run["cost"] or {"usd": 0.0, "source": "not_reported", "billing": "free",
                               "limit_usd": spec["budget"].get("max_cost_usd")}
        if cost["limit_usd"] is None:
            cost.pop("limit_usd")
        result: RunResult = {
            "schema_version": SCHEMA_VERSION, "run_id": run_id, "idempotency_key": spec["idempotency_key"],
            "status": run["status"], "started_at": run["started_at"], "ended_at": run["ended_at"],
            "duration_s": max(0, (run["ended_at"] or int(time.time())) - run["started_at"]),
            "exit_code": run["exit_code"],
            "model": {"requested": requested, "reported": report.get("reported"), "provider": report.get("provider"),
                      "route": spec["model_policy"]["assigned"],
                      "matches_assignment": None if not report else report["reported"] == requested},
            "session": {"session_id": None, "resumable": False},
            "usage": {"input_tokens": 0, "output_tokens": 0, **run["usage"]}, "cost": cost, "resources": deepcopy(run["resources"]),
            "artifacts": deepcopy(run["artifacts"]), "result_text": run["result_text"], "structured_output": deepcopy(run["output"]),
            "error": deepcopy(run["error"]), "context_digest": spec["context"].get("digest") or digest(spec["prompt"]),
            "last_seq": len(run["events"])}
        if run["status"] == "awaiting_approval":
            result["approval"] = deepcopy(run["approval"])
        return result

    async def heartbeat(self, run_id: str) -> Heartbeat:
        run = self._get(run_id)
        proc = run.get("process")
        alive = bool(proc and proc.returncode is None and run["status"] in {"running", "awaiting_approval"})
        remaining = max(0.0, run["spec"]["limits"]["timeout_s"] - run["running_s"])
        return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "status": run["status"], "alive": alive,
                "pid": run["pid"], "last_seq": len(run["events"]), "last_activity_at": run["last_activity_at"],
                "deadline_at": int(time.time() + remaining) if run["status"] == "running" else None,
                "ts": int(time.time()), "resources": deepcopy(run["resources"])}

    # ------------------------------------------------------------------ control
    async def cancel(self, request: CancelRequest) -> dict[str, Any]:
        run = self._get(request["run_id"])
        if request["request_id"] in run["cancel_ids"]:
            return {"run_id": request["run_id"], "status": run["status"], "replayed": True}
        if run["status"] in _TERMINAL:
            return {"run_id": request["run_id"], "status": run["status"], "replayed": True}
        run["cancel_ids"].add(request["request_id"])
        self.config.proxy.close_run(request["run_id"])  # no further provider request, even before the kill lands
        await self._terminate(run)
        self._finish(run, "cancelled", "CANCELLED", "Run was cancelled")
        return {"run_id": request["run_id"], "status": run["status"], "replayed": False}

    async def resume(self, decision: Decision) -> dict[str, Any]:
        run = self._get(decision["run_id"])
        previous = run["decisions"].get(decision["approval_id"])
        if previous:
            if previous["decision_id"] == decision["decision_id"]:
                return {"run_id": decision["run_id"], "status": run["status"], "replayed": True}
            raise AdapterError("DECISION_CONFLICT", "That approval already has a different decision")
        if run["status"] != "awaiting_approval" or not run["approval"] \
                or run["approval"]["approval_id"] != decision["approval_id"]:
            raise AdapterError("INVALID_TRANSITION", "Run is not awaiting that approval")
        if decision["verdict"] == "answer":
            raise AdapterError("INVALID_TRANSITION", "A tool permission accepts approve or reject only")
        run["decisions"][decision["approval_id"]] = {"decision_id": decision["decision_id"], "verdict": decision["verdict"]}
        if decision["verdict"] == "approve":
            run["segment"] += 1  # the decision itself opens the new segment
        self._event(run, "decision_applied", {"decision_id": decision["decision_id"],
                                              "approval_id": decision["approval_id"], "verdict": decision["verdict"]})
        if decision["verdict"] == "reject":
            await self._terminate(run)
            self._finish(run, "cancelled", "DECISION_REJECTED", "A human rejected the tool request")
        else:
            run["approval"] = None
            self._set_status(run, "running")
            future = run["approval_future"]
            if future and not future.done():
                future.set_result("approve")
        return {"run_id": decision["run_id"], "status": run["status"], "replayed": False}

    # ------------------------------------------------------------------ recovery
    def _is_ours(self, pid: int, run_id: str) -> bool:
        """Only signal a pid whose command line is still this run's ZeroClaw (guards against pid reuse)."""
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            return False
        return self._run_dir(run_id).name in cmdline

    async def recover(self) -> list[RecoveredRun]:
        recovered: list[RecoveredRun] = []
        for path in sorted(self.config.state_dir.glob("*.json")):
            data = json.loads(path.read_text())
            data["cancel_ids"] = set(data.get("cancel_ids", []))
            spec = data["spec"]
            run = {**data, "task": None, "process": None, "changed": asyncio.Event(), "approval_future": None,
                   "pending_tools": {}}
            outcome = "finished_while_down"
            if data["status"] in {"queued", "running", "awaiting_approval"}:
                pid = data.get("pid")
                if isinstance(pid, int) and pid > 1 and self._is_ours(pid, spec["run_id"]):
                    try:
                        os.killpg(pid, signal.SIGKILL)  # never relaunch: MCD decides on any retry
                    except (ProcessLookupError, PermissionError):
                        pass
                run["status"] = "running" if data["status"] == "queued" else data["status"]
                self._finish(run, "failed", "INTERRUPTED", "ZeroClaw cannot be reattached after a restart")
                outcome = "interrupted"
            self._runs[spec["run_id"]] = run
            self._keys[spec["idempotency_key"]] = spec["run_id"]
            self._cleanup(spec["run_id"])
            recovered.append({"run_id": spec["run_id"], "idempotency_key": spec["idempotency_key"],
                              "outcome": outcome, "status": run["status"], "last_seq": len(run["events"])})
        return recovered


_VOLATILE = {"task", "process", "changed", "approval_future", "pending_tools", "stopping"}
_SAFE_REFUSALS = {"MODEL_NOT_ALLOWED", "BUDGET_EXCEEDED", "PROVIDER_AUTH", "MODEL_MISMATCH", "RESULT_INVALID",
                  "TOOL_DENIED"}
_STATUS_CODES = {429: "PROVIDER_RATE_LIMITED", 402: "PROVIDER_QUOTA_EXHAUSTED", 401: "PROVIDER_AUTH",
                 403: "PROVIDER_AUTH", 504: "PROVIDER_ERROR"}
