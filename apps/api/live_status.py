"""Live status: a bounded in-process feed of task, run and project state changes.

SQLAlchemy commit hooks record what changed (a card's column, a run's stage, a new run
event, a project's state) and `GET /api/events/stream` pushes it to the browser as
Server-Sent Events. The Tasks and Projects views refetch the affected JSON when an event
arrives; their existing polling stays as the fallback.

Memory is fixed regardless of uptime, event rate or slow clients, which matters on a
low-RAM Pi:
  - one shared ring of at most RING_SIZE small events (ids and short state strings only,
    never run text), under BUFFER_LIMIT_BYTES when full, and no per-client queues; each
    stream only keeps a cursor;
  - at most MAX_SUBSCRIBERS open streams (the next one gets a `busy` event and the UI keeps
    polling until it retries);
  - one commit publishes at most MAX_EVENTS_PER_COMMIT events, otherwise a single `bulk`.
A client that falls behind the ring, or reconnects to a restarted API (new boot id), is
told to `reset` and refetches everything, so nothing is silently missed.

Only commits made in this API process are seen. Writes from another process show up at
the next poll.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from collections import deque
from typing import AsyncIterator

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from models import Card, Project, ProjectMemory, ProjectTask, Run, RunEvent

RING_SIZE = 256
BUFFER_LIMIT_BYTES = 512 * 1024  # documented ceiling for a full ring (tests measure it)
MAX_SUBSCRIBERS = 16
MAX_EVENTS_PER_COMMIT = 32
HEARTBEAT_S = 15.0
STREAM_MAX_S = 600.0  # streams end and reconnect, so sign-in is re-checked periodically
RETRY_MS = 1000  # EventSource reconnect delay after a dropped stream (API restart)
BUSY_RETRY_MS = 30_000  # reconnect delay when the subscriber cap is reached

_PENDING = "live_status_pending"
_WATCHED = {Card: ("column", "needs_approval"), Run: ("stage",), Project: ("state", "revision")}
_CREATED = (Card, Run, RunEvent, Project, ProjectTask, ProjectMemory)
_DELETED = (Card, Run, Project)


class StatusBus:
    """Thread-safe publisher (sessions commit in worker threads) with asyncio subscribers."""

    def __init__(self, size: int = RING_SIZE, max_subscribers: int = MAX_SUBSCRIBERS):
        self.boot = secrets.token_hex(6)
        self.max_subscribers = max_subscribers
        self._ring: deque[tuple[int, dict]] = deque(maxlen=size)
        self._seq = 0
        self._lock = threading.Lock()
        self._waiters: dict[asyncio.Event, asyncio.AbstractEventLoop] = {}
        self._closed = False

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def subscribers(self) -> int:
        return len(self._waiters)

    def publish(self, events: list[dict]) -> None:
        if not events:
            return
        if len(events) > MAX_EVENTS_PER_COMMIT:
            events = [{"type": "bulk", "count": len(events)}]
        now = int(time.time())
        with self._lock:
            for e in events:
                self._seq += 1
                self._ring.append((self._seq, {**e, "ts": now}))
            waiters = list(self._waiters.items())
        self._wake(waiters)

    def since(self, seq: int) -> tuple[list[tuple[int, dict]], bool]:
        """Events after `seq`, and whether some of them already fell out of the ring."""
        with self._lock:
            lost = bool(self._ring) and seq < self._ring[0][0] - 1
            return [item for item in self._ring if item[0] > seq], lost

    def subscribe(self) -> asyncio.Event | None:
        """A wake-up event for one stream, or None when the subscriber cap is reached."""
        with self._lock:
            if self._closed or len(self._waiters) >= self.max_subscribers:
                return None
            wake = asyncio.Event()
            self._waiters[wake] = asyncio.get_running_loop()
            return wake

    def unsubscribe(self, wake: asyncio.Event) -> None:
        with self._lock:
            self._waiters.pop(wake, None)

    def close(self) -> None:
        """End every open stream (API shutdown) so a restart is not held up by idle clients."""
        with self._lock:
            self._closed = True
            waiters = list(self._waiters.items())
        self._wake(waiters)

    @property
    def closed(self) -> bool:
        return self._closed

    @staticmethod
    def _wake(waiters) -> None:
        for wake, loop in waiters:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:  # the subscriber's loop already closed
                pass


BUS = StatusBus()


# --------------------------------------------------------------------- commit hooks


def _describe(obj, change: str) -> dict | None:
    if isinstance(obj, Card):
        return {"type": "card", "change": change, "card_id": obj.id, "column": obj.column}
    if isinstance(obj, Run):
        return {"type": "run", "change": change, "run_id": obj.id, "card_id": obj.card_id,
                "stage": obj.stage}
    if isinstance(obj, RunEvent):
        return {"type": "run_event", "change": change, "run_id": obj.run_id, "kind": obj.kind}
    if isinstance(obj, Project):
        return {"type": "project", "change": change, "project_id": obj.id, "state": obj.state}
    if isinstance(obj, ProjectTask):
        return {"type": "project", "change": "task_added", "project_id": obj.project_id,
                "card_id": obj.card_id}
    if isinstance(obj, ProjectMemory):
        return {"type": "project", "change": "memory_added", "project_id": obj.project_id,
                "card_id": obj.card_id}
    return None


def _changed(obj) -> bool:
    attrs = _WATCHED.get(type(obj))
    if not attrs:
        return False
    state = inspect(obj)
    return any(state.attrs[a].history.has_changes() for a in attrs)


def _deleted(obj) -> dict:
    # Only the identity: touching an expired attribute of a deleted row would raise.
    key = (inspect(obj).identity or (None,))[0]
    return {"type": {Card: "card", Run: "run", Project: "project"}[type(obj)], "change": "deleted",
            {Card: "card_id", Run: "run_id", Project: "project_id"}[type(obj)]: key}


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _ctx) -> None:
    pending: list[dict] = session.info.setdefault(_PENDING, [])
    try:
        found = [_describe(o, "created") for o in session.new if isinstance(o, _CREATED)]
        found += [_describe(o, "updated") for o in session.dirty if _changed(o)]
        found += [_deleted(o) for o in session.deleted if isinstance(o, _DELETED)]
    except Exception:  # a UI hint must never fail a commit; clients just refetch everything
        found = [{"type": "bulk"}]
    # Bounded even for a huge transaction: anything over the cap collapses to `bulk` anyway.
    room = MAX_EVENTS_PER_COMMIT + 1 - len(pending)
    pending.extend(e for e in found[:max(room, 0)] if e)


@event.listens_for(Session, "after_commit")
def _publish(session: Session) -> None:
    try:
        BUS.publish(session.info.pop(_PENDING, []))
    except Exception:  # never surface from a commit; polling covers a lost hint
        pass


@event.listens_for(Session, "after_rollback")
def _discard(session: Session) -> None:
    session.info.pop(_PENDING, None)


# --------------------------------------------------------------------- SSE stream


def parse_cursor(value: str | None, bus: StatusBus) -> int | None:
    """Sequence from a `<boot>:<seq>` id, or None when it is missing or from another boot."""
    boot, _, seq = (value or "").partition(":")
    if boot != bus.boot or not seq.isdigit():
        return None
    return int(seq) if int(seq) <= bus.seq else None


def _frame(kind: str, data: dict, event_id: str | None = None) -> str:
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def busy_frame() -> str:
    """Sent instead of a stream when MAX_SUBSCRIBERS are open; the client keeps polling."""
    return f"retry: {BUSY_RETRY_MS}\n\n" + _frame("busy", {"max_subscribers": BUS.max_subscribers})


async def stream(bus: StatusBus, wake: asyncio.Event, last_id: str | None,
                 heartbeat_s: float = HEARTBEAT_S, max_s: float = STREAM_MAX_S) -> AsyncIterator[str]:
    """SSE frames for one subscriber. The caller must have subscribed `wake` and unsubscribes it."""
    cursor = parse_cursor(last_id, bus)
    reset = cursor is None
    if reset:
        cursor = bus.seq
    yield f"retry: {RETRY_MS}\n\n"
    yield _frame("hello", {"boot": bus.boot, "reset": reset}, f"{bus.boot}:{cursor}")
    deadline = time.monotonic() + max_s
    while not bus.closed and time.monotonic() < deadline:
        wake.clear()  # cleared before reading, so a publish in between still wakes us
        items, lost = bus.since(cursor)
        if lost:
            cursor = items[-1][0] if items else bus.seq
            yield _frame("reset", {"reason": "behind"}, f"{bus.boot}:{cursor}")
            continue
        for seq, data in items:
            cursor = seq
            yield _frame("status", data, f"{bus.boot}:{seq}")
        if items:
            continue
        try:
            await asyncio.wait_for(wake.wait(), timeout=min(heartbeat_s, max(deadline - time.monotonic(), 0)))
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
