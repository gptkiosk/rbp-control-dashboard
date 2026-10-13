"""Fail-closed PicoClaw implementation of ``rcd.adapter.v1``.

PicoClaw is deliberately run one-shot, with an isolated config/home per MCD run.
It is never allowed to use its default workspace, model, gateway, cron, or fallback
configuration.  This module has no provider dependency and never reads or writes an
OpenRouter secret; the operator supplies it through the child process environment.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import time
from typing import Any, AsyncIterator

from adapter_contract import (AgentAdapter, AdapterError, CancelRequest, Capabilities, Decision,
                              Event, Heartbeat, RecoveredRun, RunResult, RunSpec, RunStatus,
                              SCHEMA_VERSION, TERMINAL, can_transition, digest, error, spec_digest)


@dataclass(frozen=True)
class PicoClawConfig:
    """Operator-controlled executable and durable, private adapter state directory."""
    state_dir: Path
    executable: str = "picoclaw"
    openrouter_key_env: str = "OPENROUTER_API_KEY"
    assigned_agents: tuple[str, ...] = ("picoclaw",)


class PicoClawAdapter(AgentAdapter):
    name = "picoclaw"

    def __init__(self, config: PicoClawConfig) -> None:
        self.config = config
        self.config.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._runs: dict[str, dict[str, Any]] = {}
        self._keys: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def capabilities(self) -> Capabilities:
        # Honest capability reporting is intentional: this adapter is not eligible for
        # a paid live conformance run until a provider boundary supplies cost admission.
        return {"schema_version": SCHEMA_VERSION, "adapter": self.name, "runtime_version": None,
                "pins_model": True, "reports_model": "never",
                "disables_native_fallback": True, "enforces_mode": False,
                "structured_output": "prompted_json", "streams_events": False,
                "tool_events": False, "session": "preassigned", "suspend_modes": [],
                "reports_cost": False,
                "enforces_budget": "none",
                "resource_measurement": "not_measured"}

    def _path(self, run_id: str) -> Path:
        return self.config.state_dir / f"{run_id}.json"

    def _save(self, run: dict[str, Any]) -> None:
        # Persist only redacted contract data. Config and stdout/stderr are never persisted.
        serial = {k: v for k, v in run.items() if k not in {"task", "changed", "process"}}
        serial["cancel_ids"] = sorted(run["cancel_ids"])
        target = self._path(run["spec"]["run_id"])
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(serial, sort_keys=True))
        temp.chmod(0o600)
        temp.replace(target)

    def _event(self, run: dict[str, Any], kind: str, data: dict[str, Any]) -> None:
        event = {"schema_version": SCHEMA_VERSION, "run_id": run["spec"]["run_id"],
                 "seq": len(run["events"]) + 1, "segment": run["segment"],
                 "ts": int(time.time()), "type": kind, "data": deepcopy(data)}
        run["events"].append(event)
        run["changed"].set()
        self._save(run)

    def _set_status(self, run: dict[str, Any], new: str) -> None:
        old = run["status"]
        if not can_transition(RunStatus(old) if old else None, RunStatus(new)):
            raise RuntimeError(f"invalid local state transition {old!r}->{new!r}")
        run["status"] = new
        self._event(run, "status", {"from": old, "to": new})

    def _finish(self, run: dict[str, Any], status: str, code: str | None = None) -> None:
        if run["status"] in {str(v) for v in TERMINAL}:
            return
        if code:
            run["error"] = error(code, "PicoClaw run did not complete")
            self._event(run, "error", run["error"])
        run["ended_at"] = int(time.time())
        self._set_status(run, status)

    def _allowed_route(self, spec: RunSpec) -> bool:
        route = spec["model_policy"]["assigned"]
        return (route.get("agent") in self.config.assigned_agents and bool(route.get("model"))
                and spec["model_policy"].get("allow_runtime_fallback") is False)

    def _runtime_config(self, run: dict[str, Any]) -> Path:
        spec = run["spec"]
        home = self.config.state_dir / spec["run_id"]
        home.mkdir(mode=0o700, exist_ok=True)
        model = spec["model_policy"]["assigned"]["model"]
        # The alias is fixed and --model below must select it.  No fallback model,
        # gateway, channel, cron, or MCP configuration is installed.
        config = {"version": 2, "agents": {"defaults": {"workspace": spec["workspace"]["path"],
                   "model": "rcd-assigned", "max_parallel_turns": 1}},
                  "model_list": [{"model_name": "rcd-assigned", "provider": "openrouter",
                                  "model": model, "api_base": "https://openrouter.ai/api/v1"}]}
        path = home / "config.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        return path

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
            run = {"spec": deepcopy(spec), "status": None, "events": [], "segment": 1,
                   "started_at": int(time.time()), "ended_at": None, "error": None,
                   "output": None, "reported_model": None, "exit_code": None,
                   "task": None, "process": None, "changed": asyncio.Event(), "cancel_ids": set()}
            self._runs[spec["run_id"]] = run
            self._keys[spec["idempotency_key"]] = spec["run_id"]
            self._set_status(run, "queued")
            workspace = Path(spec["workspace"]["path"])
            if not workspace.is_dir():
                self._finish(run, "failed", "WORKSPACE_REJECTED")
            elif not self._allowed_route(spec):
                self._finish(run, "failed", "MODEL_NOT_ALLOWED")
            elif self.capabilities()["enforces_budget"] == "none":
                self._finish(run, "failed", "BUDGET_EXCEEDED")
            else:
                self._set_status(run, "running")
                run["task"] = asyncio.create_task(self._execute(run))
            return {"run_id": spec["run_id"], "status": run["status"], "replayed": False}

    async def _execute(self, run: dict[str, Any]) -> None:
        spec = run["spec"]
        try:
            config_path = self._runtime_config(run)
            env = {"PATH": os.environ.get("PATH", ""), "PICOCLAW_CONFIG": str(config_path),
                   "PICOCLAW_HOME": str(config_path.parent), self.config.openrouter_key_env: os.environ.get(self.config.openrouter_key_env, "")}
            if not env[self.config.openrouter_key_env]:
                self._finish(run, "failed", "PROVIDER_AUTH"); return
            envelope = (spec["prompt"] + "\n\nReturn ONLY one JSON object matching this schema: " +
                        json.dumps(spec["output"].get("json_schema", {"type": "object"}), separators=(",", ":")))
            proc = await asyncio.create_subprocess_exec(self.config.executable, "agent", "-m", envelope,
                "--session", spec["session"].get("session_id", spec["run_id"]), "--model", "rcd-assigned",
                cwd=spec["workspace"]["path"], env=env, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True)
            run["process"] = proc
            run["pid"] = proc.pid
            self._event(run, "process", {"pid": proc.pid})
            try:
                stdout, _stderr = await asyncio.wait_for(proc.communicate(), spec["limits"]["timeout_s"])
            except TimeoutError:
                await self._terminate(run); self._finish(run, "timed_out", "TIMEOUT"); return
            run["exit_code"] = proc.returncode
            if proc.returncode:
                self._finish(run, "failed", "AGENT_ERROR"); return
            try:
                text = stdout.decode("utf-8", "replace").strip()
                run["output"] = json.loads(text[text.find("{"):text.rfind("}") + 1])
            except (ValueError, json.JSONDecodeError):
                self._finish(run, "failed", "RESULT_INVALID"); return
            # PicoClaw CLI does not return signed provider metadata. Requested model is not
            # presented as a provider fact; a live driver must obtain receipts independently.
            self._event(run, "model", {"requested": spec["model_policy"]["assigned"]["model"], "reported": None})
            self._finish(run, "succeeded")
        except FileNotFoundError:
            self._finish(run, "failed", "RUNTIME_UNAVAILABLE")
        except asyncio.CancelledError:
            raise
        except Exception:
            self._finish(run, "failed", "ADAPTER_INTERNAL")

    async def _terminate(self, run: dict[str, Any]) -> None:
        proc = run.get("process")
        if not proc or proc.returncode is not None: return
        try: os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError: return
        try: await asyncio.wait_for(proc.wait(), run["spec"]["limits"].get("kill_grace_s", 2))
        except TimeoutError:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            await proc.wait()

    async def events(self, run_id: str, after_seq: int = 0) -> AsyncIterator[Event]:
        run = self._runs.get(run_id)
        if not run: raise AdapterError("UNKNOWN_RUN", "Unknown PicoClaw run")
        cursor = after_seq
        while True:
            run["changed"].clear()
            for event in run["events"]:
                if event["seq"] > cursor:
                    cursor = event["seq"]; yield deepcopy(event)
            if run["status"] not in {"queued", "running"}: return
            await run["changed"].wait()

    async def result(self, run_id: str) -> RunResult:
        run = self._runs.get(run_id)
        if not run: raise AdapterError("UNKNOWN_RUN", "Unknown PicoClaw run")
        if run["status"] in {"queued", "running"}: raise AdapterError("INVALID_TRANSITION", "Result is not ready")
        spec = run["spec"]
        return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "idempotency_key": spec["idempotency_key"],
                "status": run["status"], "started_at": run["started_at"], "ended_at": run["ended_at"],
                "duration_s": max(0, (run["ended_at"] or int(time.time())) - run["started_at"]),
                "exit_code": run["exit_code"], "model": {"requested": spec["model_policy"]["assigned"]["model"],
                "reported": None, "provider": None,
                "route": spec["model_policy"]["assigned"], "matches_assignment": None},
                "session": {"session_id": spec["session"].get("session_id", run_id), "resumable": False},
                "usage": {}, "cost": {"usd": None, "source": "not_reported", "billing": spec["budget"].get("billing", "unknown"), "limit_usd": spec["budget"].get("max_cost_usd")},
                "resources": {"measured_by": "not_measured"}, "artifacts": [], "result_text": None,
                "structured_output": deepcopy(run["output"]), "error": deepcopy(run["error"]),
                "context_digest": spec["context"].get("digest") or digest(spec["prompt"]), "last_seq": len(run["events"])}

    async def cancel(self, request: CancelRequest) -> dict[str, Any]:
        run = self._runs.get(request["run_id"])
        if not run: raise AdapterError("UNKNOWN_RUN", "Unknown PicoClaw run")
        if request["request_id"] in run["cancel_ids"]: return {"run_id": request["run_id"], "status": run["status"], "replayed": True}
        run["cancel_ids"].add(request["request_id"])
        if run["status"] not in {str(v) for v in TERMINAL}:
            await self._terminate(run); self._finish(run, "cancelled", "CANCELLED")
        return {"run_id": request["run_id"], "status": run["status"], "replayed": False}

    async def resume(self, decision: Decision) -> dict[str, Any]:
        raise AdapterError("INVALID_TRANSITION", "PicoClaw CLI has no durable approval checkpoint")

    async def heartbeat(self, run_id: str) -> Heartbeat:
        run = self._runs.get(run_id)
        if not run: raise AdapterError("UNKNOWN_RUN", "Unknown PicoClaw run")
        proc = run.get("process")
        return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "status": run["status"],
                "alive": bool(proc and proc.returncode is None and run["status"] == "running"),
                "pid": proc.pid if proc else None, "last_seq": len(run["events"]), "ts": int(time.time()),
                "resources": {"measured_by": "not_measured"}}

    async def recover(self) -> list[RecoveredRun]:
        recovered: list[RecoveredRun] = []
        for path in self.config.state_dir.glob("*.json"):
            data = json.loads(path.read_text())
            # There is no safe CLI reattach protocol. Never resume/replay it after restart.
            if data["status"] in {"queued", "running"}:
                pid = data.get("pid")
                if isinstance(pid, int) and pid > 1:
                    try:
                        os.killpg(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        # The state file is private, but never signal a process we cannot own.
                        pass
                data["status"] = "failed"; data["error"] = error("INTERRUPTED", "PicoClaw cannot be reattached after restart")
                data["ended_at"] = int(time.time()); path.write_text(json.dumps(data, sort_keys=True)); path.chmod(0o600)
            recovered.append({"run_id": data["spec"]["run_id"], "idempotency_key": data["spec"]["idempotency_key"],
                              "outcome": "interrupted" if data["status"] == "failed" else "finished_while_down",
                              "status": data["status"], "last_seq": len(data["events"])})
        return recovered
