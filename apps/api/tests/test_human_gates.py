"""Backend acceptance with a durable synthetic runner; no provider or Pi claim."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from adapter_contract import AdapterError, error
from agents import AgentSpec, Parser
from dispatcher import Dispatcher
from models import Card, Run
from routes.tasks import _run_dict
from tests.test_dispatcher import _card, _settings


class CheckpointAdapter:
    """Test-only completed-tool journal. Each segment is a fresh short-lived process."""
    name = "fake"

    def __init__(self, path, live=False, crash_after_resume=False):
        self.path, self.live, self.crash_after_resume = path, live, crash_after_resume
        self.starts = 0

    def read(self):
        return json.loads(self.path.read_text())

    def write(self, state):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(state)); temp.replace(self.path)

    def capabilities(self):
        return {"suspend_modes": ["live" if self.live else "checkpoint"]}

    def segment(self, state, step):
        # A real process executes the tool once, guarded by the durable journal.
        self.write(state)
        code = """import json,sys
from pathlib import Path
p=Path(sys.argv[1]); s=json.loads(p.read_text());step=sys.argv[2]
if step not in s['tools']:
 s['tools'][step]={'count':1,'tokens':12 if step=='before' else 5}
t=p.with_suffix('.tmp');t.write_text(json.dumps(s));t.replace(p)
"""
        proc = subprocess.run([sys.executable, '-c', code, str(self.path), step], check=True)
        assert proc.returncode == 0
        return self.read()

    async def start(self, spec):
        self.starts += 1
        state = self.segment({"spec": spec, "status": "running", "tools": {}, "decisions": {}}, 'before')
        state['status'] = 'awaiting_approval'; self.write(state)
        return {"run_id": spec['run_id'], "status": state['status'], "replayed": False}

    async def events(self, run_id, after_seq=0):
        if False:
            yield {}

    async def result(self, run_id):
        s = self.read(); tokens = sum(t['tokens'] for t in s['tools'].values())
        return {"status": s['status'], "model": {"reported": "assigned", "provider": "synthetic"},
                "usage": {"input_tokens": tokens, "output_tokens": 1}, "cost": {"usd": 0.0},
                "result_text": 'synthetic result', "exit_code": 0, "duration_s": 0.1,
                "session": {}, "error": error('DECISION_REJECTED', 'Human rejected the decision')
                    if s['status'] == 'cancelled' else None,
                "approval": {"approval_id": 'gate-1', "kind": 'human_decision',
                    "question": 'Continue with the prepared operation?', "resume_mode": 'live' if self.live else 'checkpoint',
                    "requested_at": 1, "checkpoint": {"state_ref": str(self.path)}}}

    async def heartbeat(self, run_id):
        return {"alive": self.live, "pid": 999 if self.live else None}

    async def resume(self, decision):
        state = self.read(); old = state['decisions'].get(decision['approval_id'])
        if old:
            assert old == decision
        else:
            state['decisions'][decision['approval_id']] = decision
            if decision['verdict'] == 'reject':
                state['status'] = 'cancelled'
            else:
                state = self.segment(state, 'after')
                state['status'] = 'succeeded'
            self.write(state)
            if self.crash_after_resume:
                raise RuntimeError('simulated API death after adapter committed decision')
        return {"run_id": decision['run_id'], "status": 'cancelled' if decision['verdict']=='reject' else 'running', "replayed": bool(old)}

    async def cancel(self, request):
        state=self.read();state['status']='cancelled';self.write(state)
        self.live=False
        return {"run_id":request['run_id'],"status":"cancelled","replayed":False}

    async def recover(self):
        return [] if not self.path.exists() else [{"run_id": self.read()['spec']['run_id'],
            "outcome": 'awaiting_approval' if self.read()['status']=='awaiting_approval' else 'finished_while_down'}]


def setup(sessions, tmp_path, adapter=None):
    adapter = adapter or CheckpointAdapter(tmp_path/'adapter.json')
    registry = {'fake': AgentSpec('fake','Synthetic','worker','claude_path',lambda *a:['never-launched'],Parser)}
    d = Dispatcher(sessions, _settings(tmp_path), registry=registry, adapters={'fake':adapter})
    return d, adapter


async def drain(d):
    while d._tasks:
        await asyncio.gather(*list(d._tasks.values()))
        await asyncio.sleep(0)


def row(sessions, cid):
    with sessions() as db:
        return db.scalar(select(Run).where(Run.card_id==cid)), db.get(Card,cid)


def decision(rid, verdict='approve', **kw):
    return dict(schema_version='rcd.adapter.v1',run_id=str(rid),approval_id='gate-1',
                decision_id='operator-1',verdict=verdict,actor='operator',decided_at=2, **kw)


@pytest.mark.parametrize('restart', [False,True])
def test_checkpoint_approval_preserves_completed_steps_tokens_and_key(sessions,tmp_path,restart):
    d,a=setup(sessions,tmp_path);cid=_card(sessions,tmp_path,'assigned prompt',model='assigned')
    async def run():
        nonlocal d,a
        await d.tick(); await drain(d)
        r,c=row(sessions,cid);key=r.idempotency_key
        assert (r.stage,c.column,r.ended_at,r.pid)==('awaiting_approval','review',None,None)
        assert r.input_tokens==12 and not d._handles
        assert _run_dict(r)['approval']['question'].startswith('Continue')
        before=a.read()['tools']['before'].copy()
        assert await d.tick()==0
        if restart:
            d,a=setup(sessions,tmp_path)
            await d.tick()
            assert row(sessions,cid)[0].stage=='awaiting_approval'
        await d.decide(r.id,decision(r.id, 'answer',answer_text='Proceed with option A'))
        await drain(d)
        final,card=row(sessions,cid)
        assert (final.id, final.idempotency_key, final.attempt)==(r.id,key,1)
        assert (final.stage,card.column)==('succeeded','done')
        assert a.read()['tools']['before']==before=={'count':1,'tokens':12}
        assert a.read()['tools']['after']=={'count':1,'tokens':5}
        assert final.input_tokens==17 and a.starts==(0 if restart else 1)
        assert (await d.decide(r.id,decision(r.id,'answer',answer_text='Proceed with option A')))['replayed']
        with pytest.raises(AdapterError,match='different decision'):
            await d.decide(r.id,decision(r.id,'reject'))
        with sessions() as db:
            assert len(list(db.scalars(select(Run))))==1
    asyncio.run(run())


def test_reject_cancels_story_without_post_checkpoint_work(sessions,tmp_path):
    d,a=setup(sessions,tmp_path);cid=_card(sessions,tmp_path,'prompt')
    async def run():
        await d.tick();await drain(d);r,_=row(sessions,cid)
        await d.decide(r.id,decision(r.id,'reject'));await drain(d)
        final,c=row(sessions,cid)
        assert (final.stage,c.column)==('cancelled','failed')
        assert final.error=='Human rejected the decision'
        assert a.read()['tools']=={'before':{'count':1,'tokens':12}}
        assert final.idempotency_key==r.idempotency_key and c.idempotency_key is None
    asyncio.run(run())


def test_restart_replays_committed_decision_after_crash_without_tool_replay(sessions,tmp_path):
    a=CheckpointAdapter(tmp_path/'adapter.json',crash_after_resume=True);d,_=setup(sessions,tmp_path,a)
    cid=_card(sessions,tmp_path,'prompt')
    async def run():
        await d.tick();await drain(d);r,_=row(sessions,cid)
        with pytest.raises(RuntimeError,match='API death'):
            await d.decide(r.id,decision(r.id))
        cp=json.loads(row(sessions,cid)[0].checkpoint)
        assert cp['pending_decision']==decision(r.id)
        replacement,restored=setup(sessions,tmp_path)
        await replacement.tick();await drain(replacement)
        assert row(sessions,cid)[0].stage=='succeeded'
        assert restored.starts==0
        assert restored.read()['tools']=={'before':{'count':1,'tokens':12},'after':{'count':1,'tokens':5}}
    asyncio.run(run())


def test_live_approval_is_cancelled_and_refused(sessions,tmp_path):
    a=CheckpointAdapter(tmp_path/'adapter.json',live=True);d,_=setup(sessions,tmp_path,a)
    cid=_card(sessions,tmp_path,'prompt')
    async def run():
        await d.tick();await drain(d)
        r,c=row(sessions,cid)
        assert r.stage=='failed' and c.column=='failed'
        assert r.error.startswith('RUNTIME_INCOMPATIBLE')
        assert a.read()['status']=='cancelled'
    asyncio.run(run())


def test_stale_approval_and_output_hash_fail_before_resume(sessions,tmp_path):
    from approval import validate_decision
    with pytest.raises(AdapterError):
        validate_decision({'approval_id':'new'},decision(1))
    with pytest.raises(AdapterError):
        validate_decision({'approval_id':'gate-1','proposed_output':{'sha256':'a'*64}},decision(1))


def test_waiting_gate_is_not_pruned(sessions,tmp_path):
    d,a=setup(sessions,tmp_path);cid=_card(sessions,tmp_path,'prompt')
    async def run():
        await d.tick();await drain(d)
        assert d.prune(10**10)==0
        assert row(sessions,cid)[0].stage=='awaiting_approval'
    asyncio.run(run())


def test_tasks_api_decision_survives_app_lifespan_restart(make_client,tmp_path):
    # Two separate ASGI app instances share only durable SQLite and runner files.
    with make_client(built=False) as client:
        sessions=client.app.state.sessions
        d,a=setup(sessions,tmp_path)
        client.app.state.dispatcher=d
        cid=_card(sessions,tmp_path,'prompt')
        client.portal.call(d.tick);client.portal.call(drain,d)
        payload=client.get(f'/api/cards/{cid}').json()
        rid=payload['last_run']['id'];key=row(sessions,cid)[0].idempotency_key
        assert payload['last_run']['approval']['approval_id']=='gate-1'
        assert client.patch(f'/api/cards/{cid}',json={'column':'queued'}).status_code==409
        assert client.post(f'/api/cards/{cid}/approve',json={}).status_code==409
        assert client.delete(f'/api/cards/{cid}').status_code==409
    with make_client(built=False) as restarted:
        sessions=restarted.app.state.sessions
        d,a=setup(sessions,tmp_path)
        restarted.app.state.dispatcher=d
        nonce=restarted.get(f'/api/cards/{cid}').json()['last_run']['approval']['nonce']
        assert nonce==payload['last_run']['approval']['nonce']  # the pause nonce survives restart
        body={'approval_id':'gate-1','decision_id':'api-decision-1','verdict':'approve','approval_nonce':nonce}
        assert restarted.post(f'/api/runs/{rid}/decision',json={**body,'approval_id':'stale'}).status_code==409
        assert restarted.post(f'/api/runs/{rid}/decision',json={**body,'model':'unapproved'}).status_code==422
        response=restarted.post(f'/api/runs/{rid}/decision',json=body)
        assert response.status_code==200,response.text
        restarted.portal.call(drain,d)
        # The nonce is spent: an exact replay is refused and audited, and nothing resumes again.
        assert restarted.post(f'/api/runs/{rid}/decision',json=body).status_code==409
        final=restarted.get(f'/api/cards/{cid}').json()
        assert final['last_run']['stage']=='succeeded'
        assert final['last_run']['id']==rid
        assert row(sessions,cid)[0].idempotency_key==key
        assert a.starts==0 and a.read()['tools']['before']=={'count':1,'tokens':12}


class RefusingAdapter(CheckpointAdapter):
    """Resume admission fails, as when a route is no longer approved after the pause."""
    async def resume(self, decision):
        raise AdapterError('MODEL_NOT_ALLOWED', 'Run route is no longer approved')


def test_unapplicable_pending_decision_fails_closed_without_stalling_dispatch(sessions,tmp_path):
    d,a=setup(sessions,tmp_path);cid=_card(sessions,tmp_path,'prompt')
    async def run():
        await d.tick();await drain(d);r,_=row(sessions,cid)
        # The decision is committed, then the API dies before the adapter acknowledges it.
        a.resume=lambda decision:(_ for _ in ()).throw(RuntimeError('API death before resume'))
        with pytest.raises(RuntimeError):
            await d.decide(r.id,decision(r.id))
        later=_card(sessions,tmp_path,'later prompt')
        replacement,restored=setup(sessions,tmp_path,RefusingAdapter(tmp_path/'adapter.json'))
        assert await replacement.tick()==1  # does not raise; the other story still dispatches
        final,card=row(sessions,cid)
        assert (final.stage,card.column)==('failed','failed')
        assert final.error.startswith('MODEL_NOT_ALLOWED')
        assert final.input_tokens==12 and card.idempotency_key is None
        cp=json.loads(final.checkpoint)
        assert 'pending_decision' not in cp and cp['unapplied_decision']['decision_id']=='operator-1'
        await drain(replacement)
        assert restored.starts==1  # only the later story; the failed run never restarts
        with pytest.raises(AdapterError,match='already has a different decision|not waiting'):
            await replacement.decide(r.id,decision(r.id,'reject'))
        assert row(sessions,later)[0] is not None
    asyncio.run(run())


def test_crash_before_database_pause_recovers_adapter_checkpoint(sessions,tmp_path):
    d,a=setup(sessions,tmp_path);cid=_card(sessions,tmp_path,'prompt')
    claims=d._claim(1);spec=claims[0][0]['adapter_spec'];rid=claims[0][1]
    asyncio.run(a.start(spec))  # API dies before consuming its awaiting_approval result
    replacement,restored=setup(sessions,tmp_path)
    async def run():
        await replacement.tick();await drain(replacement)
        assert row(sessions,cid)[0].stage=='awaiting_approval'
        assert restored.starts==0
        await replacement.decide(rid,decision(rid));await drain(replacement)
        assert row(sessions,cid)[0].stage=='succeeded'
        assert restored.read()['tools']['before']['count']==1
    asyncio.run(run())
