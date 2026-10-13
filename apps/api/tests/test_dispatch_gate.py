"""SEC-013 synthetic admission and real short-lived runner checks; no providers."""
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from agents import AgentSpec, Parser
from dispatch_gate import DispatchDenied, admit
from dispatcher import Dispatcher, _reviewed_route_class
from models import (BillingConfig, Card, ChatMessage, ChatThread, Project,
                    ProjectTask, Run, RunEvent)

AGENTS = ('claude', 'codex', 'grok', 'hermes', 'openclaw')
FLAGS = dict(claude='--model', codex='-m', grok='--model', hermes='-m', openclaw='--model')


def settings(tmp_path, agent, price_class=None, **kw):
    values = dict(runs_dir=tmp_path/'runs', max_concurrent_runs=2, default_budget_usd=0.0,
                  claude_path=sys.executable, run_retention_days=90,
                  dispatch_free_only=True, dispatch_max_budget_usd=1.0,
                  dispatch_route_classes={f'{agent}||assigned': price_class} if price_class else {})
    values.update(kw)
    return SimpleNamespace(**values)


def row(agent, cap=0.0, target='', price_class='free'):
    return SimpleNamespace(agent=agent, model_requested='assigned',
                           checkpoint=json.dumps({'dispatch_policy': {'target': target, 'budget_usd': cap, 'price_class': price_class}}))


@pytest.mark.parametrize('agent', AGENTS)
@pytest.mark.parametrize('price_class,free_only,cap,expected', [
    (None, False, 1, 'PRICE_UNKNOWN'), ('paid', True, 1, 'FREE_ONLY'),
    ('subscription', True, 0, 'FREE_ONLY'), ('free', True, -1, 'BUDGET_EXCEEDED'),
    ('free', True, float('nan'), 'BUDGET_EXCEEDED'),
    ('free', True, float('inf'), 'BUDGET_EXCEEDED'),
    ('free', True, None, 'BUDGET_EXCEEDED'), ('free', True, True, 'BUDGET_EXCEEDED'),
    ('free', True, 2, 'BUDGET_EXCEEDED'), ('paid', False, 0, 'BUDGET_EXCEEDED'),
])
def test_fail_closed(tmp_path, agent, price_class, free_only, cap, expected):
    cfg = settings(tmp_path, agent, price_class, dispatch_free_only=free_only)
    with pytest.raises(DispatchDenied, match=expected):
        admit(cfg, row(agent, cap, price_class=price_class), ['runner', FLAGS[agent], 'assigned'])


@pytest.mark.parametrize('agent', AGENTS)
def test_exact_route_and_pin(tmp_path, agent):
    cfg = settings(tmp_path, agent, 'free')
    argv = ['runner', FLAGS[agent], 'assigned']
    assert admit(cfg, row(agent), argv)['price_class'] == 'free'
    with pytest.raises(DispatchDenied, match='PRICE_UNKNOWN'):
        admit(cfg, row(agent, target='other'), argv)
    with pytest.raises(DispatchDenied, match='ROUTE_UNPINNED'):
        admit(cfg, row(agent), ['runner'])
    with pytest.raises(DispatchDenied, match='ROUTE_UNPINNED'):
        admit(cfg, row(agent), ['runner', FLAGS[agent], 'changed'])


@pytest.mark.parametrize('agent', AGENTS)
def test_paid_requires_runtime_boundary(tmp_path, agent):
    cfg = settings(tmp_path, agent, 'paid', dispatch_free_only=False)
    argv = ['runner', FLAGS[agent], 'assigned', '--max-budget-usd', '1']
    if agent == 'claude':
        assert admit(cfg, row(agent, 1, price_class='paid'), argv)['budget_usd'] == 1
        with pytest.raises(DispatchDenied, match='BUDGET_UNENFORCED'):
            admit(cfg, row(agent, .5, price_class='paid'), argv)
    else:
        with pytest.raises(DispatchDenied, match='BUDGET_UNENFORCED'):
            admit(cfg, row(agent, 1, price_class='paid'), argv)


@pytest.mark.parametrize('agent', AGENTS)
@pytest.mark.parametrize('chat', [False, True])
@pytest.mark.parametrize('price_class,free_only,cap,expected', [
    (None, False, 0, 'PRICE_UNKNOWN'), ('paid', True, 1, 'FREE_ONLY'),
    ('subscription', True, 0, 'FREE_ONLY'), ('free', True, 2, 'BUDGET_EXCEEDED'),
    ('paid', False, 1, 'BUDGET_UNENFORCED'), ('free', True, 0, None),
])
def test_launch_boundary(sessions, tmp_path, agent, chat, price_class, free_only, cap, expected):
    allowed = expected is None
    marker = tmp_path/'spawned'
    program = f'from pathlib import Path; Path({str(marker)!r}).write_text("synthetic")'
    def build(card, prompt, model, budget, binary, session_id=None):
        return [sys.executable, '-c', program, FLAGS[agent], model]
    registry = {agent: AgentSpec(agent, agent, 'worker', 'claude_path', build, Parser)}
    cfg = settings(tmp_path, agent, price_class, dispatch_free_only=free_only, default_budget_usd=cap)
    d = Dispatcher(sessions, cfg, registry=registry)
    with sessions.begin() as db:
        # Exercise exact API-route admission here. Subscription-account fallback
        # has its own tests below and must not turn this unknown-route case into
        # a reviewed native subscription.
        db.add(BillingConfig(id=1, payload=json.dumps({
            'accounts': {agent: {'mode': 'api', 'monthly_usd': 0}}
        })))
        if chat:
            thread = ChatThread(agent=agent, model='assigned', title='synthetic', mode='read',
                                working_dir=str(tmp_path), created_at=1, last_activity_at=1)
            db.add(thread); db.flush()
            obj = ChatMessage(thread_id=thread.id, role='user', text='synthetic',
                              status='pending_approval', created_at=1)
        else:
            obj = Card(agent=agent, model='assigned', title='synthetic', body='synthetic',
                       mode='read', working_dir=str(tmp_path), column='queued', position=1,
                       timeout_s=30, budget_usd=cap, needs_approval=False,
                       created_by='test', created_at=1, updated_at=1)
        db.add(obj); db.flush(); oid = obj.id
    async def run():
        if chat:
            await d.start_turn(oid)
            await asyncio.gather(*list(d._chat_tasks.values()))
        else:
            await d.tick()
            await asyncio.gather(*list(d._tasks.values()))
    asyncio.run(run())
    assert marker.exists() == allowed
    with sessions() as db:
        run = db.scalar(select(Run))
        notes = list(db.scalars(select(RunEvent.text).where(RunEvent.run_id == run.id)))
        assert any(('dispatch admitted' if allowed else 'dispatch denied') in n for n in notes)
        if not allowed:
            assert run.stage == 'failed' and expected in run.error
            assert run.pid is None


def test_rcd_default_is_free_only():
    from settings import Settings
    # Field defaults are independent of local dotenv/environment.
    from pathlib import Path
    import json
    product = json.loads((Path(__file__).resolve().parents[3] / 'packaging/product.json').read_text())
    rcd = product['product'] == 'rcd'
    assert Settings.model_fields['dispatch_free_only'].default == rcd
    assert Settings.model_fields['default_budget_usd'].default == (0.0 if rcd else 1.0)


@pytest.mark.parametrize('agent', ('claude', 'codex'))
def test_subscription_account_is_a_reviewed_route(sessions, tmp_path, agent):
    cfg = settings(tmp_path, agent, dispatch_free_only=False)
    with sessions.begin() as db:
        db.add(BillingConfig(id=1, payload=json.dumps({
            'accounts': {agent: {'mode': 'subscription', 'monthly_usd': 20}}
        })))
    with sessions() as db:
        price_class = _reviewed_route_class(db, cfg, row(agent), 'assigned')
    policy = row(agent)
    policy.checkpoint = json.dumps({'dispatch_policy': {
        'target': '', 'budget_usd': 0, 'price_class': price_class}})
    evidence = admit(cfg, policy, ['runner', FLAGS[agent], 'assigned'], current_price_class=price_class)
    assert evidence['price_class'] == 'subscription'


@pytest.mark.parametrize('agent', ('hermes', 'openclaw'))
def test_api_account_without_exact_route_stays_unknown(sessions, tmp_path, agent):
    cfg = settings(tmp_path, agent, dispatch_free_only=False)
    with sessions() as db:
        assert _reviewed_route_class(db, cfg, row(agent), 'assigned') is None


def test_approved_project_openclaw_free_route_is_reviewed(sessions, tmp_path):
    model = 'openrouter/thinkingmachines/inkling:free'
    with sessions.begin() as db:
        card = Card(agent='openclaw', agent_target='mm-main', model=model,
                    title='bounded story', body='bounded story', mode='read',
                    working_dir=str(tmp_path), column='queued', position=1,
                    timeout_s=30, budget_usd=0, needs_approval=False,
                    created_by='test', created_at=1, updated_at=1)
        db.add(card); db.flush()
        manifest = {'document': {'nodes': [{
            'key': 'story', 'kind': 'story', 'assignee': 'openclaw',
            'model': model, 'agent_target': 'mm-main',
        }]}}
        project = Project(document='{}', revision=1, state='active',
                          approved_manifest=json.dumps(manifest), created_by='test',
                          created_at=1, updated_at=1)
        db.add(project); db.flush()
        db.add(ProjectTask(card_id=card.id, project_id=project.id, revision=1,
                           node_key='story', role='story'))
        card_id = card.id
    cfg = settings(tmp_path, 'openclaw', dispatch_free_only=False)
    with sessions() as db:
        card = db.get(Card, card_id)
        assert _reviewed_route_class(db, cfg, card, model) == 'free'
        assert _reviewed_route_class(db, cfg, card, 'openrouter/other:free') is None
        card.agent_target = 'different-target'
        assert _reviewed_route_class(db, cfg, card, model) is None


@pytest.mark.parametrize('agent', AGENTS)
def test_default_billing_is_not_reviewed(sessions, tmp_path, agent):
    with sessions() as db:
        assert _reviewed_route_class(db, settings(tmp_path, agent), row(agent), 'assigned') is None


@pytest.mark.parametrize('agent', AGENTS)
def test_revoked_class_and_missing_snapshot_fail_closed(tmp_path, agent):
    cfg = settings(tmp_path, agent, 'paid', dispatch_free_only=False)
    with pytest.raises(DispatchDenied, match='PRICE_UNKNOWN'):
        admit(cfg, row(agent), ['runner', FLAGS[agent], 'assigned'])
    old = row(agent)
    old.checkpoint = json.dumps({'dispatch_policy': {'target': '', 'budget_usd': 0}})
    with pytest.raises(DispatchDenied, match='PRICE_UNKNOWN'):
        admit(settings(tmp_path, agent, 'free'), old, ['runner', FLAGS[agent], 'assigned'])


@pytest.mark.parametrize('agent', AGENTS)
@pytest.mark.parametrize('chat', [False, True])
def test_revocation_between_claim_and_launch(sessions, tmp_path, agent, chat):
    cfg = settings(tmp_path, agent, 'free')
    marker = tmp_path / 'spawned'
    def build(card, prompt, model, budget, binary, session_id=None):
        return [sys.executable, '-c', f'open({str(marker)!r}, "w").close()', FLAGS[agent], model]
    d = Dispatcher(sessions, cfg, registry={agent: AgentSpec(agent, agent, 'worker', 'claude_path', build, Parser)})
    with sessions.begin() as db:
        if chat:
            thread = ChatThread(agent=agent, model='assigned', title='t', mode='read', working_dir=str(tmp_path), created_at=1, last_activity_at=1)
            db.add(thread); db.flush()
            obj = ChatMessage(thread_id=thread.id, role='user', text='t', status='pending_approval', created_at=1)
        else:
            obj = Card(agent=agent, model='assigned', title='t', body='t', mode='read', working_dir=str(tmp_path), column='queued', position=1, timeout_s=30, budget_usd=0, needs_approval=False, created_by='test', created_at=1, updated_at=1)
        db.add(obj); db.flush(); oid = obj.id
    claimed = d._claim_turn(oid) if chat else d._claim(1)[0]
    cfg.dispatch_route_classes.clear()
    from dispatcher import _Handle
    payload, rid = claimed
    d._handles[rid] = _Handle()
    asyncio.run(d._execute_turn(payload, rid) if chat else d._execute(payload, rid))
    assert not marker.exists()
    with sessions() as db:
        run = db.get(Run, rid)
        assert run.stage == 'failed' and 'PRICE_UNKNOWN' in run.error and run.pid is None


@pytest.mark.parametrize('checkpoint', ['null', '[]', '{}', '{"dispatch_policy": []}', 'bad-json'])
def test_malformed_policy_denied(tmp_path, checkpoint):
    run = row('claude')
    run.checkpoint = checkpoint
    with pytest.raises(DispatchDenied):
        admit(settings(tmp_path, 'claude', 'free'), run, ['runner', '--model', 'assigned'])


def test_extreme_budget_denied(tmp_path):
    with pytest.raises(DispatchDenied, match='BUDGET_EXCEEDED'):
        admit(settings(tmp_path, 'claude', 'free'), row('claude', 10**400), ['runner', '--model', 'assigned'])
