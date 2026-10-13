"""Approvals are single-use and bound to their task/run, route pin, nonce and expiry.

Task approvals use the real API and dispatcher with a synthetic short-lived runner process.
Checkpoint decisions use the durable synthetic runner from test_human_gates. No provider,
credential or live service is involved.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from sqlalchemy import select

import approval
from adapter_contract import AdapterError
from dispatcher import Dispatcher
from models import Card, Run, RunEvent
from .test_dispatcher import SUCCESS, _drain, _registry, _settings
from .test_human_gates import CheckpointAdapter, decision, drain, row, setup
from .test_dispatcher import _card

# A runnable synthetic program whose text trips the "deploys or releases" approval rule.
BODY = SUCCESS + "  # deploy the release"


# ----------------------------------------------------------------------------- task approvals


def _setup(make_client, tmp_path):
    client = make_client()
    card = client.post("/api/cards", json={"title": "Release", "body": BODY, "agent": "claude",
                                           "working_dir": str(tmp_path / "ws" / "proj")}).json()
    assert card["needs_approval"] and card["approval_challenge"] and card["approval_pin"]
    sessions = client.app.state.sessions
    with sessions.begin() as s:
        s.get(Card, card["id"]).agent = "fake"  # route the synthetic runner; reviewed below
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    return client, sessions, d, card["id"]


def _shown(client, cid):
    view = client.get(f"/api/cards/{cid}").json()
    return {"challenge": view["approval_challenge"], "pin": view["approval_pin"]}


def _runs(sessions, cid):
    with sessions() as s:
        return list(s.scalars(select(Run).where(Run.card_id == cid)))


def _audit(sessions, cid):
    with sessions() as s:
        return approval.load_grant(s.get(Card, cid)).get("audit", [])


def test_single_legitimate_approval_dispatches_once(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    shown = _shown(client, cid)
    assert client.post(f"/api/cards/{cid}/approve", json=shown).status_code == 200
    asyncio.run(_drain(d))
    runs = _runs(sessions, cid)
    assert [r.stage for r in runs] == ["succeeded"]
    with sessions() as s:
        notes = [e.text for e in s.scalars(select(RunEvent).where(RunEvent.run_id == runs[0].id))]
        card = s.get(Card, cid)
        assert card.column == "done" and card.approved_at is None  # the grant is spent
    assert any("bound to this run" in n and shown["pin"][:12] in n for n in notes)


def test_replayed_approval_request_is_refused_and_audited(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    shown = _shown(client, cid)
    assert client.post(f"/api/cards/{cid}/approve", json=shown).status_code == 200
    replay = client.post(f"/api/cards/{cid}/approve", json=shown)
    assert replay.status_code == 409 and "already used" in replay.json()["detail"]
    asyncio.run(_drain(d))
    assert client.post(f"/api/cards/{cid}/approve", json=shown).status_code == 409
    moved = client.patch(f"/api/cards/{cid}", json={"column": "queued"}).json()
    assert moved["column"] == "review" and moved["approved_at"] is None
    asyncio.run(_drain(d))
    assert len(_runs(sessions, cid)) == 1
    events = [a["event"] for a in _audit(sessions, cid)]
    assert events.count("refused") == 2 and events.count("used") == 1


def test_route_swap_after_approval_never_dispatches(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    assert client.post(f"/api/cards/{cid}/approve", json=_shown(client, cid)).status_code == 200
    with sessions.begin() as s:
        s.get(Card, cid).model = "swapped-model"
    assert asyncio.run(d.tick()) == 0
    assert _runs(sessions, cid) == []
    last = _audit(sessions, cid)[-1]
    assert (last["event"], last["reason"]) == ("dispatch_refused", "route or content changed since approval")
    with sessions() as s:
        assert s.get(Card, cid).column == "review"


def test_route_swap_before_approval_and_cross_card_replay_are_refused(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    shown = _shown(client, cid)
    other = client.post("/api/cards", json={"title": "Other", "body": BODY, "agent": "claude",
                                            "working_dir": str(tmp_path / "ws" / "proj")}).json()
    assert client.post(f"/api/cards/{other['id']}/approve", json=shown).status_code == 409
    with sessions.begin() as s:
        s.get(Card, cid).model = "swapped-model"
    refused = client.post(f"/api/cards/{cid}/approve", json=shown)
    assert refused.status_code == 409 and "changed" in refused.json()["detail"]
    assert _audit(sessions, cid)[-1]["reason"] == "route or content changed since it was shown"


def test_expired_approval_is_refused_at_claim(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    with sessions.begin() as s:
        card = s.get(Card, cid)
        approval.grant(card, approval.challenge(card), approval.route_pin(card), int(time.time()) - 120, 60)
        card.column = "queued"
    assert asyncio.run(d.tick()) == 0
    assert _runs(sessions, cid) == []
    assert _audit(sessions, cid)[-1]["reason"] == "approval expired before dispatch"


def test_requeue_of_the_same_execution_keeps_its_grant(make_client, tmp_path):
    client, sessions, d, cid = _setup(make_client, tmp_path)
    client.post(f"/api/cards/{cid}/approve", json=_shown(client, cid))
    assert d._claim(1)
    with sessions.begin() as s:  # an interruption requeue keeps the card's execution key
        card = s.get(Card, cid)
        assert card.idempotency_key and approval.load_grant(card)["execution_key"] == card.idempotency_key
        assert approval.grant_problem(card, int(time.time()), card.idempotency_key) is None
        # ...but a new execution of the same card does not.
        assert "already used" in approval.grant_problem(card, int(time.time()), None)


# ----------------------------------------------------------------------------- checkpoint decisions


def _events(sessions, rid):
    with sessions() as s:
        return [e.text for e in s.scalars(select(RunEvent).where(RunEvent.run_id == rid))]


def test_decision_nonce_is_single_use_and_bound_to_its_run(make_client, tmp_path):
    with make_client(built=False) as client:
        sessions = client.app.state.sessions
        d, a = setup(sessions, tmp_path)
        client.app.state.dispatcher = d
        first = _card(sessions, tmp_path, 'prompt', model='assigned')
        client.portal.call(d.tick); client.portal.call(drain, d)
        view = client.get(f'/api/cards/{first}').json()['last_run']
        rid, nonce = view['id'], view['approval']['nonce']
        body = {'approval_id': 'gate-1', 'decision_id': 'op-1', 'verdict': 'approve'}
        # Without the nonce, or with a guessed one, nothing is resumed.
        assert client.post(f'/api/runs/{rid}/decision', json=body).status_code == 409
        assert client.post(f'/api/runs/{rid}/decision', json={**body, 'approval_nonce': 'x'}).status_code == 409
        ok = client.post(f'/api/runs/{rid}/decision', json={**body, 'approval_nonce': nonce})
        assert ok.status_code == 200, ok.text
        client.portal.call(drain, d)
        assert row(sessions, first)[0].stage == 'succeeded' and a.starts == 1
        # Replaying the applied decision, onto the same run or a new paused run, is refused.
        assert client.post(f'/api/runs/{rid}/decision', json={**body, 'approval_nonce': nonce}).status_code == 409
        a2 = CheckpointAdapter(tmp_path / 'second.json')
        d2, _ = setup(sessions, tmp_path, a2)
        client.app.state.dispatcher = d2
        second = _card(sessions, tmp_path, 'prompt', model='assigned')
        client.portal.call(d2.tick); client.portal.call(drain, d2)
        rid2 = row(sessions, second)[0].id
        assert client.post(f'/api/runs/{rid2}/decision', json={**body, 'approval_nonce': nonce}).status_code == 409
        assert row(sessions, second)[0].stage == 'awaiting_approval' and a2.starts == 1
        refused = [t for t in _events(sessions, rid) + _events(sessions, rid2) if t.startswith('decision refused')]
        assert len(refused) == 4 and all('approval gate-1' in t for t in refused)


def test_route_swap_during_pause_is_refused_and_audited(sessions, tmp_path):
    d, a = setup(sessions, tmp_path)
    cid = _card(sessions, tmp_path, 'prompt', model='assigned')

    async def run():
        await d.tick(); await drain(d)
        r, _ = row(sessions, cid)
        with sessions.begin() as s:
            s.get(Card, cid).model = 'swapped-model'
        with pytest.raises(AdapterError, match='route changed'):
            await d.decide(r.id, decision(r.id))
        assert row(sessions, cid)[0].stage == 'awaiting_approval'
        assert any(t.startswith('decision refused: DECISION_CONFLICT') for t in _events(sessions, r.id))
        # Refusing the paused run is still allowed and runs nothing further.
        await d.decide(r.id, decision(r.id, 'reject')); await drain(d)
        assert row(sessions, cid)[0].stage == 'cancelled'
        assert a.read()['tools'] == {'before': {'count': 1, 'tokens': 12}}
    asyncio.run(run())


def test_route_swap_before_a_committed_decision_resumes_fails_closed(sessions, tmp_path):
    d, a = setup(sessions, tmp_path)
    cid = _card(sessions, tmp_path, 'prompt', model='assigned')

    async def run():
        await d.tick(); await drain(d)
        r, _ = row(sessions, cid)
        a.resume = lambda decision: (_ for _ in ()).throw(RuntimeError('API death before resume'))
        with pytest.raises(RuntimeError):
            await d.decide(r.id, decision(r.id))
        with sessions.begin() as s:  # the route changes while the service is down
            s.get(Card, cid).model = 'swapped-model'
        replacement, restored = setup(sessions, tmp_path)
        await replacement.tick(); await drain(replacement)
        final, card = row(sessions, cid)
        assert (final.stage, card.column) == ('failed', 'failed')
        assert final.error.startswith('DECISION_CONFLICT')
        assert restored.read()['tools'] == {'before': {'count': 1, 'tokens': 12}}  # never resumed
    asyncio.run(run())


class ExpiringAdapter(CheckpointAdapter):
    async def result(self, run_id):
        out = await super().result(run_id)
        out['approval']['expires_at'] = 1  # long past
        return out


def test_expired_checkpoint_approval_is_refused_but_can_be_rejected(sessions, tmp_path):
    d, a = setup(sessions, tmp_path, ExpiringAdapter(tmp_path / 'adapter.json'))
    cid = _card(sessions, tmp_path, 'prompt')

    async def run():
        await d.tick(); await drain(d)
        r, _ = row(sessions, cid)
        with pytest.raises(AdapterError, match='expired'):
            await d.decide(r.id, decision(r.id))
        assert any('expired' in t for t in _events(sessions, r.id))
        await d.decide(r.id, decision(r.id, 'reject')); await drain(d)
        assert row(sessions, cid)[0].stage == 'cancelled'
    asyncio.run(run())


def test_pause_records_nonce_and_pin_and_spends_them_on_apply(sessions, tmp_path):
    d, a = setup(sessions, tmp_path)
    cid = _card(sessions, tmp_path, 'prompt', model='assigned')

    async def run():
        await d.tick(); await drain(d)
        r, c = row(sessions, cid)
        cp = json.loads(r.checkpoint)
        assert cp['approval_nonce'] and cp['approval_pin'] == approval.decision_pin(r, c)
        await d.decide(r.id, decision(r.id)); await drain(d)
        cp = json.loads(row(sessions, cid)[0].checkpoint)
        assert 'approval_nonce' not in cp and 'approval_pin' not in cp
    asyncio.run(run())
