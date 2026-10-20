"""Recovery conformance using temporary state and synthetic runs; no providers are invoked."""
import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from models import Card, Project, ProjectTask, Run
from settings import get_settings
from agents import AgentSpec
import profiles
import projects
import route_reliability as recovery


@pytest.fixture
def app(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(AgentSpec, 'available', lambda self, settings: True)
    client = make_client()
    cfg = tmp_path / 'hermes.yaml'
    cfg.write_text('model:\n  default: openrouter/free\nfallback_model:\n  - model: vendor/small:free\n')
    settings = get_settings()
    settings.hermes_config_path = cfg
    settings.dispatch_free_only = False
    monkeypatch.setattr(projects, 'delegator_route', lambda settings, action=None: {'agent':'hermes', 'model':'openrouter/free'})
    with client:
        assert client.patch('/api/billing',json={'accounts':{'claude':{'mode':'subscription','monthly_usd':20},'codex':{'mode':'subscription','monthly_usd':20}}}).status_code==200
        yield client, client.app.state.sessions, settings, tmp_path / 'ws/proj'


def run(s, card, *, stage='succeeded', result='not JSON', error=None, model=None):
    row = Run(card_id=card.id, agent=card.agent, model_requested=model or card.model, stage=stage,
        started_at=int(time.time()), ended_at=int(time.time()), working_dir=card.working_dir,
        command='[]', log_path='', result_text=result, error=error)
    s.add(row); s.flush()
    card.column = 'done' if stage == 'succeeded' else 'failed'
    return row


def project(client, workspace):
    result = client.post('/api/projects', json={'title':'Synthetic recovery', 'brief':'Inspect one local file.',
        'constraints':'No writes.', 'working_dir':str(workspace), 'planner_agent':'hermes', 'planner_model':'openrouter/free'})
    assert result.status_code == 201, result.text
    return result.json()


def test_opt_in_route_policy_does_not_make_paid_routes_or_host_limits_implicit(app):
    c, sessions, settings, _ = app
    settings.dispatch_free_only = True
    options = c.get('/api/profile/route-reliability').json()
    sub = next(r for r in options['options'] if r['agent'] == 'claude')
    assert not sub['allowed']
    assert c.patch('/api/billing',json={'limits':{'allow_subscription_in_free_only':True}}).status_code == 200
    assert c.get('/api/profile/route-reliability').json()['subscription_allowed']
    assert c.put('/api/profile/route-reliability',json={'enabled':True,'routes':[{'agent':'claude','model':sub['model']}]}).status_code == 200
    with sessions() as s:
        assert recovery.eligible(s,settings,'operator') == [{'agent':'claude','model':sub['model']}]
        assert not recovery.allowed_class(s,settings,'paid')
    assert c.put('/api/profile/route-reliability',json={'enabled':True,'routes':[{'agent':'claude','model':'made-up-model'}]}).status_code == 422


def test_contract_repair_is_bounded_and_reuses_the_same_task(app):
    c, sessions, settings, workspace = app
    assert c.put('/api/profile/route-reliability',json={'enabled':True,'routes':[{'agent':'claude','model':'claude-haiku-5-5'}]}).status_code == 200
    p = project(c,workspace)
    assert c.post(f"/api/projects/{p['id']}/plan",json={'revision':1,'approve_coordination':True}).status_code == 200
    with sessions() as s:
        p = s.get(Project,p['id']); pipe = json.loads(p.pipeline); card = s.get(Card,pipe['card_id'])
        original = card.id
        first = run(s,card)
        projects.advance(s,settings);s.commit()
        assert first.stage=='failed' and first.error.startswith('OUTPUT_INVALID:')
        assert card.id == original and card.column == 'queued'
        assert 'OUTPUT REPAIR (one attempt)' in card.body
        assert json.loads(p.pipeline)['contract_repairs'] == {'coordinate':1}
        run(s,card)
        projects.advance(s,settings);s.commit()
        assert card.id == original and card.agent == 'claude'
        assert len(list(s.scalars(select(ProjectTask).where(ProjectTask.project_id==p.id)))) == 1
        assert s.scalar(select(Run.id).where(Run.id==first.id))
        # Neither a format repair nor a model fallback can create execution stories.
        assert not list(s.scalars(select(ProjectTask).where(ProjectTask.project_id==p.id,ProjectTask.role=='story')))


def test_telemetry_counts_invalid_outputs_without_returning_private_error_text(app):
    c, sessions, settings, workspace = app
    p = project(c,workspace)
    with sessions() as s:
        p = s.get(Project,p['id'])
        card = projects._queue(s,p,'plan','hermes','openrouter/free','Return JSON',settings)
        s.flush()
        for _ in range(3):
            item = run(s,card,result='PRIVATE PROJECT TEXT',error='PRIVATE ERROR')
            recovery.contract_failure(s,item)
        s.commit()
    data = c.get('/api/profile/route-reliability').json()
    assert data['health'][0]['persistent']
    assert data['health'][0]['categories']['invalid_output'] == 3
    assert data['recommendations'][0]['link'] == '/profile#route-recovery'
    assert 'PRIVATE' not in json.dumps(data)


def test_route_health_deprioritizes_a_persistently_failing_free_model(app):
    c, sessions, settings, workspace = app
    routes = [{'agent':'hermes','model':'openrouter/free'},{'agent':'claude','model':'claude-haiku-5-5'}]
    assert c.put('/api/profile/route-reliability',json={'enabled':True,'routes':routes}).status_code == 200
    p = project(c,workspace)
    with sessions() as s:
        p=s.get(Project,p['id']);card=projects._queue(s,p,'plan','hermes','openrouter/free','Return JSON',settings)
        s.flush()
        for _ in range(3): run(s,card,stage='failed',error='429 rate limit')
        s.commit()
        assert recovery.eligible(s,settings,'operator')[0] == routes[1]


def test_new_membership_retry_keeps_project_and_completed_steps(app):
    c,sessions,settings,workspace=app
    p=project(c,workspace)
    assert c.post(f"/api/projects/{p['id']}/plan",json={'revision':1,'approve_coordination':True}).status_code == 200
    with sessions() as s:
        row=s.get(Project,p['id']);pipe=json.loads(row.pipeline);card=s.get(Card,pipe['card_id'])
        item=run(s,card,stage='failed',error='provider unavailable')
        row.state='planning_failed';s.commit();card_id=card.id;run_id=item.id
    result=c.post(f"/api/projects/{p['id']}/planning-tasks/{card_id}/retry",json={'revision':1,'route':{'agent':'claude','model':'claude-haiku-5-5'}})
    assert result.status_code == 200,result.text
    data=result.json();assert data['pipeline']['card_id']==card_id
    assert data['tasks'][0]['run_id']==run_id and len(data['tasks'])==1
    assert data['document']['brief']=='Inspect one local file.'


def test_free_alias_cannot_create_an_endless_automatic_retry(app):
    c,sessions,settings,workspace=app
    settings.hermes_config_path.write_text('model:\n  default: vendor/small:free\n')
    p=project(c,workspace)
    c.post(f"/api/projects/{p['id']}/plan",json={'revision':1,'approve_coordination':True})
    with sessions() as s:
        row=s.get(Project,p['id']);card=s.get(Card,json.loads(row.pipeline)['card_id'])
        run(s,card,stage='failed',error='provider unavailable')
        projects.advance(s,settings);s.commit()
        assert row.state=='planning_failed'
        cid=card.id
    result=c.post(f"/api/projects/{p['id']}/plan",json={'revision':1,'approve_coordination':True})
    assert result.status_code==200,result.text
    assert result.json()['pipeline']['card_id']==cid and len(result.json()['tasks'])==1


def test_paid_planning_retry_needs_explicit_approval(app):
    c,sessions,settings,workspace=app
    settings.hermes_config_path.write_text(settings.hermes_config_path.read_text()+'  - model: vendor/paid\n')
    settings.dispatch_route_classes={'hermes||vendor/paid':'paid'}
    settings.dispatch_free_only=True
    p=project(c,workspace)
    c.post(f"/api/projects/{p['id']}/plan",json={'revision':1,'approve_coordination':True})
    with sessions() as s:
        row=s.get(Project,p['id']);card=s.get(Card,json.loads(row.pipeline)['card_id'])
        run(s,card,stage='failed',error='provider unavailable');row.state='planning_failed';s.commit();cid=card.id
    route={'agent':'hermes','model':'vendor/paid'}
    body={'revision':1,'route':route}
    assert c.post(f"/api/projects/{p['id']}/planning-tasks/{cid}/retry",json=body).status_code==422
    assert c.patch('/api/billing',json={'limits':{'allow_paid_in_free_only':True}}).status_code==200
    # Enabling paid routes lifts the price-class restriction; it does not approve a run.
    assert c.post(f"/api/projects/{p['id']}/planning-tasks/{cid}/retry",json=body).status_code==422
    result=c.post(f"/api/projects/{p['id']}/planning-tasks/{cid}/retry",json={**body,'approve_api_planning':True})
    assert result.status_code==200,result.text
    assert result.json()['pipeline']['api_planning_approved']


@pytest.mark.parametrize('price,flag',[('paid','allow_paid_in_free_only'),('subscription','allow_subscription_in_free_only')])
def test_dispatch_rechecks_each_explicit_billing_opt_in(app,price,flag):
    c,sessions,settings,_=app
    from dispatch_gate import admit,DispatchDenied,snapshot
    import billing
    settings.dispatch_free_only=True
    item=SimpleNamespace(agent='hermes',model_requested='synthetic/model',checkpoint=json.dumps({'dispatch_policy':snapshot(SimpleNamespace(agent_target=''),0,price)}))
    argv=['hermes','-m','synthetic/model']
    with sessions() as s:
        with pytest.raises(DispatchDenied,match='FREE_ONLY'):
            admit(settings,item,argv,current_price_class=price,limits=billing.limits(s,settings))
    c.patch('/api/billing',json={'limits':{flag:True}})
    with sessions() as s:
        assert admit(settings,item,argv,current_price_class=price,limits=billing.limits(s,settings))['price_class']==price
        other='paid' if price=='subscription' else 'subscription'
        item.checkpoint=json.dumps({'dispatch_policy':snapshot(SimpleNamespace(agent_target=''),0,other)})
        with pytest.raises(DispatchDenied,match='FREE_ONLY'):
            admit(settings,item,argv,current_price_class=other,limits=billing.limits(s,settings))


def test_failed_dispatch_uses_only_the_approved_dependency_order(app):
    c,sessions,settings,workspace=app
    with sessions() as s:
        nodes=[dict(key='a',title='Bounded inspection',description='Read one file.',scope='One file only.',acceptance='Report file count.',
            assignee='hermes',model='openrouter/free',work_kind='research',size='xs',risk='low',estimate_minutes=15,route_reason='Read-only bounded inspection.')]
        p=projects.create(s,dict(title='Dispatch fixture',brief='Inspect one file.',working_dir=str(workspace),nodes=nodes),settings,'operator')
        from project_schemas import Action
        projects.submit(s,p,Action(revision=1,approve_coordination=True,approve_api_work=True),settings,'operator')
        pipe=json.loads(p.pipeline);card=s.get(Card,pipe['card_id']);run(s,card,stage='failed',error='provider unavailable')
        projects.advance(s,settings);s.commit()
        assert p.state=='active'
        assert len(list(s.scalars(select(ProjectTask).where(ProjectTask.project_id==p.id,ProjectTask.role=='story'))))==1


@pytest.mark.parametrize('error,kind',[('429 quota','rate_limit'),('provider unavailable','provider'),('FREE_ONLY: refused','policy'),('401 sign in','sign_in')])
def test_failure_categories(error,kind):
    assert recovery.failure_kind(SimpleNamespace(stage='failed',error=error))==kind


@pytest.mark.parametrize('result,kind',[('429 free endpoint limit','rate_limit'),('Provider unavailable','provider'),('Sign in required','sign_in'),('No diagnostic supplied','runtime')])
def test_generic_hermes_exit_keeps_provider_diagnostics_useful_without_exposing_them(result,kind):
    assert recovery.failure_kind(SimpleNamespace(stage='failed',error='hermes exit code 1',result_text=result))==kind
    assert recovery.failure_kind(SimpleNamespace(stage='succeeded',error=None,result_text=result)) is None
