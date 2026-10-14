"""Live status: commit hooks, the bounded bus and the SSE stream (apps/api/live_status.py)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import tracemalloc

import pytest

import live_status
from live_status import RING_SIZE, StatusBus
from models import Card, Run, RunEvent


@pytest.fixture
def bus(monkeypatch):
    fresh = StatusBus()
    monkeypatch.setattr(live_status, "BUS", fresh)
    return fresh


def _card(**kw) -> Card:
    now = int(time.time())
    return Card(**{"title": "t", "body": "b", "timeout_s": 60, "created_at": now, "updated_at": now, **kw})


def _run(card_id: int, **kw) -> Run:
    return Run(**{"card_id": card_id, "agent": "claude", "stage": "running", "started_at": int(time.time()),
                  "working_dir": "/tmp", "command": "[]", "log_path": "/tmp/x.log", **kw})


def _events(bus: StatusBus, after: int = 0) -> list[dict]:
    return [e for _, e in bus.since(after)[0]]


def _parse(frame: str) -> dict:
    out = {}
    for line in frame.strip().splitlines():
        key, _, value = line.partition(": ")
        out[key] = value
    if "data" in out:
        out["data"] = json.loads(out["data"])
    return out


# ----------------------------------------------------------------------------- commit hooks


def test_state_transitions_publish_after_commit_only(sessions, bus):
    with sessions() as s:
        card = _card()
        s.add(card)
        s.flush()
        assert bus.seq == 0  # flushed is not committed
        s.commit()
        assert _events(bus) == [{"type": "card", "change": "created", "card_id": card.id,
                                 "column": "backlog", "ts": _events(bus)[0]["ts"]}]

        seq = bus.seq
        card.title = "renamed"  # not a state transition
        s.commit()
        assert bus.seq == seq

        card.column = "queued"
        run = _run(card.id)
        s.add(run)
        s.commit()
        types = {(e["type"], e["change"]) for e in _events(bus, seq)}
        assert types == {("card", "updated"), ("run", "created")}

        seq = bus.seq
        run.stage = "succeeded"
        s.add(RunEvent(run_id=run.id, ts=int(time.time()), kind="stage", text="succeeded"))
        s.commit()
        got = _events(bus, seq)
        run_event = next(e for e in got if e["type"] == "run")
        assert {"change": "updated", "run_id": run.id, "card_id": card.id,
                "stage": "succeeded"}.items() <= run_event.items()
        assert any(e["type"] == "run_event" and e["run_id"] == run.id for e in got)
        assert all("text" not in e for e in got)  # run text never enters the buffer

        seq = bus.seq
        card.column = "done"
        s.flush()
        s.rollback()
        assert bus.seq == seq


def test_delete_publishes_identity_and_a_broken_hook_never_fails_a_commit(sessions, bus, monkeypatch):
    with sessions() as s:
        card = _card()
        s.add(card)
        s.commit()
        card_id, seq = card.id, bus.seq
        s.expire(card)  # attributes unloaded: describing the deleted row must not touch them
        s.delete(card)
        s.commit()
        assert [{k: e[k] for k in ("type", "change", "card_id")} for e in _events(bus, seq)] == [
            {"type": "card", "change": "deleted", "card_id": card_id}]

        def broken(*_a):
            raise RuntimeError("boom")
        monkeypatch.setattr(live_status, "_describe", broken)
        seq = bus.seq
        s.add(_card(title="still saved"))
        s.commit()
        assert [e["type"] for e in _events(bus, seq)] == ["bulk"]
        assert s.query(Card).filter_by(title="still saved").count() == 1


def test_large_commit_collapses_to_one_bulk_event(sessions, bus):
    with sessions() as s:
        s.add_all([_card(title=f"c{i}") for i in range(live_status.MAX_EVENTS_PER_COMMIT + 10)])
        s.commit()
    assert [e["type"] for e in _events(bus)] == ["bulk"]


def test_api_card_creation_reaches_the_bus(make_client, bus, tmp_path):
    client = make_client()
    seq = bus.seq
    created = client.post("/api/cards", json={"title": "live", "body": "x", "agent": "claude",
                                              "working_dir": str(tmp_path / "ws" / "proj")})
    assert created.status_code == 201, created.text
    assert any(e["type"] == "card" and e["card_id"] == created.json()["id"] for e in _events(bus, seq))


# ----------------------------------------------------------------------------- bounded memory


def test_ring_is_bounded_and_reports_lost_events():
    bus = StatusBus()
    for i in range(RING_SIZE * 4):
        bus.publish([{"type": "card", "card_id": i, "column": "running"}])
    items, lost = bus.since(0)
    assert len(items) == RING_SIZE and lost
    assert items[0][0] == RING_SIZE * 3 + 1
    assert bus.since(RING_SIZE * 3) == (items, False)  # exactly at the edge: nothing lost
    assert bus.since(bus.seq) == ([], False)


def test_buffer_memory_stays_flat_over_a_long_soak():
    """A full ring stays under the documented 512 KiB and does not grow with more events."""
    def event(i):  # fresh strings per event, like values loaded from the database
        return {"type": "run", "change": "updated", "run_id": i, "card_id": i + 1,
                "stage": f"awaiting_approval-{i % 7}"}

    tracemalloc.start()
    try:
        empty = tracemalloc.get_traced_memory()[0]
        bus = StatusBus()
        for i in range(RING_SIZE):
            bus.publish([event(i)])
        full = tracemalloc.get_traced_memory()[0]
        for i in range(50_000):  # ~14 hours of one transition per second
            bus.publish([event(i)])
        settled = tracemalloc.get_traced_memory()[0]
        for i in range(50_000):  # and as long again
            bus.publish([event(i)])
        after = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    assert full - empty < live_status.BUFFER_LIMIT_BYTES
    # Flat means no growth with more events. A small one-off allocator overhead differs between Python
    # builds (about 24 KiB on macOS), so the bound is on the second 50,000 events, not the first.
    assert after - settled < 4 * 1024
    assert settled - full < 64 * 1024


def test_subscriber_cap():
    async def main():
        bus = StatusBus(max_subscribers=2)
        a, b = bus.subscribe(), bus.subscribe()
        assert a and b and bus.subscribe() is None
        bus.unsubscribe(a)
        assert bus.subscribe() is not None
    asyncio.run(main())


# ----------------------------------------------------------------------------- stream


def test_stream_pushes_a_commit_from_another_thread_within_2s():
    async def main():
        bus = StatusBus()
        wake = bus.subscribe()
        gen = live_status.stream(bus, wake, None, heartbeat_s=10)
        assert (await anext(gen)) == f"retry: {live_status.RETRY_MS}\n\n"
        hello = _parse(await anext(gen))
        assert hello["event"] == "hello" and hello["data"] == {"boot": bus.boot, "reset": True}
        started = time.monotonic()
        threading.Timer(0.05, bus.publish, [[{"type": "card", "card_id": 3, "column": "running"}]]).start()
        frame = _parse(await asyncio.wait_for(anext(gen), 2))
        assert time.monotonic() - started < 1
        assert frame["event"] == "status" and frame["id"] == f"{bus.boot}:1"
        assert frame["data"]["column"] == "running"
        await gen.aclose()
    asyncio.run(main())


def test_reconnect_replays_missed_events_and_resets_after_a_restart():
    async def first_frames(bus, last, n):
        wake = bus.subscribe()
        gen = live_status.stream(bus, wake, last, heartbeat_s=0.05)
        frames = [_parse(await anext(gen)) for _ in range(n)]
        await gen.aclose()
        bus.unsubscribe(wake)
        return frames

    bus = StatusBus()
    for i in range(3):
        bus.publish([{"type": "card", "card_id": i, "column": "queued"}])
    # Same API process: the cursor resumes and only the missed events are sent.
    frames = asyncio.run(first_frames(bus, f"{bus.boot}:1", 4))
    assert frames[1]["data"]["reset"] is False
    assert [f["id"] for f in frames[2:]] == [f"{bus.boot}:2", f"{bus.boot}:3"]
    # Restarted API (new boot id) or garbage: reset, then keepalives.
    for last in ("old-boot:3", f"{bus.boot}:999", "nonsense", None):
        frames = asyncio.run(first_frames(bus, last, 3))
        assert frames[1]["data"]["reset"] is True and frames[1]["id"] == f"{bus.boot}:3"
        assert frames[2] == {"": "keepalive"}  # nothing replayed


def test_slow_client_behind_the_ring_gets_reset():
    async def main():
        bus = StatusBus(size=4)
        wake = bus.subscribe()
        gen = live_status.stream(bus, wake, None, heartbeat_s=5)
        await anext(gen), await anext(gen)
        for i in range(10):
            bus.publish([{"type": "card", "card_id": i, "column": "queued"}])
        frame = _parse(await anext(gen))
        assert frame["event"] == "reset" and frame["id"] == f"{bus.boot}:10"
        await gen.aclose()
    asyncio.run(main())


def test_close_and_max_lifetime_end_the_stream():
    async def drain(bus, **kw):
        wake = bus.subscribe()
        return [f async for f in live_status.stream(bus, wake, None, **kw)]

    bus = StatusBus()
    threading.Timer(0.05, bus.close).start()
    started = time.monotonic()
    assert len(asyncio.run(asyncio.wait_for(drain(bus, heartbeat_s=30), 2))) == 2
    assert time.monotonic() - started < 1
    assert len(asyncio.run(drain(StatusBus(), heartbeat_s=30, max_s=0))) == 2


def test_endpoint_headers_and_busy_frame(make_client, bus, monkeypatch):
    client = make_client()
    monkeypatch.setattr(live_status, "STREAM_MAX_S", 0)
    res = client.get("/api/events/stream")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["cache-control"] == "no-cache"
    assert "event: hello" in res.text
    assert bus.subscribers == 0  # released when the stream ended

    bus.max_subscribers = 0
    res = client.get("/api/events/stream")
    assert res.status_code == 200 and "event: busy" in res.text
    assert f"retry: {live_status.BUSY_RETRY_MS}" in res.text
