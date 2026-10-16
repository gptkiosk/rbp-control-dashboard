"""Queue worker that runs agent cards.

- At most `max_concurrent_runs` runs at a time; queued cards run in board order.
- A card runs only from the "queued" column, and only if it needs no approval or has been
  approved (checked here as well as in the API).
- Each run is its own process group (start_new_session) with stdin closed (Codex otherwise
  waits on stdin). Timeout and cancel signal the whole group: SIGTERM, then SIGKILL after 5 s.
- Output lines can be large (Claude stream-json carries tool results), so the reader limit is 16 MB.
- Durable runs. Each claim records an execution idempotency key on the card and its Run.
  Attempts of one execution share the key; the database allows at most one running and one
  successful attempt per key. Agents run under a detached supervisor (legacy_adapters), so
  they survive an API crash. On startup, each run still marked running is reconciled: it is
  reattached if its process is alive, its result is recorded if it finished while the API was
  down, and otherwise it is marked "interrupted" and its card requeued with the same key (at
  most MAX_INTERRUPTIONS times, then Failed). Graceful shutdown kills and requeues the same way.
  Claims, finishes and requeues commit with synchronous=FULL (db.durable_sessions).
- Cancellation is durable. The request is committed to the run's checkpoint before any signal.
  Recovery reads it: a surviving runner is stopped, and the run is recorded as cancelled, never
  interrupted or requeued. A result that arrives after the request is recorded as cancelled too.
  Partial output is quarantined: kept for review, never published or deleted.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import secrets
import uuid
import time
from types import SimpleNamespace
from pathlib import Path
from typing import Any

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.orm import aliased
from sqlalchemy.orm import sessionmaker

from agents import REGISTRY, AgentSpec, RunMeta, redact
import agent_git
from adapter_contract import AgentAdapter, AdapterError, ERRORS, SCHEMA_VERSION, digest
from db import durable_sessions
from legacy_adapters import (EXTRA_PATH, KILL_GRACE_S, LINE_LIMIT, LegacyAgentAdapter,
                             ProcessHandle, claimed_spec, find_supervisor, run_files)
import projects
from idempotency import refuse_timeout_retry
import approval
import provider_limits
from dispatch_gate import (DispatchDenied, admit as admit_dispatch, resolve_free_alias,
                           snapshot as dispatch_snapshot, reviewed_route_class as _reviewed_route_class)
import pi_routing
from usage import put_provider_receipt
from models import Card, CardDependency, ChatMessage, ChatThread, Project, ProviderReceipt, Run, RunEvent

logger = logging.getLogger("mac_control.dispatcher")

MAX_CHAT_TURNS = 2  # chat turns run beside board cards so a long card never blocks a conversation
CHAT_TIMEOUT_S = 900
MAX_INTERRUPTIONS = 3  # interrupted attempts of one execution before its card is failed
RESTART_NOTE = "service restarted; the run's process was no longer running"
DUPLICATE_ERROR = ("Another attempt of this execution already completed; this result was not "
                   "recorded as a second completion.")
CANCEL_ERROR = "cancelled by operator"
LATE_CANCEL_ERROR = ("cancelled by operator; the runner returned a result after the cancel was "
                     "recorded, so it was quarantined rather than accepted")


def execution_key(card_id: int) -> str:
    return f"rcd:exec:{card_id}:{uuid.uuid4().hex}"


_Handle = ProcessHandle



def _now() -> int:
    return int(time.time())


def remove_run_logs(log_paths) -> None:
    """Delete a run's readable and raw logs. Used wherever runs are deleted by cascade."""
    for log_path in log_paths:
        if not log_path:
            continue
        base = Path(log_path)
        for suffix in (".log", ".raw.log", ".adapter.jsonl", ".stdout", ".stderr", ".exit", ".exit.tmp"):
            base.with_suffix(suffix).unlink(missing_ok=True)


class Dispatcher:
    def __init__(self, sessions: sessionmaker, settings, registry: dict[str, AgentSpec] | None = None,
                 poll_s: float = 2.0, adapters: dict[str, AgentAdapter] | None = None,
                 pi_scope_caps: dict[tuple[int, int], pi_routing.ScopeCaps] | None = None) -> None:
        self.sessions = sessions
        self.durable = durable_sessions(sessions)
        self.settings = settings
        self.registry = registry if registry is not None else REGISTRY
        self.poll_s = poll_s
        self.runs_dir: Path = settings.runs_dir
        self.runs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._handles: dict[int, _Handle] = {}
        self.adapters = {name: LegacyAgentAdapter(spec, sessions, settings, self._handles)
                         for name, spec in self.registry.items()}
        if adapters is not None:
            self.adapters.update(adapters)
        self.pi_scope_caps = dict(pi_scope_caps or {})
        self._tasks: dict[int, asyncio.Task] = {}
        # Recorded before adapter startup too: a UI cancel can race a just-claimed run.
        self._cancel_requested: set[int] = set()
        self._chat_tasks: dict[int, asyncio.Task] = {}
        self._chat_slots = asyncio.Semaphore(MAX_CHAT_TURNS)
        self._loop_task: asyncio.Task | None = None
        self._last_prune = 0.0
        self._adapters_recovered = False
        # Turns a previous process left running are older than this one; a message sent while the first
        # recovery is still pending belongs to this process and must not be failed by it.
        self._boot_at = _now()
        self._recovery_outcomes: dict[tuple[str, str], dict] = {}
        self._adapter_recovery_lock = asyncio.Lock()
        self._decision_lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        # The first tick reconciles runs left running by a previous process (_recover_adapters).
        self._loop_task = asyncio.create_task(self._loop(), name="dispatcher")

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        for handle in list(self._handles.values()):
            await self._kill(handle)
        tasks = [*self._tasks.values(), *self._chat_tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._adapters_recovered:
            self.recover("service stopped while the run was in progress")

    def recover(self, note: str) -> int:
        """Interrupt every run left in 'running' (processes already stopped) and requeue
        its card with the same idempotency key. Chat turns fail, as before."""
        now = _now()
        with self.durable.begin() as s:
            stuck = s.execute(select(Run).where(Run.stage == "running")).scalars().all()
            for run in stuck:
                self._interrupt(s, run, note, now)
            self._fail_chat_turns(s, note, now)
            return len(stuck)

    @staticmethod
    def _fail_chat_turns(s, note: str, now: int, before: int | None = None) -> None:
        query = select(ChatMessage).where(ChatMessage.status == "running")
        if before is not None:
            query = query.where(ChatMessage.created_at < before)
        for msg in s.execute(query).scalars():
            msg.status = "failed"
            s.add(ChatMessage(thread_id=msg.thread_id, role="assistant", status="failed",
                              text=f"(turn interrupted: {note})", created_at=now))

    def _interrupt(self, s, run: Run, note: str, now: int, requeue: bool = True) -> None:
        if json.loads(run.checkpoint or "{}").get("cancel_requested"):
            self._record_cancelled(s, run, note, now)
            return
        run.stage = "interrupted"
        run.ended_at = now
        run.duration_s = float(now - run.started_at)
        run.error = note
        run.checkpoint = json.dumps({**json.loads(run.checkpoint or "{}"), "phase": "interrupted"})
        s.add(RunEvent(run_id=run.id, ts=now, kind="stage", text=f"interrupted: {note}"))
        self._requeue_or_fail(s, run, now, requeue)

    def _record_cancelled(self, s, run: Run, note: str, now: int) -> None:
        """End a run the operator cancelled before its process was seen to stop. Never requeued."""
        run.stage, run.ended_at = "cancelled", now
        run.duration_s = float(now - run.started_at)
        run.error = f"{CANCEL_ERROR}; {note}"
        run.checkpoint = json.dumps({**json.loads(run.checkpoint or "{}"), "phase": "cancelled"})
        s.add(RunEvent(run_id=run.id, ts=now, kind="stage", text=f"cancelled: {note}"))
        self._quarantine(s, run, "cancelled", run.error, now)
        card = s.get(Card, run.card_id) if run.card_id is not None else None
        if card is not None and card.column == "running":
            card.column, card.retry_after, card.idempotency_key, card.updated_at = "failed", None, None, now
            projects.on_finish(s, card, run, "cancelled")

    def _requeue_or_fail(self, s, run: Run, now: int, requeue: bool = True) -> None:
        """Requeue an interrupted run's card with the same idempotency key, within bounds."""
        card = s.get(Card, run.card_id) if run.card_id is not None else None
        if card is None or card.column != "running":
            return
        s.flush()
        interruptions = s.scalar(select(func.count()).select_from(Run).where(
            Run.idempotency_key == run.idempotency_key, Run.stage == "interrupted")) if run.idempotency_key else 0
        link = projects.binding(s, card.id)
        project = s.get(Project, link.project_id) if link and link.role == "story" else None
        card.updated_at = now
        if requeue and projects.card_model_locked(s, card):
            requeue = False
            s.add(RunEvent(run_id=run.id, ts=now, kind="note", text="not requeued: project model lock requires explicit retry"))
        cp = json.loads(run.checkpoint or "{}")
        if requeue and (cp.get("decisions") or cp.get("pending_decision")):
            # A fresh attempt would repeat work the human decision already covered, or run
            # again after a rejection. The decision stays on the run; the operator reviews.
            requeue = False
            s.add(RunEvent(run_id=run.id, ts=now, kind="note",
                           text="not requeued: a human decision was recorded on this run; review before retrying"))
        if requeue and run.idempotency_key and interruptions < MAX_INTERRUPTIONS:
            card.column, card.idempotency_key = "queued", run.idempotency_key
            s.add(RunEvent(run_id=run.id, ts=now, kind="note",
                           text=f"requeued as attempt {run.attempt + 1} of the same execution"))
            if project:
                projects.requeue_output(s, card, run)
                projects.memory(s, project, "checkpoint",
                    f"Run #{run.id} of story #{card.id} was interrupted ({run.error}). MCD requeued the "
                    f"same execution (attempt {run.attempt + 1}, same idempotency key and route). Partial "
                    "work is unverified. Read the current workspace diff and prior run evidence before "
                    "continuing the SAME story; do not redo completed work.", "mcd", card.id, run.id)
            return
        card.column, card.idempotency_key = "failed", None
        if project:
            reason = (f"interrupted {interruptions} times" if requeue and run.idempotency_key
                      else "not safe to requeue automatically")
            projects.memory(s, project, "incident",
                f"interrupted: story #{card.id} stopped ({reason}); explicit retry required.",
                "mcd", card.id, run.id)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
                if time.time() - self._last_prune > 3600:
                    self._last_prune = time.time()
                    await asyncio.to_thread(self.prune, _now())
            except Exception:
                logger.exception("dispatcher tick failed")
            await asyncio.sleep(self.poll_s)

    # ------------------------------------------------------------------ queue

    def _claim(self, limit: int) -> list[tuple[dict[str, Any], int]]:
        """Move up to `limit` runnable queued cards to running and create their Run rows."""
        claimed: list[tuple[dict[str, Any], int]] = []
        now = _now()
        blocker = aliased(Card)
        unfinished_dependency = exists().where(and_(
            CardDependency.card_id == Card.id,
            CardDependency.depends_on_id == blocker.id,
            blocker.column != "done",
        ))
        with self.durable.begin() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            projects.advance(s, self.settings)
            active_runs = [r for r in s.scalars(select(Run).where(
                Run.stage.in_(("running", "awaiting_approval"))))
                if r.stage == "running" or json.loads(r.checkpoint or "{}").get("human_approval")]
            cards = s.execute(
                select(Card)
                .where(Card.column == "queued")
                .where(or_(Card.retry_after.is_(None), Card.retry_after <= now))
                .where(Card.assignee_type == "agent")
                .where(~unfinished_dependency)
                .where(or_(Card.needs_approval.is_(False), Card.approved_at.is_not(None)))
                .order_by(Card.position, Card.id)
            ).scalars().all()
            for card in cards:
                if len(claimed) >= limit: break
                if refuse_timeout_retry(s, card, now):
                    continue
                link = projects.binding(s, card.id)
                # Second line of defence for standalone cards: only an unused, unexpired grant
                # for this exact route pin (or the same execution's requeue) may start a run.
                problem = (approval.grant_problem(card, now, card.idempotency_key)
                           if card.needs_approval and not link else None)
                if problem:
                    approval.revoke(card, now, problem)
                    continue
                if any((link or (r.card_id and projects.binding(s, r.card_id)) or r.stage == "awaiting_approval") and projects.overlap(card.working_dir, r.working_dir) for r in active_runs):
                    continue
                # A named OpenClaw target has its own configured gateway workspace.
                # Keep its project conversations distinct and serialize work on that target.
                if card.agent=='openclaw' and any(r.agent=='openclaw' and
                    (link or (r.card_id and projects.binding(s,r.card_id))) and
                    ((s.get(Card,r.card_id) if r.card_id else s.get(ChatThread,r.thread_id)).agent_target or 'mm-main')==(card.agent_target or 'mm-main') for r in active_runs): continue
                prompt = projects.claim_context(s, card)
                if prompt is None: continue
                # While a subscription limit lasts and the operator chose to reroute, a story that
                # has not started goes straight to an approved alternate route of the same grade.
                rerouted_from = None
                if link and link.role == 'story' and card.agent in provider_limits.PROVIDERS and not getattr(card, 'output_only', False) and not projects.card_model_locked(s, card):
                    limit_row = provider_limits.rerouting_row(s, card.agent, now)
                    if limit_row:
                        alt = provider_limits.alternate(projects.approved_story_routes(projects.get(s, link.project_id), link),
                                                        card.agent, card.model, provider_limits.limited_providers(s, now))
                        if alt:
                            rerouted_from = {'agent': card.agent, 'model': card.model, 'limit_id': limit_row.id}
                            card.agent, card.model, card.agent_target = alt['agent'], alt['model'] or None, None
                            limit_row.rerouted += 1
                spec = self.registry.get(card.agent)
                if spec is None:
                    card.column, card.updated_at = "failed", now
                    continue
                pi_runtime = getattr(self.adapters.get(card.agent), "name", None) in {"picoclaw", "zeroclaw"}
                model_requested = (card.model or "") if pi_runtime else (card.model or spec.default_model())
                resolved = resolve_free_alias(s, self.settings, card.agent, card.agent_target, model_requested)
                if resolved != model_requested:   # a task saved with the generic free default before it was resolved: run it on the agent's own free model
                    card.model = model_requested = resolved
                # Branch-scoped git access is an operator grant per approved project, never plan output.
                grant = agent_git.grant_for(self.settings, link.project_id, card) if link and link.role == 'story' else None
                card.agent_git_grant = grant
                if grant:
                    prompt = agent_git.apply_context(prompt, grant, card.id, card.agent, model_requested)
                card.subscription_billing=_reviewed_route_class(s, self.settings, card, model_requested) == "subscription"
                args=(card,prompt,model_requested,card.budget_usd if card.budget_usd is not None else self.settings.default_budget_usd,spec.binary(self.settings))
                resume=getattr(card,'resume_session',None)
                argv=spec.build(*args, session_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'mcd:story:{card.id}'))) if link and spec.preassigned_session else spec.build(*args,session_id=resume) if resume else spec.build(*args)
                # An interruption requeue keeps the card's key; any other claim starts a new execution.
                card.idempotency_key = card.idempotency_key or execution_key(card.id)
                prior = s.scalars(select(Run).where(Run.idempotency_key == card.idempotency_key)
                                  .order_by(Run.id)).all()
                run = Run(
                    card_id=card.id, agent=card.agent, model_requested=model_requested,
                    stage="running", started_at=now, working_dir=card.working_dir,
                    command=json.dumps(redact(argv, prompt)), log_path="",
                    idempotency_key=card.idempotency_key, attempt=len(prior) + 1,
                    requeued_from=prior[-1].id if prior else None,
                    checkpoint=json.dumps({"phase": "claimed", "context_digest": digest(prompt), "dispatch_policy": dispatch_snapshot(card, args[3], _reviewed_route_class(s, self.settings, card, model_requested)),
                                           **({"agent_git": [{"dir": c.dir, "repo": c.repo, "branch": c.branch} for c in grant.clones]} if grant else {}),
                                           **({"rerouted_from": rerouted_from} if rerouted_from else {}),
                                           "context_bytes": len(prompt.encode())}),
                )
                s.add(run)
                s.flush()
                projects.bind_output_run(s,card,run.id)
                active_runs.append(run)
                if link and link.role == "story":
                    projects.memory(s, projects.get(s, link.project_id), "context", prompt, "mcd", card.id, run.id)
                run.log_path = str(self.runs_dir / f"run-{run.id}.log")
                s.add(RunEvent(run_id=run.id, ts=now, kind="stage", text="running"))
                if card.needs_approval and not link:
                    s.add(RunEvent(run_id=run.id, ts=now, kind="note",
                                   text=approval.consume(card, run.id, now, card.idempotency_key)))
                card.column, card.updated_at = "running", now
                adapter_spec=claimed_spec(run, card, prompt,
                    card.budget_usd if card.budget_usd is not None else self.settings.default_budget_usd)
                if link and link.role=='story':
                    run.checkpoint=json.dumps({**json.loads(run.checkpoint),
                        'project_origin':adapter_spec['origin'],'project_context':adapter_spec['context']})
                claimed.append(({"id": card.id, "agent": card.agent, "working_dir": card.working_dir,
                                 "timeout_s": card.timeout_s, "argv": argv,
                                 "adapter_spec": adapter_spec}, run.id))
        return claimed

    async def _recover_adapters(self) -> None:
        """Once per process, before any claim: reconcile runs a previous process left running."""
        async with self._adapter_recovery_lock:
            if self._adapters_recovered:
                return
            # Some adapters attach as a side effect. Keep their successful outcomes
            # if a later adapter fails, so the next tick cannot orphan that attachment.
            recovered = self._recovery_outcomes
            for agent, adapter in self.adapters.items():
                try:
                    items = await adapter.recover()
                except Exception:
                    logger.exception("adapter %s recovery failed", getattr(adapter, "name", "?"))
                    # Unknown liveness is not evidence of death. Leave rows untouched and
                    # retry recovery next tick; claiming now could launch duplicate work.
                    raise
                for item in items:
                    recovered[(agent, str(item["run_id"]))] = item
            # Chat turns are not reattached; stop any surviving process before failing them.
            for run_id, pid in await asyncio.to_thread(self._running_chat_runs):
                marker = str(run_files(self.runs_dir, run_id).exit)
                await LegacyAgentAdapter.kill(ProcessHandle(pid=pid or find_supervisor(marker), marker=marker))
            for run_id, card_id, agent in await asyncio.to_thread(self._settle, recovered):
                self._follow(run_id, card_id, agent)
                if run_id in self._cancel_requested:
                    # Cancelled before the restart: stop the reattached runner now.
                    try:
                        await self._signal_cancel(run_id, agent)
                    except Exception:
                        # _finish still records the run as cancelled whenever it ends.
                        logger.exception("could not stop cancelled run %s after restart", run_id)
            self._adapters_recovered = True
            self._recovery_outcomes = {}

    def _running_chat_runs(self) -> list[tuple[int, int | None]]:
        with self.sessions() as s:
            return [(r.id, r.pid) for r in s.scalars(select(Run).where(
                Run.stage == "running", Run.thread_id.is_not(None)))]

    def _settle(self, recovered: dict[tuple[str, str], dict]) -> list[tuple[int, int, str]]:
        """Decide each orphaned run from its adapter's recovery outcome. Returns runs to follow."""
        now = _now()
        follow = []
        with self.durable.begin() as s:
            for run in s.scalars(select(Run).where(Run.stage == "running")).all():
                if run.id in self._tasks:
                    continue
                outcome = recovered.get((run.agent, str(run.id)), {}).get("outcome")
                if run.card_id is not None and outcome in {"reattached", "finished_while_down", "awaiting_approval"}:
                    follow.append((run.id, run.card_id, run.agent))
                    if json.loads(run.checkpoint or "{}").get("cancel_requested"):
                        self._cancel_requested.add(run.id)
                    s.add(RunEvent(run_id=run.id, ts=now, kind="note",
                                   text="service restarted; " + ("reattached to the running process" if outcome == "reattached"
                                                                 else "the process finished while the service was down")))
                elif outcome == "finished_while_down":
                    # The runtime finished, but its result is not recoverable here. Rerunning could
                    # duplicate billed work, so the operator decides.
                    self._interrupt(s, run, "service restarted; the runtime finished while the service was down "
                                    "but its result could not be recovered. Inspect the adapter state before retrying.",
                                    now, requeue=False)
                else:
                    self._interrupt(s, run, RESTART_NOTE, now)
            self._fail_chat_turns(s, RESTART_NOTE, now, before=self._boot_at)
        return follow

    def _follow(self, run_id: int, card_id: int, agent: str) -> None:
        self._handles.setdefault(run_id, _Handle())
        card = {"id": card_id, "agent": agent, "working_dir": None, "timeout_s": None,
                "argv": None, "adapter_spec": None, "attach": True}
        task = asyncio.create_task(self._execute(card, run_id), name=f"run-{run_id}-reattached")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t, rid=run_id: self._forget(rid))

    async def tick(self) -> int:
        await self._recover_adapters()
        await self._resume_pending_decisions()
        free = self.settings.max_concurrent_runs - len(self._tasks)
        if free <= 0:
            return 0
        claimed = await asyncio.to_thread(self._claim, free)
        for card, run_id in claimed:
            self._handles[run_id] = _Handle()
            task = asyncio.create_task(self._execute(card, run_id), name=f"run-{run_id}")
            self._tasks[run_id] = task
            task.add_done_callback(lambda _t, rid=run_id: self._forget(rid))
        return len(claimed)

    def _forget(self, run_id: int) -> None:
        self._tasks.pop(run_id, None)
        self._handles.pop(run_id, None)
        self._cancel_requested.discard(run_id)

    # ------------------------------------------------------------------ execution

    @staticmethod
    def _env(agent: str | None = None) -> dict[str, str]:
        env = LegacyAgentAdapter.env()
        spec = REGISTRY.get(agent) if agent else None
        if spec is not None:
            env.update(spec.env)   # for example Grok's telemetry and trace upload switches, always off
        return env

    def _dispatch_admission(self, run_id, argv):
        with self.sessions.begin() as db:
            row = db.get(Run, run_id)
            if row is None:
                raise DispatchDenied("PRICE_UNKNOWN: run missing")
            try:
                source = db.get(Card, row.card_id) if row.card_id else db.get(ChatThread, row.thread_id)
                current_class = _reviewed_route_class(db, self.settings, source, row.model_requested) if source else None
                evidence = admit_dispatch(self.settings, row, argv, default_free_only=True, current_price_class=current_class)
            except DispatchDenied as exc:
                db.add(RunEvent(run_id=run_id, ts=_now(), kind="note", text=f"dispatch denied: {exc}"))
                problem = str(exc)
            else:
                db.add(RunEvent(run_id=run_id, ts=_now(), kind="note",
                                text="dispatch admitted: " + json.dumps(evidence, sort_keys=True)))
                problem = None
        if problem:
            raise DispatchDenied(problem)

    async def _run_process(self, run_id: int, agent: str, argv: list[str], cwd: str,
                           timeout_s: int, spec=None, attach: bool = False):
        """Start (or, with attach, only follow an already recovered) run through its adapter."""
        adapter = self.adapters[agent]
        # A reattached run is followed to its end even when cancelled, so its process is stopped.
        if not attach and run_id in self._cancel_requested:
            return ("cancelled", None, "cancelled by operator before runtime startup", RunMeta(), 0.0)
        if spec is None and not attach:
            with self.sessions() as db:
                row = db.get(Run, run_id)
                card = db.get(Card, row.card_id) if row.card_id else db.get(ChatThread, row.thread_id)
                spec = claimed_spec(row, card, json.dumps(argv), self.settings.default_budget_usd)
        if isinstance(adapter, LegacyAgentAdapter) and not attach:
            # Preserve the exact command built inside the claim transaction.
            adapter.prepare(run_id, argv)
        try:
            if not attach and adapter.name in {"picoclaw", "zeroclaw"}:
                with self.sessions() as db:
                    row = db.get(Run, run_id)
                    card = db.get(Card, row.card_id) if row.card_id else None
                    link = projects.binding(db, card.id) if card else None
                    caps = self.pi_scope_caps.get((link.project_id, link.revision)) if link else None
                    if caps is None:
                        raise AdapterError("BUDGET_EXCEEDED", "Approved scope caps are not bound to this project revision")
                    project = projects.get(db, link.project_id)
                    routes = projects.approved_story_routes(project, link)
                    # Count actual recorded spend across all attempts, including failed runs.
                    from models import ProjectTask
                    ids = select(ProjectTask.card_id).where(ProjectTask.project_id == link.project_id)
                    prior = [r for r in db.scalars(select(Run).where(Run.card_id.in_(ids), Run.id != run_id))
                             if getattr(self.adapters.get(r.agent), "name", None) in {"picoclaw", "zeroclaw"}
                             or r.provider == "openrouter"]
                    if any(r.cost_usd is None and r.stage != "running" for r in prior):
                        raise AdapterError("BUDGET_EXCEEDED", "Prior project usage is unreconciled")
                    pi_routing.admit(spec, caps, routes, project_spend=sum(r.cost_usd or 0 for r in prior),
                                     roots=self.settings.workdir_roots, approved=card.approved_at is not None,
                                     approval_prompt=card.body)
                    capabilities = adapter.capabilities()
                    if capabilities.get("enforces_budget") not in {"adapter", "runtime"}:
                        raise AdapterError("BUDGET_EXCEEDED", "Pi runtime lacks a provider budget boundary")
            if not attach:
                # A cancel can arrive after the first race check but before adapter.start().
                # Do not launch a process after the operator has revoked the run.
                if run_id in self._cancel_requested:
                    return ("cancelled", None, "cancelled by operator before runtime startup", RunMeta(), 0.0)
                await asyncio.to_thread(self._dispatch_admission, run_id, argv)
                started = await adapter.start(spec)
                if str(started.get("run_id")) != str(run_id):
                    raise AdapterError("IDEMPOTENCY_CONFLICT", "Adapter replay belongs to a prior attempt; no new execution was launched")
            async for event in adapter.events(str(run_id)):
                if not isinstance(adapter, LegacyAgentAdapter):
                    await asyncio.to_thread(self._adapter_event, run_id, agent, event)
            result = await adapter.result(str(run_id))
            with self.sessions() as db:
                row = db.get(Run, run_id)
                decisions = json.loads(row.checkpoint or "{}").get("decisions", {}) if row else {}
                if any(d["verdict"] == "reject" for d in decisions.values()):
                    if result["status"] != "cancelled":
                        raise AdapterError("RESULT_INVALID", "A rejected human decision cannot complete successfully")
            if result["status"] == "awaiting_approval":
                try:
                    approval.checkpoint_request(result.get("approval", {}), adapter.capabilities(),
                                                await adapter.heartbeat(str(run_id)))
                except AdapterError:
                    # A live approval holds RAM and cannot survive restart. Do not silently
                    # accept it as a durable gate or leave its runtime running unattended.
                    await adapter.cancel(dict(schema_version=SCHEMA_VERSION, run_id=str(run_id),
                                              request_id=f"unsupported-approval:{run_id}", reason="operator", actor="mcd"))
                    raise
        except DispatchDenied as exc:
            return ("failed", None, str(exc), RunMeta(), 0.0)
        except AdapterError as exc:
            code = exc.code
            await asyncio.to_thread(self._adapter_event, run_id, agent,
                                    dict(type="error", data=dict(code=code, message=str(exc))))
            return ("failed", None, f"{code}: {exc}", RunMeta(), 0.0)
        except asyncio.CancelledError:
            if isinstance(adapter, LegacyAgentAdapter):
                await adapter.abort(str(run_id))
            else:
                await adapter.cancel(dict(schema_version=SCHEMA_VERSION, run_id=str(run_id),
                                          request_id=f"shutdown:{run_id}", reason="shutdown", actor="mcd"))
            raise
        if isinstance(adapter, LegacyAgentAdapter):
            return adapter.legacy_outcome(str(run_id))
        # Pi runtimes supply contract messages beside the CLI adapters.
        # Persist only the same fields the API already exposes.
        meta = RunMeta(model_reported=result["model"]["reported"],
                       provider=result["model"]["provider"],
                       session_id=result.get("session", {}).get("session_id"),
                       result_text=result["result_text"], cost_usd=result["cost"]["usd"])
        meta.human_approval = result.get("approval") if result["status"] == "awaiting_approval" else None
        for key in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens"):
            setattr(meta, key, result["usage"].get(key))
        stage = "timeout" if result["status"] == "timed_out" else result["status"]
        return (stage, result.get("exit_code"),
                result["error"]["message"] if result["error"] else None,
                meta, result.get("duration_s") or 0.0)

    def _adapter_event(self, run_id, agent, event):
        """Allowlisted adapter evidence reaches the existing UI run-events endpoint."""
        kind, data = event.get("type"), event.get("data", {})
        if kind not in {"usage", "checkpoint", "error"}:
            return  # logs/status do not need a synchronous database write per token
        with self.durable.begin() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            if kind == "usage":
                receipts = data.get("provider_receipts", [])
                for receipt in receipts:
                    identity = ("openrouter", str(receipt.get("response_id") or ""))
                    if db.get(ProviderReceipt, identity) is not None:
                        continue
                    put_provider_receipt(db, agent, f"mcd-run-{run_id}", receipt)
                    db.add(ProviderReceipt(provider=identity[0], response_id=identity[1], run_id=run_id,
                                           payload=json.dumps(receipt, sort_keys=True)))
                if receipts:
                    from models import UsageRecord
                    row = db.get(Run, run_id)
                    if row:
                        row.checkpoint = json.dumps({**json.loads(row.checkpoint or "{}"),
                                                     "provider_receipts_recorded": True})
                        records = db.scalars(select(UsageRecord).where(
                            UsageRecord.agent == agent, UsageRecord.session_id == f"mcd-run-{run_id}"))
                        row.cost_usd = sum(json.loads(record.payload)["reported_cost_usd"] for record in records)
            elif kind == "checkpoint":
                row = db.get(Run, run_id)
                if row and row.stage == "running":
                    row.checkpoint = json.dumps({**json.loads(row.checkpoint or "{}"),
                        "phase": "checkpoint", "adapter_checkpoint": data, "event_seq": event.get("seq")})
            elif kind == "error" and data.get("code") == "BUDGET_EXCEEDED":
                db.add(RunEvent(run_id=run_id, ts=_now(), kind="cap_exceeded",
                                text="BUDGET_EXCEEDED: Pi provider budget cap stopped dispatch or execution"))

    async def _execute(self, card: dict[str, Any], run_id: int) -> None:
        stage, exit_code, error, meta, seconds = await self._run_process(
            run_id, card["agent"], card["argv"], card["working_dir"], card["timeout_s"], card["adapter_spec"],
            attach=card.get("attach", False))
        await asyncio.to_thread(self._finish, run_id, card["id"], stage, exit_code, error, meta, seconds)

    @staticmethod
    def _record_run(s, run_id, stage, exit_code, error, meta, duration, now) -> Run | None:
        """Record a run's outcome once: only a run still 'running' can finish (compare-and-set)."""
        run = s.get(Run, run_id)
        if run is None or run.stage != "running":
            return None
        run.stage, run.exit_code, run.error = stage, exit_code, error
        run.ended_at, run.duration_s = now, round(duration, 2)
        run.checkpoint = json.dumps({**json.loads(run.checkpoint or "{}"), "phase": stage,
                                     "exit_code": exit_code})
        for f in ("model_reported", "provider", "session_id", "input_tokens", "output_tokens",
                  "cached_input_tokens", "cache_write_tokens", "result_text"):
            setattr(run, f, getattr(meta, f))
        # A result's aggregate must not replace deduplicated independent receipts,
        # nor erase usage recorded before an interruption with an unknown total.
        if not json.loads(run.checkpoint).get("provider_receipts_recorded") and meta.cost_usd is not None:
            run.cost_usd = meta.cost_usd
        s.add(RunEvent(run_id=run_id, ts=now, kind="stage", text=stage))
        provider_limits.observe(s, run, now)
        return run

    def _finish(self, run_id, card_id, stage, exit_code, error, meta, duration) -> None:
        now = _now()
        with self.durable.begin() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            candidate = s.get(Run, run_id)
            if candidate is None or candidate.stage != "running":
                return
            if stage != "cancelled" and json.loads(candidate.checkpoint or "{}").get("cancel_requested"):
                stage, error = "cancelled", LATE_CANCEL_ERROR
            if stage == "succeeded" and candidate.idempotency_key and s.scalar(select(exists().where(
                    Run.idempotency_key == candidate.idempotency_key, Run.id != run_id,
                    Run.stage.in_(("succeeded", "awaiting_approval"))))):
                stage, error = "failed", DUPLICATE_ERROR
            run = self._record_run(s, run_id, stage, exit_code, error, meta, duration, now)
            if run is None:
                return
            if stage == "awaiting_approval" and getattr(meta, "human_approval", None):
                cp = json.loads(run.checkpoint or "{}")
                cp["human_approval"] = meta.human_approval
                cp.pop("pending_decision", None)
                card = s.get(Card, card_id)
                # Each pause gets its own server nonce and route pin; a decision must match both.
                cp["approval_nonce"] = secrets.token_urlsafe(18)
                cp["approval_pin"] = approval.decision_pin(run, card)
                run.checkpoint = json.dumps(cp)
                run.ended_at, run.pid = None, None
                if card:
                    card.column, card.updated_at = "review", now
                # This is a pause, not a result, retry, handoff or output publication.
                return
            if stage == "interrupted":  # the process was killed outside MCD; usage stays recorded
                self._requeue_or_fail(s, run, now)
                return
            card = s.get(Card, card_id)
            if card and card.column == "running":
                if stage != "succeeded":
                    self._quarantine(s, run, stage, error, now)
                retrying = self._retryable(stage, error) and run.attempt < card.max_attempts and not projects.card_model_locked(s, card)
                if retrying:
                    # Bounded exponential backoff; preserve the execution key so the attempt
                    # lineage and provider receipt deduplication remain durable.
                    delay = card.retry_backoff_s * (2 ** max(0, run.attempt - 1))
                    card.column, card.retry_after = "queued", now + delay
                    s.add(RunEvent(run_id=run.id, ts=now, kind="note",
                                   text=f"retry scheduled: attempt {run.attempt + 1} of {card.max_attempts} after {delay}s"))
                else:
                    card.column, card.retry_after = ("done" if stage == "succeeded" else "failed"), None
                    card.idempotency_key = None  # this execution has ended
                    if stage != "succeeded" and self._retryable(stage, error):
                        reason = f"retry budget exhausted after {run.attempt} of {card.max_attempts} attempts"
                        run.error = f"{reason}: {error or 'transient failure'}"
                        s.add(RunEvent(run_id=run.id, ts=now, kind="note", text=reason))
                    if card.needs_approval and not projects.binding(s, card.id):
                        approval.issue_challenge(card)  # its grant is spent; a rerun needs a new one
                card.updated_at = now
                # A retry is not a completed story and must not create a handoff, publish
                # output, or trigger a project route fallback from partial output.
                if not retrying:
                    projects.on_finish(s, card, run, stage)
                run.checkpoint = json.dumps({**json.loads(run.checkpoint or "{}"), "phase": run.stage})

    @staticmethod
    def _retryable(stage: str, message: str | None) -> bool:
        """Only taxonomy-marked transport/provider failures retry; timeouts need review."""
        if stage in {"cancelled", "timeout"}:
            return False
        if stage == "timeout":
            return True
        code = (message or "").split(":", 1)[0]
        return bool(ERRORS.get(code) and ERRORS[code].retryable)

    def _quarantine(self, s, run: Run, stage: str, message: str | None, now: int) -> None:
        """Record non-success output as unpublishable without mutating the user workspace."""
        root = self.runs_dir / "quarantine"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = root / f"run-{run.id}.json"
        # The run's own output files stay where they are; the record pins which ones to review.
        evidence = []
        if run.log_path:
            base = Path(run.log_path)
            for suffix in (".log", ".raw.log", ".stdout", ".stderr", ".adapter.jsonl"):
                if base.with_suffix(suffix).is_file():
                    evidence.append({"path": str(base.with_suffix(suffix)),
                                     "bytes": base.with_suffix(suffix).stat().st_size})
        payload = {"run_id": run.id, "card_id": run.card_id, "stage": stage, "reason": message,
                   "workspace": run.working_dir, "evidence": evidence, "quarantined_at": now,
                   "publishable": False}
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(payload, sort_keys=True))
        os.replace(tmp, path)
        run.checkpoint = json.dumps({**json.loads(run.checkpoint or "{}"),
                                     "quarantine": str(path), "publishable": False})
        s.add(RunEvent(run_id=run.id, ts=now, kind="note", text="partial artifacts quarantined; not publishable"))

    # ------------------------------------------------------------------ chat turns

    def thread_busy(self, thread_id: int) -> bool:
        return thread_id in self._chat_tasks

    def _claim_turn(self, message_id: int) -> tuple[dict[str, Any], int] | None:
        """Create the Run for an approved user message and mark it running."""
        now = _now()
        with self.sessions.begin() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            msg = s.get(ChatMessage, message_id)
            if msg is None or msg.role != "user" or msg.status not in ("pending_approval", "running"):
                return None
            if msg.approval_reasons and msg.approved_at is None:
                return None  # second line of defence: never run an unapproved turn
            thread = s.get(ChatThread, msg.thread_id)
            spec = self.registry.get(thread.agent) if thread else None
            if thread is None or spec is None:
                return None
            active = list(s.scalars(select(Run).where(Run.stage == "running")))
            if any(r.card_id and projects.binding(s, r.card_id) and (projects.overlap(thread.working_dir, r.working_dir) or (thread.agent==r.agent=="openclaw" and (s.get(Card,r.card_id).agent_target or "mm-main")==(thread.agent_target or "mm-main"))) for r in active):
                return None
            ctx = SimpleNamespace(mode=thread.mode, working_dir=thread.working_dir,
                                  agent_target=thread.agent_target, timeout_s=CHAT_TIMEOUT_S,
                                  subscription_billing=_reviewed_route_class(s, self.settings, thread, thread.model or spec.default_model()) == "subscription")
            argv = spec.build(ctx, msg.text, thread.model or spec.default_model(), self.settings.default_budget_usd,
                              spec.binary(self.settings), session_id=thread.session_id)
            run = Run(thread_id=thread.id, agent=thread.agent,
                      model_requested=thread.model or spec.default_model(), stage="running",
                      started_at=now, working_dir=thread.working_dir,
                      command=json.dumps(redact(argv, msg.text)), log_path="",
                      checkpoint=json.dumps({"dispatch_policy": dispatch_snapshot(thread, self.settings.default_budget_usd, _reviewed_route_class(s, self.settings, thread, thread.model or spec.default_model()))}))
            s.add(run)
            s.flush()
            run.log_path = str(self.runs_dir / f"run-{run.id}.log")
            s.add(RunEvent(run_id=run.id, ts=now, kind="stage", text="running"))
            msg.status, msg.run_id = "running", run.id
            thread.last_activity_at = now
            return ({"thread_id": thread.id, "message_id": msg.id, "agent": thread.agent,
                     "working_dir": thread.working_dir, "argv": argv,
                     "adapter_spec": claimed_spec(run, ctx, msg.text,
                         self.settings.default_budget_usd, thread.session_id, msg.id)}, run.id)

    async def start_turn(self, message_id: int) -> int | None:
        """Run an approved user message. Returns the run id, or None if it may not run."""
        await self._recover_adapters()
        claimed = await asyncio.to_thread(self._claim_turn, message_id)
        if claimed is None:
            return None
        turn, run_id = claimed
        self._handles[run_id] = _Handle()
        task = asyncio.create_task(self._execute_turn(turn, run_id), name=f"turn-{run_id}")
        self._chat_tasks[turn["thread_id"]] = task
        task.add_done_callback(lambda _t, tid=turn["thread_id"], rid=run_id: self._forget_turn(tid, rid))
        return run_id

    def _forget_turn(self, thread_id: int, run_id: int) -> None:
        self._chat_tasks.pop(thread_id, None)
        self._handles.pop(run_id, None)

    async def _execute_turn(self, turn: dict[str, Any], run_id: int) -> None:
        async with self._chat_slots:
            stage, exit_code, error, meta, seconds = await self._run_process(
                run_id, turn["agent"], turn["argv"], turn["working_dir"], CHAT_TIMEOUT_S, turn["adapter_spec"])
        await asyncio.to_thread(self._finish_turn, run_id, turn, stage, exit_code, error, meta, seconds)

    def _finish_turn(self, run_id, turn, stage, exit_code, error, meta, duration) -> None:
        now = _now()
        with self.durable.begin() as s:
            row = s.get(Run, run_id)
            if row is not None and stage != "cancelled" and json.loads(row.checkpoint or "{}").get("cancel_requested"):
                stage, error = "cancelled", LATE_CANCEL_ERROR
            run = self._record_run(s, run_id, stage, exit_code, error, meta, duration, now)
            if run is None:
                return
            if stage == "cancelled":
                self._quarantine(s, run, stage, error, now)
            msg = s.get(ChatMessage, turn["message_id"])
            thread = s.get(ChatThread, turn["thread_id"])
            if msg is None or thread is None:
                return
            msg.status = {"succeeded": "done", "cancelled": "cancelled"}.get(stage, "failed")
            reply = meta.result_text if stage == "succeeded" else f"({stage}: {error})"
            s.add(ChatMessage(
                thread_id=thread.id, role="assistant", text=reply or "(no reply)",
                status="done" if stage == "succeeded" else "failed", run_id=run_id,
                model=meta.model_reported or s.get(Run, run_id).model_requested,
                input_tokens=meta.input_tokens, output_tokens=meta.output_tokens,
                cost_usd=meta.cost_usd, duration_s=round(duration, 2), created_at=now,
            ))
            spec = self.registry.get(thread.agent)
            if thread.session_id is None and meta.session_id and spec and not spec.preassigned_session:
                thread.session_id = meta.session_id
            thread.last_activity_at = now

    # ------------------------------------------------------------------ control

    async def decide(self, run_id: int, decision: dict) -> dict:
        """Commit intent before calling resume; restart replays the exact same decision.

        Adapter.resume must journal decisions and completed calls before relaunching.
        No start(), new Run, new key, model selection or prompt reconstruction occurs.
        A refused decision is recorded on the run's events.
        """
        try:
            return await self._decide(run_id, decision)
        except AdapterError as exc:
            if exc.code not in {"UNKNOWN_RUN", "CONCURRENCY_CONFLICT"}:  # the latter is only deferred
                await asyncio.to_thread(self.audit_decision, run_id, decision, f"{exc.code}: {exc}")
            raise

    def audit_decision(self, run_id: int, decision: dict, reason: str) -> None:
        with self.durable.begin() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            if s.get(Run, run_id) is None:
                return
            s.add(RunEvent(run_id=run_id, ts=_now(), kind="note", text=(
                f"decision refused: {reason}; approval {str(decision.get('approval_id'))[:120]}, "
                f"decision {str(decision.get('decision_id'))[:120]}, actor {str(decision.get('actor'))[:120]}")))
        logger.warning("run %s decision refused: %s", run_id, reason)

    def _route_unchanged(self, s, run: Run) -> bool:
        cp = json.loads(run.checkpoint or "{}")
        card = s.get(Card, run.card_id) if run.card_id else None
        return bool(cp.get("approval_pin")) and hmac.compare_digest(
            cp["approval_pin"], approval.decision_pin(run, card))

    async def _decide(self, run_id: int, decision: dict) -> dict:
        await self._recover_adapters()
        async with self._decision_lock:
            with self.durable.begin() as db:
                db.execute(text("BEGIN IMMEDIATE"))
                run = db.get(Run, run_id)
                if run is None:
                    raise AdapterError("UNKNOWN_RUN", "Run not found")
                cp = json.loads(run.checkpoint or "{}")
                history = cp.get("decisions", {})
                if any(d["decision_id"] == decision["decision_id"] and aid != decision["approval_id"]
                       for aid, d in history.items()):
                    raise AdapterError("DECISION_CONFLICT", "Decision identity was already used for another approval")
                old = history.get(decision["approval_id"])
                if old:
                    if any(old.get(k) != decision.get(k) for k in (
                            "decision_id", "verdict", "answer_text", "option_id", "approved_output_sha256", "actor")):
                        raise AdapterError("DECISION_CONFLICT", "That approval already has a different decision")
                    db.add(RunEvent(run_id=run_id, ts=_now(), kind="note",
                                    text="identical decision replay ignored; nothing was resumed again"))
                    return dict(run_id=str(run_id), status=run.stage, replayed=True)
                if run.stage != "awaiting_approval" or not cp.get("human_approval"):
                    raise AdapterError("INVALID_TRANSITION", "Run is not waiting for a checkpoint decision")
                approval.validate_decision(cp["human_approval"], decision)
                if decision["verdict"] != "reject" and not self._route_unchanged(db, run):
                    raise AdapterError("DECISION_CONFLICT", "This run's route changed since it paused. "
                                       "Reject this decision and review a new run.")
                pending = cp.get("pending_decision")
                if pending and pending != decision:
                    # decided_at is assigned by the server, so exact client retries use the
                    # previously committed payload rather than another timestamp.
                    if any(pending.get(k) != decision.get(k) for k in decision if k != "decided_at"):
                        raise AdapterError("DECISION_CONFLICT", "A decision is already being applied")
                    decision = pending
                cp["pending_decision"] = decision
                run.checkpoint = json.dumps(cp)
            await self._apply_or_abandon(run_id, decision)
            return dict(run_id=str(run_id), status="cancelled" if decision["verdict"] == "reject" else "running", replayed=False)

    async def _apply_or_abandon(self, run_id: int, decision: dict) -> None:
        """A decision that can never be applied ends the paused run instead of retrying forever.

        Waiting for a runtime slot is the only deferral. Other exceptions (adapter death,
        I/O) keep the committed decision for the next tick to replay.
        """
        try:
            await self._apply_decision(run_id, decision)
        except AdapterError as exc:
            if exc.code != "CONCURRENCY_CONFLICT":
                await self._abandon_decision(run_id, f"{exc.code}: {exc}")
            raise

    async def _abandon_decision(self, run_id: int, message: str) -> None:
        with self.sessions() as db:
            row = db.get(Run, run_id)
            agent = row.agent if row else None
        adapter = self.adapters.get(agent)
        if adapter is not None and not isinstance(adapter, LegacyAgentAdapter):
            # Retire the checkpoint so nothing can resume it after the run is failed.
            try:
                await adapter.cancel(dict(schema_version=SCHEMA_VERSION, run_id=str(run_id),
                                          request_id=f"abandoned-decision:{run_id}", reason="operator", actor="mcd"))
            except AdapterError:
                pass
        await asyncio.to_thread(self._fail_paused, run_id, message)

    def _fail_paused(self, run_id: int, message: str) -> None:
        now = _now()
        with self.durable.begin() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            run = s.get(Run, run_id)
            if run is None or run.stage != "awaiting_approval":
                return
            cp = json.loads(run.checkpoint or "{}")
            for key in ("human_approval", "approval_nonce", "approval_pin"):
                cp.pop(key, None)
            pending = cp.pop("pending_decision", None)
            if pending:
                cp["unapplied_decision"] = pending  # audit evidence; never replayed
            cp["phase"] = "failed"
            # Usage recorded before the checkpoint stays on the row.
            run.checkpoint, run.stage, run.error, run.ended_at = json.dumps(cp), "failed", message, now
            s.add(RunEvent(run_id=run_id, ts=now, kind="stage", text="failed"))
            card = s.get(Card, run.card_id) if run.card_id else None
            if card:
                self._quarantine(s, run, "failed", message, now)
                card.column, card.retry_after, card.updated_at = "failed", None, now
                card.idempotency_key = None
                projects.on_finish(s, card, run, "failed")

    async def _apply_decision(self, run_id: int, decision: dict) -> None:
        task = self._tasks.get(run_id)
        if task:
            await asyncio.shield(task)  # let the pause's finish/forget complete first
            self._forget(run_id)
        with self.sessions() as db:
            run = db.get(Run, run_id)
            agent, card_id = run.agent, run.card_id
            # A committed decision replayed after a restart still resumes only the pinned route.
            if decision["verdict"] != "reject" and not self._route_unchanged(db, run):
                raise AdapterError("DECISION_CONFLICT", "Run route changed since it paused")
            if len(self._tasks) >= self.settings.max_concurrent_runs:
                raise AdapterError("CONCURRENCY_CONFLICT", "Decision recorded; waiting for a runtime slot")
            if run.agent in {"picoclaw", "zeroclaw"} and decision["verdict"] != "reject":
                card = db.get(Card, card_id)
                link = projects.binding(db, card_id)
                caps = self.pi_scope_caps.get((link.project_id, link.revision)) if link else None
                if caps is None:
                    raise AdapterError("BUDGET_EXCEEDED", "Approved scope caps are not bound at resume")
                from models import ProjectTask
                ids = select(ProjectTask.card_id).where(ProjectTask.project_id == link.project_id)
                prior = [r for r in db.scalars(select(Run).where(Run.card_id.in_(ids)))
                         if r.agent in {"picoclaw", "zeroclaw"} or r.provider == "openrouter"]
                if any(r.cost_usd is None for r in prior) or sum(r.cost_usd for r in prior) > caps.max_project_usd:
                    raise AdapterError("BUDGET_EXCEEDED", "Project usage is unreconciled or exceeds its approved cap")
                if run.cost_usd > caps.max_run_usd:
                    raise AdapterError("BUDGET_EXCEEDED", "Run exceeds its approved cap")
                route = {"agent": agent, "model": run.model_requested}
                if not any(all(route[k] == r[k] for k in route) for r in
                           projects.approved_story_routes(projects.get(db, link.project_id), link)):
                    raise AdapterError("MODEL_NOT_ALLOWED", "Run route is no longer approved")
        adapter = self.adapters[agent]
        ack = await adapter.resume(decision)
        expected = "cancelled" if decision["verdict"] == "reject" else "running"
        if str(ack.get("run_id")) != str(run_id) or ack.get("status") != expected:
            raise AdapterError("RESULT_INVALID", "Adapter resume returned an unexpected run or state")
        with self.durable.begin() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            run = db.get(Run, run_id)
            cp = json.loads(run.checkpoint or "{}")
            if cp.get("pending_decision") != decision:
                raise AdapterError("DECISION_CONFLICT", "Pending decision changed")
            cp.setdefault("decisions", {})[decision["approval_id"]] = decision
            for key in ("pending_decision", "human_approval", "approval_nonce", "approval_pin"):
                cp.pop(key, None)  # the nonce is spent; a replayed request no longer matches
            cp["phase"] = "running"
            run.checkpoint, run.stage, run.ended_at = json.dumps(cp), "running", None
            card = db.get(Card, card_id)
            card.column, card.updated_at = "running", _now()
            db.add(RunEvent(run_id=run_id, ts=_now(), kind="decision",
                           text=json.dumps(decision, sort_keys=True)))
        self._follow(run_id, card_id, agent)

    async def _resume_pending_decisions(self) -> None:
        async with self._decision_lock:
            with self.sessions() as db:
                pending = [(r.id, json.loads(r.checkpoint or "{}").get("pending_decision"))
                           for r in db.scalars(select(Run).where(Run.stage == "awaiting_approval"))]
            for run_id, decision in pending:
                if decision:
                    # One unapplicable decision must not stop every other run from dispatching.
                    try:
                        await self._apply_or_abandon(run_id, decision)
                    except AdapterError:
                        pass
                    except Exception:
                        logger.exception("pending decision for run %s not applied; will retry", run_id)

    async def _kill(self, handle: _Handle) -> None:
        await LegacyAgentAdapter.kill(handle)

    async def cancel(self, run_id: int) -> bool:
        with self.durable.begin() as db:
            row = db.get(Run, run_id)
            if row is None or row.stage != "running":
                return False
            cp = json.loads(row.checkpoint or "{}")
            if not cp.get("cancel_requested"):
                row.checkpoint = json.dumps({**cp, "cancel_requested": True, "cancel_requested_at": _now()})
                db.add(RunEvent(run_id=run_id, ts=_now(), kind="note", text="operator cancellation requested"))
            agent = row.agent
        self._cancel_requested.add(run_id)
        if run_id not in self._handles:
            # The execution task observes the request before adapter.start(); after a restart,
            # recovery reads it from the checkpoint.
            return True
        await self._signal_cancel(run_id, agent)
        return True

    async def _signal_cancel(self, run_id: int, agent: str) -> None:
        handle = self._handles.setdefault(run_id, _Handle())
        handle.cancel_requested = True
        adapter = self.adapters.get(agent)
        if adapter is not None:
            try:
                await adapter.cancel(dict(schema_version=SCHEMA_VERSION, run_id=str(run_id),
                                          request_id=f"operator:{run_id}", reason="operator", actor="mcd"))
            except AdapterError as exc:
                if exc.code != "UNKNOWN_RUN":
                    raise
                await self._kill(handle)  # claimed but not yet started
        else:
            await self._kill(handle)

    def is_running(self, run_id: int) -> bool:
        return run_id in self._tasks

    # ------------------------------------------------------------------ retention

    def prune(self, now: int) -> int:
        """Delete runs (and their log files) and idle chat threads past the retention window.

        Cards stay. Returns the number of runs removed.
        """
        cutoff = now - self.settings.run_retention_days * 86400
        removed_ids = []
        with self.sessions.begin() as s:
            for thread in s.execute(select(ChatThread).where(ChatThread.last_activity_at < cutoff)).scalars():
                if thread.id not in self._chat_tasks:
                    removed_ids.extend(s.scalars(select(Run.id).where(Run.thread_id == thread.id)))
                    remove_run_logs(s.execute(select(Run.log_path).where(Run.thread_id == thread.id)).scalars())
                    s.delete(thread)
            old = s.execute(select(Run).where(Run.started_at < cutoff,
                Run.stage.not_in(("running", "awaiting_approval")))).scalars().all()
            for run in old:
                remove_run_logs([run.log_path])
                s.delete(run)
            for adapter in self.adapters.values():
                if isinstance(adapter, LegacyAgentAdapter):
                    adapter.forget([*removed_ids, *(run.id for run in old)])
            return len(old)
