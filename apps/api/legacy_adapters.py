"""Compatibility adapters for the existing CLI runtimes.

Workflow authority remains in Dispatcher. Commands are prepared by its existing
AgentSpec builders; this module owns only process execution and contract views.
No new model, budget or approval policy is imposed on legacy routes.

Each agent runs under run_supervisor.py in its own session, writing to run-N.stdout /
run-N.stderr and an fsynced run-N.exit record, so it outlives an API crash. The
follower tails those files. After a restart, recover() reattaches to a live supervisor
(identified by its exit path in the command line), or replays a run that finished while
the API was down. It never relaunches work.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil
from sqlalchemy import select
from adapter_contract import (AdapterError, LEGACY_STAGE, SCHEMA_VERSION, digest,
                              error, run_key, spec_digest)
from models import Card, Run
from profiles import SAVED_KEY_AGENTS, saved_openrouter_key
from operator_boundary import runner_env
from settings import tool_search_dirs
from db import durable_sessions

LINE_LIMIT = 16 * 1024 * 1024
# Leave scheduler/polling headroom beneath the story SLA: a stubborn process is
# SIGKILLed before the wall-clock deadline plus five seconds.
KILL_GRACE_S = 4.0
POLL_S = 0.2
READ_CHUNK = 1024 * 1024
EXTRA_PATH = tool_search_dirs()
SUPERVISOR = Path(__file__).resolve().parent / "run_supervisor.py"
LOST_ERROR = ("The agent process was killed outside MCD (for example kill -9 or the out-of-memory "
              "killer) before it recorded a result.")


@dataclass
class ProcessHandle:
    proc: asyncio.subprocess.Process | None = None
    cancel_requested: bool = False
    pid: int | None = None      # supervisor pid = process group id
    marker: str | None = None   # exit path; present in the supervisor's command line


def run_files(runs_dir: Path, run_id) -> SimpleNamespace:
    base = Path(runs_dir) / f"run-{run_id}"
    return SimpleNamespace(stdout=base.with_suffix(".stdout"), stderr=base.with_suffix(".stderr"),
                           exit=base.with_suffix(".exit"))


def read_exit(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return None


def supervisor_alive(pid: int | None, marker: str | None) -> bool:
    """True if `pid` is still this run's supervisor. A reused pid fails the marker check."""
    if not pid or not marker:
        return False
    try:
        proc = psutil.Process(pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            return False
        return marker in proc.cmdline()
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except psutil.AccessDenied:
        raise AdapterError("RUNTIME_UNAVAILABLE", "Cannot verify the recorded supervisor identity")


def find_supervisor(marker: str) -> int | None:
    """Locate a supervisor whose pid was never recorded (crash between spawn and commit)."""
    # Enumeration failure must propagate. It is not proof that a supervisor
    # spawned just before the API died is absent.
    for proc in psutil.process_iter(["pid", "cmdline"]):
        if marker in (proc.info.get("cmdline") or []):
            return proc.info["pid"]
    return None


def reap_group(pgid: int | None, since: float) -> None:
    """SIGKILL agent processes left in a dead supervisor's group (created after `since`)."""
    if not pgid:
        return
    for proc in psutil.process_iter(["pid", "create_time"]):
        try:
            if os.getpgid(proc.info["pid"]) == pgid and proc.info["create_time"] >= since - 1:
                os.kill(proc.info["pid"], signal.SIGKILL)
        except (OSError, psutil.Error):
            pass


class _Tail:
    """Incremental line reader over a file another process appends to."""

    def __init__(self, path: Path) -> None:
        self.path, self.stream, self.buffer = path, None, b""

    def lines(self, final: bool = False) -> list[str]:
        """Complete lines since the last call (one chunk), or everything left when final."""
        if self.stream is None:
            try:
                self.stream = open(self.path, "rb")
            except FileNotFoundError:
                return []
        out: list[bytes] = []
        while True:
            data = self.stream.read(READ_CHUNK)
            parts = (self.buffer + data).split(b"\n")
            self.buffer = parts.pop()
            if len(self.buffer) > LINE_LIMIT:
                parts.append(self.buffer)
                self.buffer = b""
            out += parts
            if not final or not data:
                break
        if final and self.buffer:
            out.append(self.buffer)
            self.buffer = b""
        return [part.decode("utf-8", "replace") for part in out]

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()


def claimed_spec(row, card, prompt, budget, session_id=None, message_id=None):
    """Project-independent view of an already authorized legacy claim."""
    chat = row.thread_id is not None
    session_id = session_id or getattr(card, "resume_session", None)
    payload=getattr(card,'project_context',{})
    refs=[{'story_key':k,**{f:a.get(f) for f in ('workspace','branch','head')}}
          for k,a in payload.get('accepted_artifacts',{}).items()]
    refs += [{'story_key':k,**a} for k,a in payload.get('accepted_outputs',{}).items()]
    return dict(schema_version=SCHEMA_VERSION, run_id=str(row.id),
                idempotency_key=row.idempotency_key or run_key(row.id),
                work_key=f"mcd:thread:{row.thread_id}:message:{message_id}" if chat else f"mcd:story:{row.card_id}",
                attempt=getattr(row, "attempt", None) or 1,
                origin={"kind": "chat_turn" if chat else "story",**getattr(card,'project_origin',{})}, prompt=prompt,
                context={"digest": digest(prompt),
                         "memory_refs":[{'id':r['id'],'kind':r['kind'],'sha256':digest(r['text'])}
                                        for r in payload.get('accepted_memory',[])],
                         "artifact_refs":refs},
                model_policy=dict(assigned=dict(agent=row.agent, model=row.model_requested or "",
                                                agent_target=getattr(card, "agent_target", None)),
                                  approved_fallback_routes=[], allow_runtime_fallback=False,
                                  require_model_report=False),
                workspace=dict(path=row.working_dir, mode=card.mode),
                limits=dict(timeout_s=card.timeout_s, idle_timeout_s=getattr(card, "idle_timeout_s", None), kill_grace_s=KILL_GRACE_S),
                budget=dict(billing="subscription" if getattr(card, "subscription_billing", False) else "unknown",
                            max_cost_usd=budget),
                session=dict(mode="resume", session_id=session_id) if session_id else dict(mode="new"),
                output=dict(format="handoff_text"))


SECRET_KEY = re.compile(r"sk-or-[A-Za-z0-9_\-]{12,}")


def scrub(text: str, key: str | None = None) -> str:
    """Remove OpenRouter keys from anything an agent printed before it is stored or shown."""
    if key:
        text = text.replace(key, "[redacted OpenRouter key]")
    return SECRET_KEY.sub("[redacted OpenRouter key]", text)


class LegacyAgentAdapter:
    def __init__(self, spec, sessions, settings, handles):
        self.name = spec.id
        self.spec = spec
        self.sessions = sessions
        self.durable = durable_sessions(sessions)
        self.settings = settings
        self.runs_dir = settings.runs_dir
        self.handles = handles
        self._runs = {}
        self._keys = {}
        self._prepared = {}

    def capabilities(self):
        return dict(schema_version=SCHEMA_VERSION, adapter=self.name,
                    runtime_version=None, pins_model=True,
                    reports_model={"codex": "never", "openclaw": "at_end"}.get(self.name, "at_start"),
                    disables_native_fallback=self.name == "hermes",
                    enforces_mode=self.spec.enforces_mode, structured_output="none",
                    streams_events=self.name != "openclaw", tool_events=False,
                    session="preassigned" if self.spec.preassigned_session else "agent_assigned",
                    suspend_modes=[], reports_cost=self.name == "claude",
                    enforces_budget="runtime" if self.name == "claude" else "none",
                    resource_measurement="not_measured")

    def prepare(self, run_id, argv):
        """Internal bridge: retain the exact argv built at transactional claim time."""
        self._prepared[str(run_id)] = list(argv)

    async def start(self, spec):
        stale_state = None
        try:
            fingerprint = spec_digest(spec)
            rid, key = spec["run_id"], spec["idempotency_key"]
            if not isinstance(rid, str) or rid != str(int(rid)) or not key:
                raise ValueError("Legacy run identity must match its MCD row")
            route = spec["model_policy"]["assigned"]
            if route["agent"] != self.name or spec["schema_version"] != SCHEMA_VERSION:
                raise ValueError("Wrong adapter or schema version")
            if spec["model_policy"].get("allow_runtime_fallback") is not False:
                raise ValueError("Runtime fallback must be disabled")
            prior_run = self._runs.get(rid)
            if prior_run and prior_run["key"] != key:
                task = prior_run.get("task")
                if task is None or not task.done():
                    raise AdapterError("IDEMPOTENCY_CONFLICT", "Run ID already has an active start key")
                stale_state = prior_run
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterError("INVALID_RUN_SPEC", "Malformed legacy run specification") from exc
        # Existing Run row is the durable source of identity. Never create workflow rows here.
        with self.sessions() as db:
            row = db.get(Run, int(rid))
            if row is None or row.agent != self.name or row.stage != "running":
                raise AdapterError("INVALID_RUN_SPEC", "A claimed running row is required")
            if key != (row.idempotency_key or run_key(rid)):
                raise AdapterError("INVALID_RUN_SPEC", "Start key differs from the durable claim")
            if row.working_dir != spec["workspace"]["path"] or (row.model_requested or "") != route["model"]:
                raise AdapterError("INVALID_RUN_SPEC", "Specification differs from the claimed route or workspace")
            started_at = row.started_at
        # A restored/replaced database can reuse a numeric run ID while this API process
        # still holds a completed adapter receipt from the previous database. The current
        # durable Run row has now been validated, so discard only that finished stale receipt.
        # Never release an active receipt or change the same-key replay/interruption semantics.
        if stale_state is not None:
            self._runs.pop(rid, None)
            if self._keys.get(stale_state["key"]) == rid:
                self._keys.pop(stale_state["key"], None)
        if key in self._keys:
            prior = self._runs[self._keys[key]]
            retry = (prior.get("outcome") is not None and prior["outcome"][0] == "interrupted"
                     and spec.get("attempt", 1) > prior["spec"].get("attempt", 1))
            if not retry and prior["digest"] != fingerprint:
                raise AdapterError("IDEMPOTENCY_CONFLICT", "Start key was used for different work")
            if not retry:
                self._prepared.pop(rid, None)
                return dict(run_id=rid, status=prior["status"], replayed=True)
        argv = self._prepared.pop(rid, None)
        if argv is None:
            ctx = SimpleNamespace(mode=spec["workspace"]["mode"],
                                  working_dir=spec["workspace"]["path"],
                                  timeout_s=spec["limits"]["timeout_s"],
                                  agent_target=route.get("agent_target"),
                                  subscription_billing=spec["budget"]["billing"] == "subscription")
            argv = self.spec.build(ctx, spec["prompt"], route["model"],
                                   spec["budget"].get("max_cost_usd") or self.settings.default_budget_usd,
                                   self.spec.binary(self.settings),
                                   session_id=spec["session"].get("session_id"))
        state = dict(key=key, digest=fingerprint, spec=copy.deepcopy(spec),
                     status="running", last_seq=0, changed=asyncio.Event(),
                     context_digest=spec.get("context", {}).get("digest", digest(spec["prompt"])),
                     started_at=started_at, outcome=None)
        event_path = self.runs_dir / f"run-{rid}.adapter.jsonl"
        with os.fdopen(os.open(event_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"):
            pass
        state["event_path"] = event_path
        self._runs[rid] = state
        self._keys[key] = rid
        self.handles.setdefault(int(rid), ProcessHandle())
        self._emit(rid, "status", {"from": "queued", "to": "running"})
        state["task"] = asyncio.create_task(self._drive(rid, argv), name=f"adapter-{self.name}-{rid}")
        return dict(run_id=rid, status="running", replayed=False)

    def _state(self, run_id):
        if run_id not in self._runs:
            raise AdapterError("UNKNOWN_RUN", "Run is not attached to this adapter")
        return self._runs[run_id]

    def _emit(self, rid, kind, data):
        state = self._runs.get(rid)
        if state is None:
            return
        if kind == "log" and len(data["text"]) > 65536:
            data = {**data, "text": data["text"][:65536], "truncated": True}
        seq = state["last_seq"] + 1
        ev = dict(schema_version=SCHEMA_VERSION, run_id=rid, seq=seq,
                  segment=1, ts=int(time.time()), type=kind, data=data)
        with state["event_path"].open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(ev) + "\n")
        state["last_seq"] = seq
        state["changed"].set()

    async def _drive(self, rid, argv, attach=False):
        state = self._state(rid)
        spec = state["spec"]
        state["outcome"] = await self._run_process(int(rid), self.name, argv,
                                                    spec["workspace"]["path"],
                                                    spec["limits"]["timeout_s"],
                                                    attach_started_at=state["started_at"] if attach else None,
                                                    idle_timeout_s=spec["limits"].get("idle_timeout_s"))
        stage, _, _, _, _ = state["outcome"]
        state["status"] = str(LEGACY_STAGE[stage][0])
        state["ended_at"] = int(time.time())
        self._emit(rid, "status", {"from": "running", "to": state["status"]})
        state["spec"]["prompt"] = ""  # keep only its digest once inference is finished

    def legacy_outcome(self, run_id):
        return self._state(run_id)["outcome"]

    async def abort(self, run_id):
        """Keep shutdown semantics: interrupt the task, let MCD recover its row."""
        task = self._state(run_id)["task"]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def wait(self, run_id):
        """Internal compatibility result for the unchanged workflow persistence code."""
        state = self._state(run_id)
        await state["task"]
        return state["outcome"]

    async def events(self, run_id, after_seq=0):
        state = self._state(run_id)
        with state["event_path"].open(encoding="utf-8") as stream:
            while True:
                state["changed"].clear()
                for line in stream:
                    ev = json.loads(line)
                    if ev["seq"] > after_seq:
                        after_seq = ev["seq"]
                        yield ev
                if state["task"].done():
                    await state["task"]
                    return
                # Also wake if execution raises before it can emit a terminal event.
                wake = asyncio.create_task(state["changed"].wait())
                try:
                    await asyncio.wait((wake, state["task"]), return_when=asyncio.FIRST_COMPLETED)
                finally:
                    wake.cancel()
                    await asyncio.gather(wake, return_exceptions=True)

    async def result(self, run_id):
        state = self._state(run_id)
        if state["outcome"] is None:
            raise AdapterError("INVALID_TRANSITION", "Run is still active")
        if "result" not in state:
            stage, exit_code, message, meta, seconds = state["outcome"]
            spec = state["spec"]
            requested = spec["model_policy"]["assigned"]["model"]
            code = LEGACY_STAGE[stage][1]
            if stage == "failed":
                code = ("MODEL_MISMATCH" if message and "different model" in message else
                        "RUNTIME_UNAVAILABLE" if message and message.startswith("could not start") else
                        "AGENT_ERROR")
            if stage == "timeout" and meta.timed_out and message and "provider timed out" in message:
                code = "PROVIDER_TIMEOUT"
            if stage == "failed" and code == "AGENT_ERROR" and message:
                if re.search(r"usage limit|session limit|quota exceeded|quota exhausted|limit reached", message, re.I):
                    code = "PROVIDER_QUOTA_EXHAUSTED"
                elif re.search(r"rate.?limit|too many requests|HTTP.?429", message, re.I):
                    code = "PROVIDER_RATE_LIMITED"
            state["result"] = dict(
                schema_version=SCHEMA_VERSION, run_id=run_id, idempotency_key=state["key"],
                status=state["status"], started_at=state["started_at"], ended_at=state["ended_at"],
                duration_s=seconds, exit_code=exit_code,
                model=dict(requested=requested, reported=meta.model_reported,
                           provider=meta.provider, route=spec["model_policy"]["assigned"],
                           matches_assignment=None if not meta.model_reported or not requested else
                           requested.removeprefix("openrouter/") == meta.model_reported.removeprefix("openrouter/")),
                session=dict(session_id=meta.session_id, resumable=bool(meta.session_id)),
                usage=dict(input_tokens=meta.input_tokens, output_tokens=meta.output_tokens,
                           cached_input_tokens=meta.cached_input_tokens, cache_write_tokens=meta.cache_write_tokens),
                cost=dict(usd=meta.cost_usd, source="reported" if meta.cost_usd is not None else "not_reported",
                          billing=spec["budget"]["billing"]),
                resources=dict(measured_by="not_measured"), artifacts=[], result_text=meta.result_text,
                structured_output=None, error=error(code, "Legacy runtime did not succeed; inspect the run log") if code else None,
                context_digest=state["context_digest"],
                last_seq=state["last_seq"])
        return copy.deepcopy(state["result"])

    async def cancel(self, request):
        rid = request["run_id"]
        state = self._state(rid)
        if state["outcome"] is not None:
            return dict(run_id=rid, status=state["status"], replayed=True)
        replayed = state.get("cancel_requested", False)
        state["cancel_requested"] = True
        handle = self.handles[int(rid)]
        handle.cancel_requested = True
        await self.kill(handle)
        return dict(run_id=rid, status=state["status"], replayed=replayed)

    async def resume(self, decision):
        self._state(decision["run_id"])
        raise AdapterError("INVALID_TRANSITION", "Legacy approvals and new continuation runs belong to MCD")

    async def heartbeat(self, run_id):
        state = self._state(run_id)
        handle = self.handles.get(int(run_id))
        proc = handle.proc if handle else None
        return dict(schema_version=SCHEMA_VERSION, run_id=run_id, status=state["status"],
                    alive=bool(proc and proc.returncode is None), pid=proc.pid if proc else None,
                    last_seq=state["last_seq"], ts=int(time.time()),
                    resources=dict(measured_by="not_measured"))

    def forget(self, run_ids):
        """Drop compatibility receipts when MCD's existing retention removes a row."""
        for run_id in run_ids:
            rid = str(run_id)
            state = self._runs.get(rid)
            if state and state["task"].done():
                self._runs.pop(rid)
                self._keys.pop(state["key"], None)
            self._prepared.pop(rid, None)

    async def recover(self):
        """Reconcile this agent's unfinished board runs after a restart. Never relaunches.

        reattached: the supervisor is alive; follow it to completion.
        finished_while_down: it exited and left an exit record; replay its output now.
        interrupted: no live process and no exit record (already-interrupted rows too).
        Chat turns are left to the dispatcher, which interrupts them.
        """
        with self.sessions() as db:
            rows = list(db.scalars(select(Run).where(Run.agent == self.name,
                                                     Run.stage.in_(("running", "interrupted")))))
            cards = {row.id: db.get(Card, row.card_id) for row in rows if row.card_id is not None}
        recovered = []
        for row in rows:
            rid = str(row.id)
            entry = dict(run_id=rid, idempotency_key=row.idempotency_key or run_key(rid), outcome="interrupted",
                         status="failed", last_seq=0)
            if row.stage == "interrupted":
                recovered.append(entry)
                continue
            if rid in self._runs or row.card_id is None:
                continue  # already followed by this process, or a chat turn
            files = run_files(self.runs_dir, rid)
            marker = str(files.exit)
            pid = row.pid or find_supervisor(marker)
            alive = supervisor_alive(pid, marker)
            finished = read_exit(files.exit) is not None
            if not alive and not finished:
                await asyncio.to_thread(reap_group, pid, row.started_at)
                recovered.append(entry)
                continue
            self.handles[row.id] = ProcessHandle(pid=pid, marker=marker)
            state = self._attach(row, cards[row.id])
            if alive:
                entry.update(outcome="reattached", status="running", last_seq=state["last_seq"])
            else:
                await asyncio.gather(state["task"], return_exceptions=True)
                entry.update(outcome="finished_while_down", status=state["status"], last_seq=state["last_seq"])
            recovered.append(entry)
        return recovered

    def _attach(self, row, card):
        """Rebuild contract state for a run claimed before a restart and follow its files."""
        rid = str(row.id)
        spec = claimed_spec(row, card, "", card.budget_usd if card.budget_usd is not None
                            else self.settings.default_budget_usd)
        checkpoint = json.loads(row.checkpoint or "{}")
        event_path = self.runs_dir / f"run-{rid}.adapter.jsonl"
        with os.fdopen(os.open(event_path, os.O_RDWR | os.O_CREAT, 0o600), "r") as stream:
            last_seq = sum(1 for _ in stream)
        state = dict(key=spec["idempotency_key"], digest=spec_digest(spec), spec=spec, status="running",
                     last_seq=last_seq, changed=asyncio.Event(), event_path=event_path,
                     context_digest=checkpoint.get("context_digest") or digest(""),
                     started_at=row.started_at, outcome=None)
        self._runs[rid] = state
        self._keys[state["key"]] = rid
        state["task"] = asyncio.create_task(self._drive(rid, None, attach=True),
                                            name=f"adapter-{self.name}-{rid}-reattached")
        return state

    def _record_spawn(self, run_id: int, pid: int) -> None:
        with self.durable.begin() as db:
            row = db.get(Run, run_id)
            if row is not None and row.stage == "running":
                row.pid = pid
                row.checkpoint = json.dumps({**json.loads(row.checkpoint or "{}"), "phase": "spawned"})

    @staticmethod
    def env() -> dict[str, str]:
        # No MAC_CONTROL_*/RCD_* settings: operator credentials and paths never reach an agent.
        # Run-specific RCD_RUN_ID and RCD_IDEMPOTENCY_KEY are added after this.
        env = runner_env()
        env["PATH"] = ":".join((*EXTRA_PATH, env.get("PATH", "/usr/bin:/bin")))
        env.setdefault("HOME", str(Path.home()))
        return env

    async def _run_process(self, run_id: int, agent: str, argv: list[str] | None, cwd: str,
                           timeout_s: int, attach_started_at: int | None = None,
                           idle_timeout_s: int | None = None
                           ) -> tuple[str, int | None, str | None, Any, float]:
        """Spawn one supervised agent process (or reattach to one), follow its output files
        into the run log, and classify the result.

        Shared by board cards and chat turns. Returns (stage, exit_code, error, meta, seconds).
        A reattached run replays its output from the start, so the parser sees every line;
        its time limit still counts from the original start.
        """
        spec = self.spec
        parser = spec.parser()
        handle = self.handles[run_id]
        files = run_files(self.runs_dir, run_id)
        log_path = self.runs_dir / f"run-{run_id}.log"
        raw_path = self.runs_dir / f"run-{run_id}.raw.log"
        attach = attach_started_at is not None
        started = time.monotonic()
        wall_started = attach_started_at if attach else time.time()
        deadline = started + timeout_s - (time.time() - wall_started)
        last_activity = started
        stage, exit_code, error = "failed", None, None
        quota_reported = False
        mode = "w" if attach else "a"  # a reattached run rebuilds its readable logs
        supplied_key: str | None = None  # the saved OpenRouter key this run was given, if any: scrubbed from everything it prints

        with open(log_path, mode, encoding="utf-8") as log, open(raw_path, mode, encoding="utf-8") as raw:
            def write(text: str) -> None:
                text = scrub(text, supplied_key)
                stamp = time.strftime("%H:%M:%S")
                for part in (text.splitlines() or [""]):
                    log.write(f"{stamp}  {part}\n")
                log.flush()
                self._emit(str(run_id), "log", {"text": text, "stream": "stdout"})

            def feed(line: str, is_stderr: bool) -> None:
                nonlocal quota_reported
                line = scrub(line.rstrip("\n"), supplied_key)
                raw.write(("! " if is_stderr else "") + line + "\n")
                if is_stderr:
                    parser.feed_stderr(line)
                    quota_reported |= bool(re.search(r"usage limit|session limit|rate.?limit|quota exceeded|quota exhausted|too many requests|limit reached|HTTP.?429",line,re.I))
                    if line.strip():
                        write(f"! {line}")
                else:
                    for out in parser.feed(line):
                        write(out)

            tails = ((_Tail(files.stdout), False), (_Tail(files.stderr), True))

            def drain(final: bool = False) -> bool:
                moved = False
                for tail, is_stderr in tails:
                    for line in tail.lines(final):
                        moved = True
                        feed(line, is_stderr)
                return moved

            proc = None
            if attach:
                write("MCD restarted and reattached to this run; its output so far is replayed below.")
            else:
                try:
                    if agent == 'hermes':
                        from hermes_runtime import command
                        argv = command(argv, getattr(self.settings, "agent_tools_path", None))
                    for path in vars(files).values():
                        path.unlink(missing_ok=True)
                    env = self.env()
                    env.update(self.spec.env)   # for example Grok's telemetry and trace upload switches, always off
                    with self.sessions() as db:
                        row = db.get(Run, run_id)
                        env["RCD_IDEMPOTENCY_KEY"] = row.idempotency_key or run_key(run_id)
                        if agent in SAVED_KEY_AGENTS:
                            supplied_key = saved_openrouter_key(db, self.settings)
                    if supplied_key:
                        # The only operator credential an agent ever receives, and only after the operator opted in.
                        env["OPENROUTER_API_KEY"] = supplied_key
                        write("The saved OpenRouter key was supplied to this run (its value is never logged).")
                    env["RCD_RUN_ID"] = str(run_id)
                    with open(files.stdout, "ab") as out, open(files.stderr, "ab") as err:
                        proc = await asyncio.create_subprocess_exec(
                            sys.executable, "-I", str(SUPERVISOR), str(files.exit), "--", *argv,
                            cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
                            stdout=out, stderr=err, start_new_session=True,
                        )
                except (FileNotFoundError, PermissionError) as exc:
                    error = f"could not start {spec.name}: {exc}"
                    write(f"error: {error}")
                    return stage, exit_code, error, parser.meta, time.monotonic() - started
                handle.proc, handle.pid, handle.marker = proc, proc.pid, str(files.exit)
                await asyncio.to_thread(self._record_spawn, run_id, proc.pid)

            waiter = asyncio.ensure_future(proc.wait()) if proc is not None else None
            status, outcome = None, "exit"
            try:
                while True:
                    moved = drain()
                    if moved:
                        last_activity = time.monotonic()
                    status = read_exit(files.exit)
                    if status is not None:
                        break
                    alive = not waiter.done() if waiter else supervisor_alive(handle.pid, handle.marker)
                    if not alive:
                        status = read_exit(files.exit)  # it may have written just before exiting
                        outcome = "exit" if status is not None else "lost"
                        break
                    if time.monotonic() >= deadline:
                        await self.kill(handle)
                        status, outcome = read_exit(files.exit), "timeout"
                        break
                    if idle_timeout_s and time.monotonic() - last_activity >= idle_timeout_s:
                        await self.kill(handle)
                        status, outcome = read_exit(files.exit), "idle_timeout"
                        break
                    if not moved:
                        await asyncio.sleep(POLL_S)
                drain(final=True)
            except asyncio.CancelledError:
                await self.kill(handle)
                raise
            finally:
                for tail, _ in tails:
                    tail.close()
                if waiter is not None and not waiter.done():
                    waiter.cancel()

            if outcome == "lost" and handle.pid:
                await asyncio.to_thread(reap_group, handle.pid, wall_started)
            exit_code = status.get("returncode") if status else None
            if status and "spawn_error" in status:
                error = f"could not start {spec.name}: {status['spawn_error']}"
                write(f"error: {error}")
            elif outcome in {"timeout", "idle_timeout"}:
                limit = idle_timeout_s if outcome == "idle_timeout" else timeout_s
                kind = "idle" if outcome == "idle_timeout" else "wall-clock"
                stage, error = "timeout", f"MCD stopped the run after its {limit} s {kind} time limit. Review any partial work before retrying."
                write(f"error: {error}")
            else:
                for out in parser.finish():
                    write(out)
                with self.sessions() as db:
                    requested = db.get(Run, run_id).model_requested
                if agent in {'hermes','openclaw'} and requested and parser.meta.model_reported and requested.removeprefix('openrouter/') != parser.meta.model_reported.removeprefix('openrouter/'):
                    parser.meta.error = 'Agent reported a different model than the MCD assignment. Review this run; no automatic reassignment was authorized.'
                    parser.meta.timed_out = False
                if handle.cancel_requested:
                    stage, error = "cancelled", "cancelled by operator"
                elif outcome == "lost" or exit_code == -signal.SIGKILL:
                    # Not MCD's doing (cancel and timeout are handled above): an interruption.
                    stage, error = "interrupted", LOST_ERROR
                    write(f"error: {error}")
                elif exit_code == 0 and parser.meta.error is None:
                    stage = "succeeded"
                else:
                    stage = "timeout" if parser.meta.timed_out else "failed"
                    error = parser.meta.error or f"exit code {exit_code}"
                    if quota_reported: error += " (CLI reported a quota or rate limit)"

        return stage, exit_code, error, parser.meta, time.monotonic() - started

    @staticmethod
    async def kill(handle: ProcessHandle) -> None:
        """SIGTERM the run's process group, then SIGKILL after KILL_GRACE_S."""
        proc = handle.proc
        if proc is None:
            if supervisor_alive(handle.pid, handle.marker):
                await LegacyAgentAdapter._kill_detached(handle.pid, handle.marker)
            return
        if proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE_S)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()

    @staticmethod
    async def _kill_detached(pid: int, marker: str) -> None:
        """Same policy for a supervisor adopted after a restart (not this process's child)."""
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            deadline = time.monotonic() + KILL_GRACE_S
            while time.monotonic() < deadline:
                if not supervisor_alive(pid, marker):
                    return
                await asyncio.sleep(0.1)
