"""Dispatcher tests with a fake agent that exists only here (never registered in production)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from types import SimpleNamespace

from sqlalchemy import select, update

import agents
import approval
from dispatcher import Dispatcher
from models import Card, Run


class FakeParser(agents.Parser):
    def feed(self, line):
        if line == "TRANSIENT_RATE_LIMIT":
            self.meta.error = "PROVIDER_RATE_LIMITED: synthetic transient failure"
            return [line]
        ev = agents._json(line)
        if ev and ev.get("type") == "result":
            self.meta.model_reported = ev.get("model")
            self.meta.input_tokens = ev.get("in")
            self.meta.output_tokens = ev.get("out")
            self.meta.result_text = ev.get("text")
            return ["finished"]
        return [line]


def _build(card, prompt, model, budget, binary):
    # The prompt is a tiny Python program; tests only.
    return [sys.executable, "-c", prompt] + (["--model", model] if card.agent == "openclaw" else [])


def _registry():
    spec = agents.AgentSpec("fake", "Fake", "worker", "claude_path", _build, FakeParser, default_model=lambda: "m1")
    return {"fake": spec}


def _settings(tmp_path, **kw):
    base = dict(runs_dir=tmp_path / "runs", max_concurrent_runs=2, default_budget_usd=1.0,
                claude_path=sys.executable, run_retention_days=90,
                dispatch_free_only=True, dispatch_max_budget_usd=1.0,
                dispatch_route_classes={f"{agent}||{model}": "free"
                    for agent in ("fake", "openclaw")
                    for model in ("m1", "assigned", "swapped-model", "pinned-model", "assigned-model", "openrouter/model:free", "openrouter/assigned:free")})
    base.update(kw)
    return SimpleNamespace(**base)


def _card(sessions, tmp_path, body, column="queued", timeout_s=30, **kw):
    now = int(time.time())
    kw.setdefault("model", "m1")
    with sessions.begin() as s:
        card = Card(title="t", body=body, agent="fake", mode="read", working_dir=str(tmp_path),
                    column=column, position=1.0, timeout_s=timeout_s, needs_approval=False,
                    created_by="operator", created_at=now, updated_at=now, **kw)
        s.add(card)
        s.flush()
        return card.id


async def _drain(d: Dispatcher):
    await d.tick()
    while d._tasks:
        await asyncio.gather(*list(d._tasks.values()), return_exceptions=True)


def _run_for(sessions, card_id):
    with sessions() as s:
        return s.execute(select(Run).where(Run.card_id == card_id)).scalar_one(), s.get(Card, card_id)


SUCCESS = ("import json;print('working');"
           "print(json.dumps({'type':'result','model':'m1','in':12,'out':3,'text':'OK'}))")


def test_success_records_run_and_moves_card_to_done(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, SUCCESS)
    asyncio.run(_drain(d))
    run, card = _run_for(sessions, cid)
    assert run.stage == "succeeded" and card.column == "done"
    assert (run.model_reported, run.input_tokens, run.output_tokens, run.result_text) == ("m1", 12, 3, "OK")
    assert run.exit_code == 0 and run.duration_s is not None
    log = open(run.log_path).read()
    assert "working" in log and "finished" in log
    assert json.loads(run.command) == [sys.executable, "-c", "<prompt>"]

def test_model_mismatch_is_failed_without_losing_usage(sessions,tmp_path):
    cid=_card(sessions,tmp_path,SUCCESS,model='assigned-model')
    with sessions.begin() as s:s.get(Card,cid).agent='openclaw'
    spec=agents.AgentSpec('openclaw','Test OpenClaw','worker','claude_path',_build,FakeParser)
    d=Dispatcher(sessions,_settings(tmp_path),registry={'openclaw':spec})
    asyncio.run(_drain(d));run,card=_run_for(sessions,cid)
    assert run.stage=='failed' and card.column=='failed'
    assert 'different model' in run.error and run.model_requested=='assigned-model'
    assert (run.model_reported,run.input_tokens,run.output_tokens)==('m1',12,3)


def test_failure_exit_code(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, "import sys;print('boom', file=sys.stderr);sys.exit(3)")
    asyncio.run(_drain(d))
    run, card = _run_for(sessions, cid)
    assert run.stage == "failed" and run.exit_code == 3 and card.column == "failed"
    assert "! boom" in open(run.log_path).read()


def test_openclaw_zero_exit_provider_timeout_is_not_success_or_quota_handoff(sessions, tmp_path):
    payload = {'status': 'timeout', 'timeoutPhase': 'provider', 'providerStarted': True,
               'result': {'payloads': [{'text': 'The model did not produce a response before the model idle timeout.'}],
                          'meta': {'agentMeta': {'model': 'model:free', 'provider': 'openrouter',
                                                'usage': {'input': 132156, 'output': 2617}}}}}
    cid = _card(sessions, tmp_path, f'print({json.dumps(payload)!r})', model='openrouter/model:free')
    with sessions.begin() as s:
        s.get(Card, cid).agent = 'openclaw'
    spec = agents.AgentSpec('openclaw', 'Test OpenClaw', 'worker', 'claude_path', _build, agents.OpenClawParser)
    d = Dispatcher(sessions, _settings(tmp_path), registry={'openclaw': spec})
    asyncio.run(_drain(d))
    run, card = _run_for(sessions, cid)
    assert run.stage == 'timeout' and card.column == 'failed' and run.exit_code == 0
    assert 'OpenClaw provider timed out' in run.error and 'idle limit' in run.error
    assert (run.input_tokens, run.output_tokens) == (132156, 2617)
    assert 'idle timeout' in run.result_text
    assert 'quota' not in run.error
    assert asyncio.run(d.tick()) == 0  # no automatic retry/model switch


def test_model_mismatch_takes_precedence_over_provider_timeout(sessions, tmp_path):
    payload = {'status': 'timeout', 'timeoutPhase': 'provider',
               'result': {'meta': {'agentMeta': {'model': 'different:free'}}}}
    cid = _card(sessions, tmp_path, f'print({json.dumps(payload)!r})', model='openrouter/assigned:free')
    with sessions.begin() as s:
        s.get(Card, cid).agent = 'openclaw'
    spec = agents.AgentSpec('openclaw', 'Test OpenClaw', 'worker', 'claude_path', _build, agents.OpenClawParser)
    d = Dispatcher(sessions, _settings(tmp_path), registry={'openclaw': spec})
    asyncio.run(_drain(d))
    run, _ = _run_for(sessions, cid)
    assert run.stage == 'failed' and 'different model' in run.error


def test_openclaw_gateway_timeout_exit_one_without_json(sessions, tmp_path):
    program = "import sys;print('GatewayClientRequestError: FailoverError: LLM request timed out.',file=sys.stderr);sys.exit(1)"
    cid = _card(sessions, tmp_path, program, model='openrouter/model:free')
    with sessions.begin() as s:
        s.get(Card, cid).agent = 'openclaw'
    spec = agents.AgentSpec('openclaw', 'Test OpenClaw', 'worker', 'claude_path', _build, agents.OpenClawParser)
    d = Dispatcher(sessions, _settings(tmp_path), registry={'openclaw': spec})
    asyncio.run(_drain(d))
    run, card = _run_for(sessions, cid)
    assert run.stage == 'timeout' and run.exit_code == 1 and card.column == 'failed'
    assert 'gateway reported an LLM request timeout' in run.error
    assert run.model_reported is None and run.input_tokens is None and run.result_text is None
    assert 'provider timed out' in open(run.log_path).read()
    assert asyncio.run(d.tick()) == 0


def test_timeout_kills_process_group(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, "import time;print('start', flush=True);time.sleep(60)", timeout_s=1)
    t0 = time.time()
    asyncio.run(_drain(d))
    assert time.time() - t0 < 15
    run, card = _run_for(sessions, cid)
    assert run.stage == "timeout" and card.column == "failed"


def test_idle_timeout_quarantines_partial_run(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, "import time;time.sleep(60)", timeout_s=30,
                idle_timeout_s=1)
    asyncio.run(_drain(d))
    run, card = _run_for(sessions, cid)
    assert run.stage == "timeout" and card.column == "failed"
    checkpoint = json.loads(run.checkpoint)
    assert checkpoint["publishable"] is False
    assert (tmp_path / "runs" / "quarantine" / f"run-{run.id}.json").is_file()


def test_cancel(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, "import time;time.sleep(60)")

    async def scenario():
        await d.tick()
        await asyncio.sleep(0.5)
        run_id = next(iter(d._tasks))
        assert await d.cancel(run_id)
        await asyncio.gather(*list(d._tasks.values()), return_exceptions=True)

    asyncio.run(scenario())
    run, card = _run_for(sessions, cid)
    assert run.stage == "cancelled" and card.column == "failed"


def test_cancel_before_runtime_start_is_durable_and_quarantined(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, "import time;time.sleep(60)")

    async def scenario():
        # Claim synchronously, then cancel in the small window before _execute starts.
        claimed = await asyncio.to_thread(d._claim, 1)
        card, run_id = claimed[0]
        assert await d.cancel(run_id)
        await d._execute(card, run_id)
    asyncio.run(scenario())
    run, card = _run_for(sessions, cid)
    assert run.stage == "cancelled" and card.column == "failed"
    assert json.loads(run.checkpoint)["publishable"] is False


def test_retry_is_bounded_and_keeps_partial_runs_quarantined(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path,
                "import sys;print('TRANSIENT_RATE_LIMIT');sys.exit(1)", timeout_s=30,
                max_attempts=2, retry_backoff_s=0)
    asyncio.run(_drain(d))
    with sessions() as s:
        first = s.execute(select(Run).where(Run.card_id == cid)).scalar_one()
        card = s.get(Card, cid)
        assert first.stage == "failed" and card.column == "queued" and card.idempotency_key
    # New dispatcher instance proves the queued retry budget survives process restart.
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    asyncio.run(_drain(d))
    with sessions() as s:
        runs = s.execute(select(Run).where(Run.card_id == cid).order_by(Run.id)).scalars().all()
        card = s.get(Card, cid)
        assert [r.stage for r in runs] == ["failed", "failed"]
        assert [r.attempt for r in runs] == [1, 2]
        assert card.column == "failed" and card.idempotency_key is None
        assert "retry budget exhausted after 2 of 2 attempts" in runs[-1].error
        assert all(json.loads(r.checkpoint)["publishable"] is False for r in runs)


def test_concurrency_limit(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path, max_concurrent_runs=2), registry=_registry())
    for _ in range(3):
        _card(sessions, tmp_path, "import time;time.sleep(1)")

    async def scenario():
        first = await d.tick()
        second = await d.tick()
        await asyncio.gather(*list(d._tasks.values()), return_exceptions=True)
        return first, second

    assert asyncio.run(scenario()) == (2, 0)


def test_unapproved_card_never_runs_even_if_queued(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, SUCCESS)
    with sessions.begin() as s:
        s.execute(update(Card).where(Card.id == cid).values(needs_approval=True, approved_at=None))
    assert asyncio.run(d.tick()) == 0
    # A bare approved_at without a grant is not an approval: refused, audited, back to Review.
    with sessions.begin() as s:
        s.execute(update(Card).where(Card.id == cid).values(approved_at=int(time.time())))
    assert asyncio.run(d.tick()) == 0
    with sessions() as s:
        card = s.get(Card, cid)
        assert (card.column, card.approved_at) == ("review", None)
        assert approval.load_grant(card)["audit"][-1]["event"] == "dispatch_refused"
    with sessions.begin() as s:
        card = s.get(Card, cid)
        approval.grant(card, approval.challenge(card), approval.route_pin(card), int(time.time()), 3600)
        card.column = "queued"
    asyncio.run(_drain(d))
    run, _ = _run_for(sessions, cid)
    assert run.stage == "succeeded"


def test_recover_marks_interrupted(sessions, tmp_path):
    cid = _card(sessions, tmp_path, SUCCESS, column="running")
    with sessions.begin() as s:
        s.add(Run(card_id=cid, agent="fake", stage="running", started_at=int(time.time()) - 5,
                  working_dir=str(tmp_path), command="[]", log_path=str(tmp_path / "x.log")))
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    assert d.recover("restart") == 1
    run, card = _run_for(sessions, cid)
    assert run.stage == "interrupted" and card.column == "failed" and run.error == "restart"


def test_missing_binary_fails_cleanly(sessions, tmp_path):
    def build(card, prompt, model, budget, binary):
        return ["/nonexistent/agent-binary"]
    reg = {"fake": agents.AgentSpec("fake", "Fake", "worker", "claude_path", build, FakeParser)}
    d = Dispatcher(sessions, _settings(tmp_path), registry=reg)
    cid = _card(sessions, tmp_path, "x")
    asyncio.run(_drain(d))
    run, card = _run_for(sessions, cid)
    assert run.stage == "failed" and "could not start" in run.error


def test_prune_deletes_old_runs_and_logs(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path, run_retention_days=1), registry=_registry())
    cid = _card(sessions, tmp_path, SUCCESS)
    asyncio.run(_drain(d))
    run, _ = _run_for(sessions, cid)
    with sessions.begin() as s:
        s.execute(update(Run).where(Run.id == run.id).values(started_at=int(time.time()) - 3 * 86400))
    assert d.prune(int(time.time())) == 1
    import os
    assert not os.path.exists(run.log_path)


def test_log_tail_endpoint(make_client, tmp_path):
    client = make_client()
    sessions = client.app.state.sessions
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, SUCCESS)
    asyncio.run(_drain(d))
    run, _ = _run_for(sessions, cid)
    first = client.get(f"/api/runs/{run.id}/log").json()
    assert "working" in first["text"] and first["done"] is True
    again = client.get(f"/api/runs/{run.id}/log?offset={first['next_offset']}").json()
    assert again["text"] == ""


def test_deleting_card_removes_run_logs(make_client, tmp_path):
    import os
    client = make_client()
    sessions = client.app.state.sessions
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, SUCCESS, column="queued")
    asyncio.run(_drain(d))
    run, _ = _run_for(sessions, cid)
    assert os.path.exists(run.log_path)
    assert client.delete(f"/api/cards/{cid}").status_code == 204
    assert not os.path.exists(run.log_path)
    assert not os.path.exists(run.log_path.replace(".log", ".raw.log"))
    with sessions() as s:
        assert s.execute(select(Run).where(Run.card_id == cid)).first() is None
