"""Timeout retries must not repeat partial work, even after dispatcher restart."""
import asyncio
import os

import pytest
from sqlalchemy import select

from dispatcher import Dispatcher
from models import Card, Run, RunEvent
from .test_dispatcher import _settings, _registry, _card, _drain


@pytest.mark.parametrize("restart", [False, True])
def test_timeout_kill_retry_fails_closed(sessions, tmp_path, monkeypatch, restart):
    import dispatcher
    monkeypatch.setattr(dispatcher, "KILL_GRACE_S", 0.1)
    try:
        import legacy_adapters
    except ImportError:
        pass
    else:
        monkeypatch.setattr(legacy_adapters, "KILL_GRACE_S", 0.1)
    marker = tmp_path / "dispatches"
    body = ("import os,signal,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            f"open({str(marker)!r},'a').write(str(os.getpid())+chr(10));"
            "time.sleep(60)")
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, body, timeout_s=1)
    asyncio.run(_drain(d))
    with sessions.begin() as s:
        original = s.scalar(select(Run).where(Run.card_id == cid))
        assert original.stage == "timeout"
        rid, error = original.id, original.error
        key = getattr(original, "idempotency_key", None) or f"mcd:run:{rid}"
        card = s.get(Card, cid)
        card.column = "queued"
        if hasattr(card, "idempotency_key"):
            card.idempotency_key = key
    pid = int(marker.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    if restart:
        d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    asyncio.run(_drain(d))
    with sessions() as s:
        runs = list(s.scalars(select(Run).where(Run.card_id == cid)))
        assert len(runs) == 1
        assert runs[0].id == rid and runs[0].stage == "timeout" and runs[0].error == error
        assert s.get(Card, cid).column == "failed"
        events = list(s.scalars(select(RunEvent).where(RunEvent.run_id == rid)))
        assert any("RETRY_REQUIRES_REVIEW" in e.text and key in e.text for e in events)
    assert marker.read_text().splitlines() == [str(pid)]
    assert asyncio.run(d.tick()) == 0


def test_timeout_requeue_is_serialized_and_does_not_block_other_cards(sessions, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from .test_dispatcher import SUCCESS

    cid = _card(sessions, tmp_path, "original")
    with sessions.begin() as s:
        row = Run(card_id=cid, agent="fake", stage="timeout", started_at=1,
                  working_dir=str(tmp_path), command="[]", log_path="", error="provider timeout")
        s.add(row)
        s.flush()
        rid = row.id
        card = s.get(Card, cid)
        # Changed input and a cleared key must not bypass uncertain partial work.
        card.body, card.model = "changed input", "changed model"
        if hasattr(card, "idempotency_key"):
            card.idempotency_key = None
    healthy = _card(sessions, tmp_path, SUCCESS)
    workers = [Dispatcher(sessions, _settings(tmp_path), registry=_registry()) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda d: d._claim(1), workers))
    assert sum(len(claim) for claim in claims) == 1
    assert next(claim[0][0]["id"] for claim in claims if claim) == healthy
    # Repeated operator requeue records one refusal, never another start.
    with sessions.begin() as s:
        s.get(Card, cid).column = "queued"
    assert workers[0]._claim(1) == []
    with sessions() as s:
        assert len(list(s.scalars(select(Run).where(Run.card_id == cid)))) == 1
        notes = list(s.scalars(select(RunEvent).where(RunEvent.run_id == rid)))
        assert len(notes) == 1 and "RETRY_REQUIRES_REVIEW" in notes[0].text
        assert s.get(Card, cid).column == "failed"
