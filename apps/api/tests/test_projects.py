"""Reviewed project pipeline, isolated execution and handoffs; never calls an LLM."""
import json
from types import SimpleNamespace
import subprocess
from pathlib import Path
import pytest
from sqlalchemy import select
from models import Card, Run, Project
from agents import AgentSpec
from dispatcher import Dispatcher
from settings import get_settings
from project_schemas import Accept
import projects
import cards
import project_outputs

@pytest.mark.parametrize('result', [
    '**Blocked: nothing was uploaded.** The approved release inputs are missing.',
    'The clean install is blocked, so I have no install, update, rollback or recovery receipts.',
    '**Verification is incomplete.** The preview was not run.',
    '**Status: not complete.** Nothing was installed or tested.',
    '## Handoff: docs\n\n**Status: written, not verified. Do not mark this story Done.**\n\nNone of the documented commands was executed.',
    'The report contains useful findings.\n\n## Final status\n\nThis story is not Done. Required checks have not been executed.',
    'The implementation is present. Checks: I did not run tests or start a preview.',
    'Implementation is present, but this story is not fully verified. Keep this story incomplete.',
    'The remaining checks are incomplete. This handoff does not claim complete verification.',
    '- **Incomplete:** backend lifecycle checks did not run successfully in the sandbox.',
    '**Story s7 is incomplete.** None of the required checks ran in this session.',
    'This story is **incomplete**: no release archive was built or receipt produced.',
    ('## Long handoff\n\n' + ('Implemented detail. ' * 250) +
     '\n\nThis story is **incomplete**: no release archive was built.'),
    '# Evidence handoff\n\n**Status:** INCOMPLETE. The pack lists what exists.',
    'The docs are updated, but story `s17_docs_rcd` is **incomplete**.',
    '## Handoff: s16_docs_mcd is incomplete\n\nNothing was executed.',
    'The evidence pack is incomplete, so nothing should be marked done.',
    '## Handoff — incomplete verification\n\nChanges were written but require host testing.',
    'Story incomplete: the inventory is drafted, but dashboard catalog sizing and estimates remain unverified.',   # pilot story 17
    '**Task unfinished.** The scenes are drafted.',
])
def test_direct_incomplete_handoff_language_is_not_completion(result):
    assert project_outputs.incomplete_error(SimpleNamespace(result_text=result))

PLAN_MODE_REFUSAL = (
    "The verifier run is not done. Plan mode is active, so I have not run `tools/verify-preview.sh` or any other command that writes or starts a server.\n\n"
    "I wrote the plan to `/home/pi/.claude/plans/x.md`. I could not call ExitPlanMode to submit the plan for approval.")


def test_a_plan_mode_refusal_is_incomplete_with_a_reason_that_says_what_to_do():
    reason = project_outputs.incomplete_error(SimpleNamespace(result_text=PLAN_MODE_REFUSAL))
    assert reason and 'plan mode' in reason and 'human or CI story' in reason and 'workspace execution' in reason and 'does not allow starting a server' in reason


@pytest.mark.parametrize('result', [
    "Plan mode is active, so nothing was executed. The commands below are the plan.",
    "I cannot run the build in plan mode; no check ran.",
    "Plan mode blocks execution, and the checks have not been run.",
])
def test_other_phrasings_of_a_plan_mode_refusal_are_incomplete(result):
    assert 'plan mode' in project_outputs.incomplete_error(SimpleNamespace(result_text=result))


@pytest.mark.parametrize('result', [
    "# Review\n\nI read the files and found two issues. Plan mode kept this review read-only, as intended.",
    "All checks ran and passed. The agent used plan mode only for the read steps.",
    "Plan mode is active. The plan is written; plan mode blocks writing the file, so approve the plan to lift plan mode and save it.",
])
def test_a_normal_read_result_or_an_output_approval_plan_is_not_flagged_as_a_plan_mode_refusal(result):
    reason = project_outputs.incomplete_error(SimpleNamespace(result_text=result))
    assert not reason or 'read-only plan mode' not in reason


@pytest.fixture
def app(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(AgentSpec,'available',lambda self,settings:True)
    # The Codex default model comes from the host's ~/.codex/config.toml; a test must not depend on it.
    from agents import REGISTRY
    import dataclasses
    monkeypatch.setitem(REGISTRY,'codex',dataclasses.replace(REGISTRY['codex'],default_model=lambda:'gpt-6-luna'))
    # RCD ships free-only; these flows exercise Claude and Codex subscriptions, so the tests opt in to them.
    import billing
    monkeypatch.setattr(billing,'DEFAULT_ACCOUNTS',{**billing.DEFAULT_ACCOUNTS,
        'claude':{'mode':'subscription','monthly_usd':20.0},'codex':{'mode':'subscription','monthly_usd':20.0}})
    client=make_client()
    st=get_settings();st.dispatch_free_only=False;st.default_budget_usd=1.0;st.dispatch_max_budget_usd=1.0   # the paid and subscription flows under test
    config=tmp_path/'openclaw.json'
    config.write_text(json.dumps({'agents':{'list':[{'id':'mm-main'},{'id':'mm-developer'},{'id':'mm-security'}]}}))
    get_settings().openclaw_config_path=config
    with client:
        assert client.patch('/api/routes/policy/cost',json={'membership':True,'paid':True}).status_code==200   # paid flows still need their own approval
        yield client,client.app.state.sessions,tmp_path/'ws/proj',get_settings()

def node(key,**kw):
    base=dict(key=key,title=key,description='Implement a bounded local change.',scope='Only this story-owned file.',acceptance='Checks pass and reviewer verifies the artifact.',assignee='codex',model='gpt-6.1-sol',
        work_kind='implement',size='s',risk='low',estimate_minutes=45,route_reason='Bounded local change; the catalog route fits.')
    return {**base,**kw}

def test_managed_workspace_symlink_cannot_escape_approved_root(app,tmp_path):
    import project_workspaces
    from fastapi import HTTPException
    root=app[3].workdir_roots[-1].expanduser().resolve()
    root.mkdir(parents=True,exist_ok=True)
    outside=tmp_path/'outside';outside.mkdir()
    (root/'.mcd-projects').symlink_to(outside,target_is_directory=True)
    with pytest.raises(HTTPException) as error:
        project_workspaces.location(1,1,'story',app[3])
    assert error.value.status_code==422
    assert not list(outside.iterdir())

def new(app,nodes=None,**kw):
    c,s,wd,settings=app
    r=c.post('/api/projects',json={'title':'Test project','brief':'Build the reviewed project.','working_dir':str(wd),'nodes':nodes or [],**kw})
    assert r.status_code==201,r.text
    return r.json()

def finish(app,cid,result='',stage='succeeded',error=None):
    c,s,wd,settings=app
    with s.begin() as db:
        card=db.get(Card,cid)
        run=db.scalar(select(Run).where(Run.card_id==cid).order_by(Run.id.desc()).limit(1))
        if not run or run.stage!='running':
            run=Run(card_id=cid,agent=card.agent,model_requested=card.model,working_dir=card.working_dir,
                stage='running',started_at=projects.now(),command='[]',log_path='test-only')
            db.add(run);db.flush()
        run.stage=stage;run.result_text=result;run.error=error
        card.column='done' if stage=='succeeded' else 'failed'
        projects.on_finish(db,card,run,stage)
        return run.id

def advance(app):
    with app[1].begin() as db: projects.advance(db,app[3])

def active(app,nodes,**kw):
    p=new(app,nodes,**kw)
    r=app[0].post(f'/api/projects/{p["id"]}/submit',json={'revision':1,'approve_coordination':True,'approve_api_work':True})
    assert r.status_code==200,r.text
    finish(app,r.json()['pipeline']['card_id'],json.dumps({'order':projects.ordered([dict(kind='story',depends_on=[],**n) if 'depends_on' not in n else dict(kind='story',**n) for n in nodes])}))
    advance(app)
    p=app[0].get(f'/api/projects/{p["id"]}').json()
    assert p['state']=='active',p
    return p

def test_revision_schema_and_cycles(app):
    p=new(app,[node('a'),node('b',depends_on=['a'])]);c=app[0]
    doc=p['document'];doc['nodes'][0]['depends_on']=['b']
    assert c.patch('/api/projects/1',json={'revision':1,'document':doc}).status_code==422
    doc['nodes'][0]['depends_on']=[];doc['nodes'][0]['parent']=''
    r=c.patch('/api/projects/1',json={'revision':1,'document':doc});assert r.status_code==200
    assert r.json()['revision']==2 and r.json()['document']['nodes'][0]['parent'] is None
    assert c.patch('/api/projects/1',json={'revision':1,'document':doc}).status_code==409
    doc['nodes'][0]['mcp_command']='untrusted instructions'
    assert c.patch('/api/projects/1',json={'revision':2,'document':doc}).status_code==422

def test_full_planning_pipeline_requires_review_then_submits_once(app):
    p=new(app);c=app[0]
    assert c.post('/api/projects/1/plan',json={'revision':1}).status_code==422
    p=c.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True}).json()
    cid=p['pipeline']['card_id'];finish(app,cid,json.dumps({**next(v for v in p['pipeline']['choices'] if v['agent']=='codex'),'rationale':'Fit'}));advance(app)
    p=c.get('/api/projects/1').json();assert p['pipeline']['step']=='plan'
    finish(app,p['pipeline']['card_id'],json.dumps({'nodes':[node('a'),node('b',depends_on=['a'])]}));advance(app)
    p=c.get('/api/projects/1').json();assert p['pipeline']['step']=='return'
    finish(app,p['pipeline']['card_id'],json.dumps({'nodes':[node('a'),node('b',depends_on=['a'])]}));advance(app)
    p=c.get('/api/projects/1').json();assert p['state']=='review' and p['revision']==2
    assert not any(t['role']=='story' for t in p['tasks'])
    action={'revision':2,'approve_coordination':True}
    p=c.post('/api/projects/1/submit',json=action).json()
    assert c.post('/api/projects/1/submit',json=action).json()['pipeline']==p['pipeline']
    finish(app,p['pipeline']['card_id'],json.dumps({'order':['a','b']}));advance(app);advance(app)
    p=c.get('/api/projects/1').json();assert len([t for t in p['tasks'] if t['role']=='story'])==2
    doc=p['document'];doc['nodes'][0]['model']='other'
    assert c.patch('/api/projects/1',json={'revision':2,'document':doc}).status_code==409

def test_resume_saved_planner_proposal_fills_only_human_scope_and_refreshes_catalog(app):
    c,s,wd,settings=app
    p=new(app)
    p=c.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True}).json()
    finish(app,p['pipeline']['card_id'],json.dumps(next(v for v in p['pipeline']['choices'] if v['agent']=='codex')));advance(app)
    p=c.get('/api/projects/1').json();planner_card=p['pipeline']['card_id']
    human=dict(node('review'),assignee='human',scope='',model='')
    finish(app,planner_card,json.dumps({'nodes':[node('work'),human]}))
    with s.begin() as db:
        row=db.get(Project,1);row.state='planning_failed';row.error='Legacy scope validation'
        pipeline=json.loads(row.pipeline);pipeline['execution_catalog']=[{'agent':'openclaw','targets':[{'id':'retired'}]}];row.pipeline=json.dumps(pipeline)
    assert c.get('/api/projects/1').json()['can_resume_plan']
    assert c.post('/api/projects/1/resume-plan',json={'revision':2}).status_code==409
    resumed=c.post('/api/projects/1/resume-plan',json={'revision':1});assert resumed.status_code==200,resumed.text
    p=resumed.json();assert p['state']=='planning' and p['pipeline']['step']=='return'
    assert len([t for t in p['tasks'] if t['role']=='plan'])==1
    with s() as db:
        review=db.get(Card,p['pipeline']['card_id']).body
        assert 'Operator decision or review limited' in review and 'mm-developer' in review and '"id": "retired"' not in review
    assert c.post('/api/projects/1/resume-plan',json={'revision':1}).status_code==409
    finish(app,p['pipeline']['card_id'],json.dumps({'nodes':[node('work'),human]}));advance(app)
    p=c.get('/api/projects/1').json();assert p['state']=='review' and p['revision']==2
    assert p['document']['nodes'][1]['scope'].startswith('Operator decision')
    assert not any(t['role']=='story' for t in p['tasks'])

def test_agent_missing_scope_is_named_and_not_normalized(app):
    c,s,wd,settings=app
    from fastapi import HTTPException
    with pytest.raises(HTTPException,match='bounded scope') as error:
        projects.proposal(new(app)['document'],[dict(node('missing'),scope='')],settings)
    assert 'missing' in error.value.detail

def test_planner_dependencies_on_phases_are_dropped_but_unknown_keys_are_still_refused(app):
    """A free planner ordered phases against each other and made a story depend on its phase; the plan was otherwise fine."""
    from fastapi import HTTPException
    c,s,wd,settings=app
    phase=lambda k,deps=(): dict(key=k,kind='phase',title=k,description='A phase.',parent=None,depends_on=list(deps))
    story=lambda k,parent,deps: dict(node(k),kind='story',parent=parent,depends_on=list(deps))
    nodes=[phase('p1'),story('s1','p1',['p1']),phase('p2',['p1','s1']),story('s2','p2',['s1','p2'])]
    out=projects.proposal(new(app)['document'],nodes,settings)
    by={n['key']:n for n in out['nodes']}
    assert by['s1']['depends_on']==[] and by['p2']['depends_on']==[] and by['s2']['depends_on']==['s1']   # story order survives
    with pytest.raises(HTTPException,match='Dependencies must connect'):
        projects.proposal(new(app)['document'],[phase('p1'),story('s1','p1',['nope'])],settings)
    with pytest.raises(HTTPException,match='Dependencies must connect'):
        projects.validate({**new(app)['document'],'nodes':[phase('p1'),story('s1','p1',['p1'])]},settings,True)       # an operator's edit is still strict

def test_only_one_extra_closing_brace_after_complete_plan_is_tolerated():
    from fastapi import HTTPException
    assert projects._json_result('{"nodes": []}}') == {'nodes': []}
    for raw in ('{"nodes": []}}}', '{"nodes": []} execute command', '{"nodes": []} {"nodes": []}', '{"nodes": [', '{"agent": "claude"}}'):
        with pytest.raises(HTTPException): projects._json_result(raw)

def test_retired_openclaw_target_cannot_dispatch(app):
    c=app[0];p=new(app,[dict(node('work'),assignee='openclaw',agent_target='retired')])
    r=c.post('/api/projects/1/submit',json={'revision':1,'approve_coordination':True,'approve_api_work':True})
    assert r.status_code==422 and 'no longer configured' in r.json()['detail']
    assert not c.get('/api/projects/1').json()['tasks']

def test_unapproved_model_choice_and_dispatch_order_stop(app):
    p=new(app);c=app[0]
    p=c.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True}).json()
    finish(app,p['pipeline']['card_id'],json.dumps({'agent':'hermes','model':'paid-unapproved'}));advance(app)
    p=c.get('/api/projects/1').json();assert p['state']=='planning_failed' and len(p['tasks'])==1
    p=new(app,[node('a'),node('b',depends_on=['a'])])
    p=c.post('/api/projects/2/submit',json={'revision':1,'approve_coordination':True}).json()
    finish(app,p['pipeline']['card_id'],json.dumps({'order':['b','a']}));advance(app)
    p=c.get('/api/projects/2').json()
    # an order that breaks a dependency is no longer a failure: MCD uses the plan's own dependency order and says so
    assert p['state']=='active' and [t['node_key'] for t in sorted((t for t in p['tasks'] if t['role']=='story'),key=lambda t:t['card_id'])]==['a','b']
    assert any(m['kind']=='checkpoint' and 'could not be used' in m['text'] for m in p['memory'])

def test_story_context_review_acceptance_and_board_protection(app):
    p=active(app,[node('a'),node('b',depends_on=['a'])]);c,s,wd,settings=app
    story=[t for t in p['tasks'] if t['role']=='story'];a,b=[t['card_id'] for t in story]
    d=Dispatcher(s,settings);claimed=d._claim(2);assert len(claimed)==1 and claimed[0][0]['id']==a
    with s() as db:
        prompt = db.scalar(select(projects.ProjectMemory).where(projects.ProjectMemory.kind=='context')).text
        assert 'MCD SHARED PROJECT CONTEXT' in prompt
        assert 'final assistant text' in prompt and 'Do not use sessions_yield' in prompt
    rid=finish(app,a,'Proposed changes and checks.')
    assert c.get(f'/api/cards/{a}').json()['column']=='review'
    assert d._claim(2)==[]
    assert c.patch(f'/api/cards/{a}',json={'model':'different'}).status_code==409
    assert c.post(f'/api/cards/{a}/dependencies',json={'depends_on_id':b}).status_code==409
    assert c.delete(f'/api/cards/{a}').status_code==409
    assert c.get(f'/api/cards/{a}').json()['project']['id']==1
    assert c.post(f'/api/projects/1/stories/{a}/accept',json={'run_id':rid+1,'summary':'Wrong run'}).status_code==409
    r=c.post(f'/api/projects/1/stories/{a}/accept',json={'run_id':rid,'summary':'Accepted checked artifact A.'});assert r.status_code==200,r.text
    claimed=d._claim(2);assert len(claimed)==1 and claimed[0][0]['id']==b
    with s() as db:
        assert 'Accepted checked artifact A.' in projects.claim_context(db,db.get(Card,b))
    c.post('/api/projects/1/pause',json={'revision':1})
    rid=finish(app,b,'B checked')
    assert c.post(f'/api/projects/1/stories/{b}/accept',json={'run_id':rid,'summary':'B verified'}).json()['state']=='complete'

def test_pause_prevents_claim_and_resume_keeps_revision(app):
    p=active(app,[node('a')]);c,s,wd,settings=app
    assert c.post('/api/projects/1/pause',json={'revision':1}).json()['state']=='paused'
    assert Dispatcher(s,settings)._claim(2)==[]
    assert c.post('/api/projects/1/resume',json={'revision':1}).json()['state']=='active'
    assert len(Dispatcher(s,settings)._claim(2))==1

def test_screenshot_dispatch_keeps_live_server_and_routes_unchanged(app):
    p=active(app,[dict(node('capture'),description='Capture a demo dashboard on port 8800.',assignee='openclaw',model='openrouter/thinkingmachines/inkling:free',agent_target='mm-developer')])
    c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    claimed=Dispatcher(s,settings)._claim(1)
    assert len(claimed)==1 and claimed[0][0]['id']==cid
    with s() as db:
        card=db.get(Card,cid)
        prompt=db.scalar(select(projects.ProjectMemory).where(projects.ProjectMemory.card_id==cid,projects.ProjectMemory.kind=='context')).text
        assert 'Capture a demo dashboard on port 8800.' in prompt
        assert 'Never stop, restart, kill, reconfigure or replace it' in prompt
        assert '8801 or another free port' in prompt
        assert 'MAC_CONTROL_COLLECTOR_ENABLED=false' in prompt
        assert 'MAC_CONTROL_DISPATCHER_ENABLED=false' in prompt
        assert 'only that verified preview PID' in prompt
        assert card.model=='openrouter/thinkingmachines/inkling:free'
        assert card.agent_target=='mm-developer'
        assert card.column=='running'

def test_model_routes_handoff_same_story_once_and_no_paid_guess(app):
    p=active(app,[node('a',routes=[{'agent':'claude','model':'claude-sonnet-5-5'},{'agent':'hermes','model':'thinkingmachines/inkling:free'}])]);c,s,wd,settings=app
    a=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    d=Dispatcher(s,settings);assert len(d._claim(2))==1
    finish(app,a,'Partial work',stage='failed',error='usage limit reached')
    assert c.get(f'/api/cards/{a}').json()['agent']=='claude'
    assert len(d._claim(2))==1
    finish(app,a,stage='failed',error='quota limit reached')
    assert c.get(f'/api/cards/{a}').json()['agent']=='hermes'
    assert len(d._claim(2))==1
    finish(app,a,stage='failed',error='429 rate limit')
    assert c.get(f'/api/cards/{a}').json()['column']=='failed' and d._claim(2)==[]
    assert len([t for t in c.get('/api/projects/1').json()['tasks'] if t['role']=='story'])==1
    assert 'Partial work' in c.get('/api/projects/1/context').text


def test_operator_retry_selects_only_reviewed_route_and_preserves_story(app):
    choice={'agent':'claude','model':'claude-haiku-5-5'}
    p=active(app,[node('a',routes=[choice]),node('b',depends_on=['a'])])
    c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    finish(app,cid,'Unverified partial output',stage='timeout',error='provider timeout')
    before=c.get(f'/api/cards/{cid}').json()
    p=c.get('/api/projects/1').json()
    task=next(t for t in p['tasks'] if t['card_id']==cid)
    assert task['retry_routes']==[choice]
    blocked=next(t for t in p['tasks'] if t['node_key']=='b')
    rejected=c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1,'route':{'agent':'hermes','model':'anthropic/paid'}})
    assert rejected.status_code==422 and 'approved plan' in rejected.json()['detail']
    assert c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':2,'route':choice}).status_code==409
    r=c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1,'route':choice,'acknowledge_timeout':True})
    assert r.status_code==200,r.text
    after=c.get(f'/api/cards/{cid}').json()
    assert (after['agent'],after['model'],after['column'])==('claude','claude-haiku-5-5','queued')
    for key in ['id','body','acceptance','working_dir','mode','timeout_s','depends_on','approved_at']:
        assert after[key]==before[key]
    assert c.get(f'/api/cards/{blocked["card_id"]}').json()['blocked_by']==[cid]
    assert r.json()['revision']==1
    assert 'Operator selected approved retry route' in c.get('/api/projects/1/context').text
    # A duplicate request cannot launch twice after the card is queued.
    assert c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1,'route':choice}).status_code==409


def test_unaccepted_review_rerun_preserves_scope_evidence_and_dependency_gate(app):
    p=active(app,[node('a'),node('b',depends_on=['a'])])
    c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    dependent=next(t['card_id'] for t in p['tasks'] if t['node_key']=='b')
    rid=finish(app,cid,'Verification report ready for review.')
    before=c.get(f'/api/cards/{cid}').json()
    assert before['column']=='review'
    path=f'/api/projects/1/stories/{cid}/retry'
    assert c.post(path,json={'revision':2}).status_code==409
    response=c.post(path,json={'revision':1})
    assert response.status_code==200,response.text
    after=c.get(f'/api/cards/{cid}').json()
    assert after['column']=='queued'
    for key in ['body','acceptance','agent','model','mode','working_dir','approved_at','depends_on']:
        assert after[key]==before[key]
    assert c.get(f'/api/cards/{dependent}').json()['blocked_by']==[cid]
    with s() as db:
        assert db.get(Run,rid).result_text=='Verification report ready for review.'
        assert db.get(Run,rid).stage=='succeeded'
    assert c.post(path,json={'revision':1}).status_code==409
    with s.begin() as db:db.get(Card,cid).column='done'
    assert c.post(path,json={'revision':1}).status_code==200   # b has not started, so reopening a invalidates no handoff
    assert c.get(f'/api/cards/{cid}').json()['column']=='queued'


def test_completed_project_can_reopen_only_accepted_final_agent_story(app):
    p=active(app,[node('a'),node('b',depends_on=['a'])])
    c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    for key in ['a','b']:
        rid=finish(app,ids[key],'Verified artifact ready.')
        response=c.post(f'/api/projects/1/stories/{ids[key]}/accept',json={'run_id':rid,'summary':'Operator verified the artifact.'})
        assert response.status_code==200,response.text
    assert c.get('/api/projects/1').json()['state']=='complete'
    assert c.post(f'/api/projects/1/stories/{ids["a"]}/retry',json={'revision':1}).status_code==409
    assert c.get('/api/projects/1').json()['state']=='complete'
    response=c.post(f'/api/projects/1/stories/{ids["b"]}/retry',json={'revision':1})
    assert response.status_code==200,response.text
    assert response.json()['state']=='active'
    assert c.get(f'/api/cards/{ids["a"]}').json()['column']=='done'
    assert c.get(f'/api/cards/{ids["b"]}').json()['column']=='queued'
    context=c.get('/api/projects/1/context').text
    assert 'Earlier accepted run' in context and 'new run requires review' in context
    assert c.post(f'/api/projects/1/stories/{ids["b"]}/retry',json={'revision':1}).status_code==409


def test_accepted_story_can_be_reopened_until_a_dependent_starts(app):
    p=active(app,[node('a'),node('b',depends_on=['a'])])
    c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    rid=finish(app,ids['a'],'Art said done but is wrong.')
    assert c.post(f'/api/projects/1/stories/{ids["a"]}/accept',json={'run_id':rid,'summary':'Operator accepted.'}).status_code==200
    assert c.get(f'/api/cards/{ids["a"]}').json()['column']=='done'
    # b depends on a but has not run: reopening a invalidates no handoff
    response=c.post(f'/api/projects/1/stories/{ids["a"]}/retry',json={'revision':1})
    assert response.status_code==200,response.text
    assert c.get(f'/api/cards/{ids["a"]}').json()['column']=='queued'
    rid=finish(app,ids['a'],'Fixed.')
    assert c.post(f'/api/projects/1/stories/{ids["a"]}/accept',json={'run_id':rid,'summary':'Operator accepted again.'}).status_code==200
    # once b has a run, its handoff exists, so reopening a is refused
    finish(app,ids['b'],'Built on the fixed art.')
    response=c.post(f'/api/projects/1/stories/{ids["a"]}/retry',json={'revision':1})
    assert response.status_code==409 and 'already started' in response.text
    assert c.get(f'/api/cards/{ids["a"]}').json()['column']=='done'


def test_review_rerun_does_not_skip_output_approval(app):
    p=active(app,[node('a'),node('b')])
    c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    rid=finish(app,cid,'Unaccepted output')
    with s.begin() as db:db.get(Run,rid).stage='awaiting_approval'
    assert c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1}).status_code==409
    assert c.get(f'/api/cards/{cid}').json()['column']=='review'


def test_plain_retry_keeps_current_assignment_even_if_alternates_exist(app):
    p=active(app,[node('a',routes=[{'agent':'claude','model':'claude-haiku-5-5'}])])
    c,s,wd,settings=app;cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    finish(app,cid,stage='timeout',error='provider timeout')
    assert c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1,'acknowledge_timeout':True}).status_code==200
    after=c.get(f'/api/cards/{cid}').json()
    assert (after['agent'],after['model'])==('codex','gpt-6.1-sol')


def test_reviewed_subscription_retry_does_not_expand_to_api_billing(app,monkeypatch):
    choice={'agent':'claude','model':'claude-haiku-5-5'}
    p=active(app,[node('a',routes=[choice])]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    finish(app,cid,stage='timeout',error='provider timeout')
    with s.begin() as db:
        project=db.get(Project,1);m=json.loads(project.approved_manifest)
        m['api_work_approved']=False;project.approved_manifest=json.dumps(m)
    monkeypatch.setattr(projects,'subscription',lambda s,a:False)
    r=c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1,'route':choice})
    assert r.status_code==422 and 'API billing' in r.json()['detail']
    assert c.get(f'/api/cards/{cid}').json()['column']=='failed'

def test_arbitrary_api_fallback_not_allowed_and_paid_story_requires_approval(app):
    p=new(app,[node('a',routes=[{'agent':'hermes','model':'anthropic/paid'}])]);c=app[0]
    assert c.post('/api/projects/1/submit',json={'revision':1,'approve_coordination':True,'approve_api_work':True}).status_code==422
    p=new(app,[dict(node('a'),assignee='hermes',model='thinkingmachines/inkling:free')])
    assert c.post('/api/projects/2/submit',json={'revision':1,'approve_coordination':True}).status_code==422

def git(wd,*args):
    return subprocess.check_output(['git','-C',str(wd),*args],text=True,stderr=subprocess.DEVNULL).strip()

def init_repo(wd):
    git(wd,'init','-b','codex/test-project');git(wd,'config','user.name','Test');git(wd,'config','user.email','test@localhost')
    (wd/'base.txt').write_text('base');git(wd,'add','.');git(wd,'commit','-m','base')

def test_parallel_isolates_edits_and_passes_only_accepted_commits(app):
    c,s,wd,settings=app;init_repo(wd);base=git(wd,'rev-parse','HEAD')
    p=active(app,[node('a'),node('b'),node('c',depends_on=['a','b'])],dispatch_mode='parallel')
    story={t['node_key']:t for t in p['tasks'] if t['role']=='story'}
    d=Dispatcher(s,settings);assert len(d._claim(2))==2
    assert story['a']['working_dir']!=story['b']['working_dir']
    for key in ['a','b']:
        workspace=Path(story[key]['working_dir']);(workspace/(key+'.txt')).write_text(key)
        git(workspace,'add','.');git(workspace,'commit','-m',key)
        rid=finish(app,story[key]['card_id'],'Artifact '+key)
        r=c.post(f'/api/projects/1/stories/{story[key]["card_id"]}/accept',json={'run_id':rid,'summary':key+' verified'});assert r.status_code==200,r.text
    claimed=d._claim(2);assert len(claimed)==1 and claimed[0][0]['id']==story['c']['card_id']
    child=Path(story['c']['working_dir']);assert (child/'a.txt').read_text()=='a' and (child/'b.txt').read_text()=='b'
    assert git(wd,'rev-parse','HEAD')==base and not (wd/'a.txt').exists()
    rid=finish(app,story['c']['card_id'],'Integration checked')
    (child/'dirty.txt').write_text('Not reviewed')
    assert c.post(f'/api/projects/1/stories/{story["c"]["card_id"]}/accept',json={'run_id':rid,'summary':'No'}).status_code==409

def test_parallel_refuses_dirty_base_and_commit_conflict_stops(app):
    c,s,wd,settings=app;init_repo(wd)
    (wd/'base.txt').write_text('dirty')
    p=new(app,[node('a')],dispatch_mode='parallel')
    assert c.post('/api/projects/1/submit',json={'revision':1,'approve_coordination':True}).status_code==409
    git(wd,'checkout','--','base.txt')
    p=active(app,[node('a'),node('b'),node('c',depends_on=['a','b']),node('d',depends_on=['c'])],dispatch_mode='parallel')
    story={t['node_key']:t for t in p['tasks'] if t['role']=='story'}
    d=Dispatcher(s,settings);d._claim(2)
    for key in ['a','b']:
        workspace=Path(story[key]['working_dir']);(workspace/'base.txt').write_text(key)
        git(workspace,'add','.');git(workspace,'commit','-m',key)
        rid=finish(app,story[key]['card_id'],'Verified')
        assert c.post(f'/api/projects/{p["id"]}/stories/{story[key]["card_id"]}/accept',json={'run_id':rid,'summary':'Verified '+key}).status_code==200
    assert d._claim(2)==[]
    p=c.get(f'/api/projects/{p["id"]}').json();assert 'conflict' in p['error'] and next(t for t in p['tasks'] if t['node_key']=='c')['column']=='failed'
    assert git(Path(story['c']['working_dir']),'status','--porcelain')==''
    child=Path(story['c']['working_dir']);(child/'base.txt').write_text('Reviewed combined resolution')
    path=f'/api/projects/{p["id"]}/stories/{story["c"]["card_id"]}'
    r=c.post(path+'/integration',json={'revision':1,'summary':'Verified both prerequisite changes and the conflict resolution.','snapshot':True,'files':['base.txt']})
    assert r.status_code==200,r.text
    assert next(t for t in r.json()['tasks'] if t['node_key']=='c')['column']=='failed'
    assert c.post(path+'/retry',json={'revision':1}).status_code==200
    assert len(d._claim(2))==1
    rid=finish(app,story['c']['card_id'],'Combined result checked')
    assert c.post(path+'/accept',json={'run_id':rid,'summary':'Verified resolved integration'}).status_code==200
    claimed=d._claim(2);assert len(claimed)==1 and claimed[0][0]['id']==story['d']['card_id']
    assert (Path(story['d']['working_dir'])/'base.txt').read_text()=='Reviewed combined resolution'

@pytest.mark.parametrize('initial_error', ['usage limit reached', "You've hit your session limit"])
def test_quota_reported_only_on_stderr_still_hands_off_without_exposing_stderr(app,initial_error):
    import asyncio,sys
    from tests.test_dispatcher import FakeParser,_drain
    p=active(app,[node('a',routes=[{'agent':'claude','model':'claude-sonnet-5-5'}])]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    def fake_build(card,prompt,model,*a,**k): return [sys.executable,'-c',f"import sys; print({(initial_error+'; sensitive-debug-value')!r},file=sys.stderr); sys.exit(1)",'-m',model]   # pinned model, as the gate requires
    registry={'codex':AgentSpec('codex','Fake subscription','worker','codex_path',fake_build,FakeParser)}
    d=Dispatcher(s,settings,registry=registry);asyncio.run(_drain(d))
    with s() as db:
        run=db.scalar(select(Run).where(Run.card_id==cid))
        assert 'rate limit' in run.error and 'sensitive-debug-value' not in run.error
        assert db.get(Card,cid).agent=='claude' and db.get(Card,cid).column=='queued'

def test_reviewed_snapshot_passes_changes_without_worker_git_permissions(app):
    c,s,wd,settings=app;init_repo(wd)
    p=active(app,[node('a'),node('b',depends_on=['a'])],dispatch_mode='parallel')
    story={t['node_key']:t for t in p['tasks'] if t['role']=='story'}
    d=Dispatcher(s,settings);d._claim(2)
    workspace=Path(story['a']['working_dir']);(workspace/'accepted.txt').write_text('Checked content')
    rid=finish(app,story['a']['card_id'],'Verified changes')
    preview=c.get(f'/api/projects/1/stories/{story["a"]["card_id"]}/artifact').json();assert preview['files']==['accepted.txt']
    path=f'/api/projects/1/stories/{story["a"]["card_id"]}/accept'
    assert c.post(path,json={'run_id':rid,'summary':'Reviewed','snapshot':True,'files':['../escape']}).status_code==409
    r=c.post(path,json={'run_id':rid,'summary':'Reviewed accepted.txt','snapshot':True,'files':['accepted.txt']});assert r.status_code==200,r.text
    assert len(d._claim(2))==1
    assert (Path(story['b']['working_dir'])/'accepted.txt').read_text()=='Checked content'
    assert not (wd/'accepted.txt').exists()

def test_openclaw_targets_are_serialized_with_separate_story_sessions(app):
    c,s,wd,settings=app;init_repo(wd)
    n=lambda key: dict(node(key),assignee='openclaw',model='openrouter/thinkingmachines/inkling:free',agent_target='mm-main')
    p=active(app,[n('a'),n('b'),node('c')],dispatch_mode='parallel')
    tasks={t['node_key']:t for t in p['tasks'] if t['role']=='story'}
    d=Dispatcher(s,settings)
    d._adapters_recovered=True   # a dispatcher that is already running has reconciled at startup; these direct claims are its own runs
    claimed=d._claim(3)
    assert {a['id'] for a,_ in claimed}=={tasks['a']['card_id'],tasks['c']['card_id']}
    first=next(a['argv'] for a,_ in claimed if a['agent']=='openclaw')
    c.app.state.dispatcher=d
    thread=c.post('/api/chat/threads',json={'agent':'openclaw','working_dir':str(wd),'agent_target':'mm-main'}).json()
    assert c.post(f'/api/chat/threads/{thread["id"]}/messages',json={'text':'Inspect workspace'}).status_code==409
    from models import ChatMessage
    with s() as db: assert db.scalar(select(ChatMessage).where(ChatMessage.thread_id==thread['id'])).status=='failed'
    finish(app,tasks['a']['card_id'],'Ready for review')
    claimed=d._claim(2);assert len(claimed)==1 and claimed[0][0]['id']==tasks['b']['card_id']
    second=claimed[0][0]['argv']
    assert first[first.index('--session-id')+1]!=second[second.index('--session-id')+1]
    with s() as db: assert tasks['b']['working_dir'] in projects.claim_context(db,db.get(Card,tasks['b']['card_id']))

@pytest.mark.parametrize('bias',[-1,101,12.5,True,'50',None])
def test_planning_bias_rejects_invalid_input(app,bias):
    c,_,wd,_=app
    assert c.post('/api/projects',json={'title':'Test','brief':'Bounded goal','working_dir':str(wd),'planning_bias':bias}).status_code==422

def test_legacy_bias_default_is_read_only_and_edits_preserve_assignments(app):
    p=new(app,[node('a')]);assert p['document']['planning_bias']==50
    with app[1].begin() as db:
        row=db.get(Project,p['id']);legacy=json.loads(row.document);legacy.pop('planning_bias')
        row.document=json.dumps(legacy);row.approved_manifest='{"hash":"unchanged"}'
        assert projects.document(row)['planning_bias']==75
        assert 'planning_bias' not in json.loads(row.document)
        assert row.approved_manifest=='{"hash":"unchanged"}'
        row.approved_manifest=None
    p=app[0].get('/api/projects/1').json();original=p['document']['nodes']
    p['document']['planning_bias']=0
    saved=app[0].patch('/api/projects/1',json={'revision':1,'document':p['document']}).json()
    assert saved['document']['planning_bias']==0 and saved['document']['nodes']==original

@pytest.mark.parametrize('bias,phrase',[(0,'Economy.'),(50,'Balanced.'),(100,'Capability.')])
def test_bias_reaches_each_planning_stage_and_reviewed_edits_win(app,bias,phrase):
    c,s,_,_=app
    c.app.state.collector=SimpleNamespace(subagents={'openclaw':{'agents':[{'id':'mm-developer','name':'Local Dev','model':'openrouter/thinkingmachines/inkling:free','secret':'must-not-propagate'}]}})
    p=new(app,planning_bias=bias)
    def prompt(cid):
        with s() as db: return db.get(Card,cid).body
    p=c.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True}).json()
    assert phrase in prompt(p['pipeline']['card_id'])
    assert {v['agent'] for v in p['pipeline']['choices']} <= {'codex','claude'}
    finish(app,p['pipeline']['card_id'],json.dumps(next(v for v in p['pipeline']['choices'] if v['agent']=='codex')));advance(app)
    p=c.get('/api/projects/1').json();text=prompt(p['pipeline']['card_id'])
    assert phrase in text and 'mm-developer' in text and 'must-not-propagate' not in text
    proposed=dict(node('a'),assignee='openclaw',model='openrouter/thinkingmachines/inkling:free',agent_target='mm-developer')
    finish(app,p['pipeline']['card_id'],json.dumps({'nodes':[proposed]}));advance(app)
    p=c.get('/api/projects/1').json();assert phrase in prompt(p['pipeline']['card_id'])
    finish(app,p['pipeline']['card_id'],json.dumps({'nodes':[proposed]}));advance(app)
    p=c.get('/api/projects/1').json();assert p['document']['planning_bias']==bias
    # Merely recommending free-first work does not authorize its possible BYOK route.
    assert c.post('/api/projects/1/submit',json={'revision':2,'approve_coordination':True}).status_code==422
    p['document']['nodes'][0].update(assignee='claude',model='claude-sonnet-5-5',agent_target='')
    p=c.patch('/api/projects/1',json={'revision':2,'document':p['document']}).json()
    p=c.post('/api/projects/1/submit',json={'revision':3,'approve_coordination':True}).json()
    finish(app,p['pipeline']['card_id'],json.dumps({'order':['a']}));advance(app)
    p=c.get('/api/projects/1').json();story=next(t for t in p['tasks'] if t['role']=='story')
    assert (story['agent'],story['model'])==('claude','claude-sonnet-5-5')
    with s() as db: assert json.loads(db.get(Project,1).approved_manifest)['document']['planning_bias']==bias


def blocked_output(app):
    p=active(app,[dict(node('inventory'),assignee='claude',model='claude-haiku-5-5'),node('next',depends_on=['inventory'])])
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='inventory')
    rid=finish(app,cid,"The inventory is not written yet. Plan mode blocks writing it. Lift plan mode to proceed.")
    with app[1].begin() as db: db.get(Run,rid).session_id='test-prior-session'
    return cid,rid

def test_incomplete_plan_requires_output_approval_not_handoff_acceptance(app):
    c,s,wd,settings=app;cid,rid=blocked_output(app)
    task=next(t for t in c.get('/api/projects/1').json()['tasks'] if t['card_id']==cid)
    assert task['run_stage']=='awaiting_approval' and task['column']=='review'
    assert task['output_approval']['path'].endswith(f'project-1/story-{cid}/after-run-{rid}/inventory.md')
    assert not Path(task['output_approval']['path']).exists()
    assert c.post(f'/api/projects/1/stories/{cid}/accept',json={'run_id':rid,'summary':'Only a plan'}).status_code==409
    assert Dispatcher(s,settings)._claim(2)==[]
    endpoint=f'/api/projects/1/stories/{cid}/continue-output'
    assert c.post(endpoint,json={'revision':1,'run_id':rid}).status_code==422
    assert c.post(endpoint,json={'revision':2,'run_id':rid,'approve_output':True}).status_code==409
    assert c.post(endpoint,json={'revision':1,'run_id':rid+1,'approve_output':True}).status_code==409
    assert not (settings.data_dir/'project-outputs').exists()
    assert c.post('/api/projects/1/pause',json={'revision':1}).status_code==200
    assert c.post(endpoint,json={'revision':1,'run_id':rid,'approve_output':True}).status_code==409

def test_approved_output_continuation_resumes_readonly_and_requires_artifact_review(app):
    c,s,wd,settings=app;cid,rid=blocked_output(app)
    before=c.get(f'/api/cards/{cid}').json()
    endpoint=f'/api/projects/1/stories/{cid}/continue-output'
    body={'revision':1,'run_id':rid,'approve_output':True}
    assert c.post(endpoint,json=body).status_code==200
    assert c.post(endpoint,json=body).status_code==409
    after=c.get(f'/api/cards/{cid}').json()
    for key in ['id','body','acceptance','working_dir','mode','model','agent','timeout_s','depends_on']:
        assert after[key]==before[key]
    claimed=Dispatcher(s,settings)._claim(2);assert len(claimed)==1
    argv=claimed[0][0]['argv'];prompt=argv[argv.index('-p')+1]
    assert argv[argv.index('--resume')+1]=='test-prior-session'
    assert argv[argv.index('--permission-mode')+1]=='plan'
    assert argv[argv.index('--tools')+1]=='Read,Glob,Grep'
    assert 'MCD will save it' in prompt and 'No path field' in prompt
    assert '--max-budget-usd' not in argv
    new_run=finish(app,cid,json.dumps({'markdown':'# Verified inventory\n\nAll sections checked.\n','handoff':'Checked the cited source files.'}))
    artifact=c.get(f'/api/projects/1/stories/{cid}/artifact').json()['output']
    assert Path(artifact['path']).read_text()==artifact['markdown']
    assert (Path(artifact['path']).stat().st_mode & 0o777)==0o600
    assert not (wd/'inventory.md').exists()
    assert c.get(f'/api/cards/{cid}').json()['column']=='review'
    assert Dispatcher(s,settings)._claim(2)==[]
    accept=f'/api/projects/1/stories/{cid}/accept'
    assert c.post(accept,json={'run_id':new_run,'summary':'Verified'}).status_code==409
    Path(artifact['path']).write_text('changed')
    assert c.post(accept,json={'run_id':new_run,'summary':'Verified','output_sha256':artifact['sha256']}).status_code==409
    Path(artifact['path']).write_text(artifact['markdown'])
    assert c.post(accept,json={'run_id':new_run,'summary':'Verified inventory','output_sha256':artifact['sha256']}).status_code==200
    assert 'accepted_outputs' in c.get('/api/projects/1/context').text
    assert artifact['sha256'] in c.get('/api/projects/1/context').text
    assert len(Dispatcher(s,settings)._claim(2))==1

def test_invalid_continuation_result_never_writes_and_explicit_retry_keeps_authorization(app):
    c,s,wd,settings=app;cid,rid=blocked_output(app)
    assert c.post(f'/api/projects/1/stories/{cid}/continue-output',json={'revision':1,'run_id':rid,'approve_output':True}).status_code==200
    d=Dispatcher(s,settings);assert len(d._claim(2))==1
    new_run=finish(app,cid,json.dumps({'markdown':'bad','handoff':'done','path':'../../secret'}))
    with s() as db: assert db.get(Run,new_run).stage=='failed'
    assert not (settings.data_dir/'project-outputs').exists()
    assert c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1}).status_code==200
    argv=d._claim(2)[0][0]['argv'];assert argv[argv.index('--tools')+1]=='Read,Glob,Grep'

def test_output_approval_cannot_expand_subscription_to_api_billing(app,monkeypatch):
    c,s,wd,settings=app;cid,rid=blocked_output(app)
    monkeypatch.setattr(projects,'subscription',lambda *args:False)
    r=c.post(f'/api/projects/1/stories/{cid}/continue-output',json={'revision':1,'run_id':rid,'approve_output':True})
    assert r.status_code==422 and 'subscription' in r.json()['detail']
    assert c.get(f'/api/cards/{cid}').json()['column']=='review'

def test_continuation_billing_checked_at_claim_and_quota_does_not_auto_switch(app,monkeypatch):
    c,s,wd,settings=app;cid,rid=blocked_output(app)
    assert c.post(f'/api/projects/1/stories/{cid}/continue-output',json={'revision':1,'run_id':rid,'approve_output':True}).status_code==200
    real_subscription=projects.subscription
    monkeypatch.setattr(projects,'subscription',lambda *args:False)
    assert Dispatcher(s,settings)._claim(2)==[]
    assert c.get(f'/api/cards/{cid}').json()['column']=='failed'
    monkeypatch.setattr(projects,'subscription',real_subscription)
    # Restoring subscription mode requires an explicit retry, not a spontaneous claim.
    assert c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1}).status_code==200
    d=Dispatcher(s,settings);assert len(d._claim(2))==1
    finish(app,cid,stage='failed',error='usage limit reached')
    assert c.get(f'/api/cards/{cid}').json()['column']=='failed'
    assert d._claim(2)==[]


def policy_request(client,p,mode='automatic',**changes):
    return client.post(f'/api/projects/{p["id"]}/handoff-policy',json={
        'revision':p['revision'],'manifest_hash':p['handoff_approval']['manifest_hash'],
        'mode':mode,'approve':True,**changes})


def test_bulk_handoff_policy_requires_operator_acknowledgment_and_exact_revision(app):
    p=active(app,[node('a')]);c=app[0]
    assert policy_request(c,p,approve=False).status_code==422
    assert policy_request(c,p,revision=2).status_code==409
    assert policy_request(c,p,manifest_hash='0'*64).status_code==409
    assert c.get('/api/projects/1').json()['handoff_approval']['mode']=='manual'


def test_automatic_handoffs_advance_dependencies_but_leave_human_decisions(app):
    p=active(app,[node('a'),node('b',depends_on=['a']),dict(node('operator',depends_on=['b']),assignee='human',model='')]);c=app[0]
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    approved=policy_request(c,p);assert approved.status_code==200,approved.text
    assert approved.json()['handoff_approval']['excluded'][0]['card_id']==ids['operator']
    finish(app,ids['a'],'Created the requested document and checked its links.')
    advance(app)
    q=c.get('/api/projects/1').json();states={t['node_key']:t['column'] for t in q['tasks'] if t['role']=='story'}
    assert states=={'a':'done','b':'queued','operator':'backlog'}
    assert next(t for t in q['tasks'] if t['node_key']=='b')['blocked_by']==[], (ids,q['tasks'])
    assert any('not independently verified' in m['text'] for m in q['memory'] if m['kind']=='handoff')
    finish(app,ids['b'],'Created the second document.');advance(app);advance(app)
    q=c.get('/api/projects/1').json();assert q['state']=='active'
    assert next(t for t in q['tasks'] if t['node_key']=='operator')['column']=='backlog'
    assert len([m for m in q['memory'] if m['kind']=='handoff'])==2


def test_batch_handoffs_only_pass_current_successful_results(app):
    p=active(app,[node('a'),node('b',depends_on=['a'])]);c=app[0]
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    finish(app,ids['a'],'Document A complete.')
    response=policy_request(c,p,'batch');assert response.status_code==200,response.text
    assert response.json()['handoff_approval']['mode']=='manual'
    finish(app,ids['b'],'Document B complete.');advance(app)
    assert next(t for t in c.get('/api/projects/1').json()['tasks'] if t['node_key']=='b')['column']=='review'


def test_bulk_handoffs_do_not_pass_empty_failed_or_unfinished_results(app):
    p=active(app,[node('a'),node('b'),dict(node('plan'),assignee='claude',model='claude-haiku-5-5',mode='read')]);c=app[0]
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    assert policy_request(c,p).status_code==200
    finish(app,ids['a'],'');finish(app,ids['b'],'Failure',stage='failed',error='Timed out')
    finish(app,ids['plan'],'Waiting for operator approval.',stage='awaiting_approval');advance(app)
    q=c.get('/api/projects/1').json()
    assert all(t['column']!='done' for t in q['tasks'] if t['role']=='story')
    assert not any(m['kind']=='handoff' for m in q['memory'])


def test_bulk_handoffs_keep_security_license_and_publication_manual(app):
    p=active(app,[dict(node('docs'),title='Write section guide'),dict(node('security'),title='Review security findings'),dict(node('license'),title='Confirm license'),dict(node('publish'),title='Publish repository')]);c=app[0]
    review=p['handoff_approval']
    assert [t['title'] for t in review['eligible']]==['Write section guide']
    assert len(review['excluded'])==3
    assert policy_request(c,p).status_code==200
    for t in p['tasks']:
        if t['role']=='story':finish(app,t['card_id'],'Completed proposed work.')
    advance(app)
    q=c.get('/api/projects/1').json();states={t['node_key']:t['column'] for t in q['tasks'] if t['role']=='story'}
    assert states=={'docs':'done','security':'review','license':'review','publish':'review'}


def test_automatic_handoffs_respect_pause_and_can_be_disabled(app):
    p=active(app,[node('a')]);c=app[0];cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    assert policy_request(c,p).status_code==200
    c.post('/api/projects/1/pause',json={'revision':1})
    finish(app,cid,'Document complete.');advance(app)
    assert c.get('/api/projects/1').json()['tasks'][-1]['column']=='review'
    assert policy_request(c,p,'manual',approve=False).status_code==200
    c.post('/api/projects/1/resume',json={'revision':1});advance(app)
    assert c.get('/api/projects/1').json()['tasks'][-1]['column']=='review'

@pytest.mark.parametrize('result',[
    "I couldn't build the release candidate, so none of this story's acceptance criteria are met. Nothing was created.",
    "The docs-qa story is only partly done. The required checks need approval.",
    "I didn't create the repo, and nothing was created, pushed or changed on GitHub. Three things block this story.",
    '⚠️ 🛠️ `search "outDir|dist|build" in /tmp/check/apps/web/vite.config.ts` failed',
])
def test_explicit_incomplete_process_success_is_failed_and_cannot_release_dependencies(app,result):
    p=active(app,[node('a'),node('b',depends_on=['a'])]);c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    rid=finish(app,ids['a'],result)
    with s() as db:
        run=db.get(Run,rid)
        assert run.stage=='failed' and 'normal process exit' in run.error
        assert run.result_text==result
    assert c.post(f'/api/projects/1/stories/{ids["a"]}/accept',json={'run_id':rid,'summary':'Approve'}).status_code==409
    assert Dispatcher(s,settings)._claim(2)==[]
    assert policy_request(c,p).status_code==200
    advance(app)
    assert next(t for t in c.get('/api/projects/1').json()['tasks'] if t['node_key']=='a')['column']=='failed'


def test_reconciles_unaccepted_legacy_incomplete_result_once_without_changing_routes(app):
    p=active(app,[node('a')]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    rid=finish(app,cid,'Completed documentation.')
    with s.begin() as db:
        db.get(Run,rid).result_text="The story is unfinished. Git commands require approval."
        db.get(Run,rid).exit_code=0
    assert c.post(f'/api/projects/1/stories/{cid}/accept',json={'run_id':rid,'summary':'Approve'}).status_code==409
    advance(app);q=c.get('/api/projects/1').json()
    assert q['tasks'][-1]['column']=='failed' and q['tasks'][-1]['agent']=='codex'
    count=len(q['memory']);advance(app)
    assert len(c.get('/api/projects/1').json()['memory'])==count
    with s() as db: assert db.get(Run,rid).exit_code==0


def test_past_blocker_in_completed_handoff_does_not_change_success(app):
    p=active(app,[node('a')]);c=app[0];cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    finish(app,cid,'Completed the document and all required checks.\n\nEarlier the story is partly done was the old status; it is now finished.')
    advance(app)
    assert c.get('/api/projects/1').json()['tasks'][-1]['column']=='review'

def test_recovered_tool_warning_with_report_does_not_change_success(app):
    p=active(app,[node('a')]);c=app[0];cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    finish(app,cid,'⚠️ 🛠️ `search build setting` failed\n\nVerification completed. Read the configuration directly; all required checks passed. Report: verified.md')
    advance(app)
    assert c.get('/api/projects/1').json()['tasks'][-1]['column']=='review'


def test_diamond_release_and_run_spec_context_logs_without_handoff_clicks(app,monkeypatch):
    """Synthetic separate non-Git workspaces exercise concurrent diamond release."""
    c,s,wd,settings=app
    monkeypatch.setattr(projects.workspaces,'snapshot',lambda path:'0'*40)
    def workspace(project_id,revision,key,source,commit,settings):
        path=wd.parent/key;path.mkdir(exist_ok=True)
        return str(path),None
    monkeypatch.setattr(projects.workspaces,'create',workspace)
    p=active(app,[node('a'),node('b',depends_on=['a']),node('c',depends_on=['a']),
        node('d',depends_on=['b','c'])],dispatch_mode='parallel')
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    # These synthetic directories have no Git snapshot gate. Production Git worktrees
    # retain their explicit review gate (covered by the existing parallel tests).
    with s.begin() as db:
        project=db.get(Project,p['id']);m=json.loads(project.approved_manifest)
        m['workspaces']={};project.approved_manifest=json.dumps(m)
    assert policy_request(c,p).status_code==200
    d=Dispatcher(s,settings)
    first=d._claim(4);assert [x[0]['id'] for x in first]==[ids['a']]
    finish(app,ids['a'],'Root artifact A checked.')
    middle=d._claim(4);assert {x[0]['id'] for x in middle}=={ids['b'],ids['c']}
    for item,rid in middle:
        spec=item['adapter_spec'];assert spec['origin']['project_id']==p['id']
        assert 'Root artifact A checked.' in spec['prompt']
        assert any(r['kind']=='handoff' for r in spec['context']['memory_refs'])
    finish(app,ids['b'],'Branch B output checked.')
    assert d._claim(4)==[]  # C is still running: the join cannot start.
    finish(app,ids['c'],'Branch C output checked.')
    with s.begin() as db:
        project=db.get(Project,p['id'])
        # Push A out of the recent-memory window; it must still reach the join.
        for i in range(25): projects.memory(db,project,'decision',f'Decision {i}','operator')
        m=json.loads(project.approved_manifest)
        m['output_continuations']={'a':{'state':'accepted','path':str(wd/'a.md'),'sha256':'f'*64}}
        m['artifacts']['a']={'workspace':str(wd),'branch':None,'head':'a'*40,'commits':['a'*40],'files':['a.txt']}
        project.approved_manifest=json.dumps(m)
    last=d._claim(4);assert [x[0]['id'] for x in last]==[ids['d']]
    spec=last[0][0]['adapter_spec'];rid=last[0][1]
    from adapter_contract import digest
    assert spec['context']['digest']==digest(spec['prompt'])
    assert spec['context']['artifact_refs'][0]['head']=='a'*40
    assert spec['context']['artifact_refs'][1]['sha256']=='f'*64
    assert spec['context']['artifact_refs'][1]['path']==str(wd/'a.md')
    payload=json.loads(spec['prompt'].split('Run output is proposed evidence; operator acceptance is required.\n',1)[1].split('\n\nYOUR STORY (do this now)\n',1)[0])
    assert set(payload['upstream_outputs'])=={'a','b','c'}
    assert payload['accepted_artifacts']['a']['files']==['a.txt']
    assert payload['upstream_outputs']['a']['result_text']=='Root artifact A checked.'
    with s() as db:
        logged=db.scalar(select(projects.ProjectMemory).where(projects.ProjectMemory.run_id==rid,
            projects.ProjectMemory.kind=='context')).text
        assert logged==spec['prompt']
        checkpoint=json.loads(db.get(Run,rid).checkpoint)
        assert checkpoint['project_context']==spec['context']
        assert checkpoint['project_origin']==spec['origin']
        for ref in spec['context']['memory_refs']:
            entry=next(r for r in payload['accepted_memory'] if r['id']==ref['id'])
            assert ref['sha256']==digest(entry['text'])
    finish(app,ids['d'],'Join completed with all upstream outputs.');advance(app);advance(app)
    q=c.get('/api/projects/1').json();assert q['state']=='complete'
    assert len([m for m in q['memory'] if m['kind']=='handoff'])==4


@pytest.mark.parametrize('stage',['failed','timeout','cancelled','awaiting_approval'])
def test_failed_or_blocked_root_halts_transitive_dependents_with_visible_reason(app,stage):
    p=active(app,[node('a'),node('b',depends_on=['a']),node('c',depends_on=['a']),node('d',depends_on=['b','c'])])
    c,s,wd,settings=app;ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    assert policy_request(c,p).status_code==200
    finish(app,ids['a'],'Upstream stopped.',stage=stage,error='Synthetic upstream stop')
    d=Dispatcher(s,settings);assert d._claim(4)==[]
    q=c.get('/api/projects/1').json()
    for key in ['b','c','d']:
        task=next(t for t in q['tasks'] if t['node_key']==key)
        assert ids['a'] in task['blocked_by']
        assert any(b['card_id']==ids['a'] and stage in b['reason'] for b in task['blocked_reasons'])
    with s() as db:
        assert projects.claim_context(db,db.get(Card,ids['d'])) is None
        assert not list(db.scalars(select(Run).where(Run.card_id.in_([ids[k] for k in ['b','c','d']]))))
    if stage=='failed':
        assert c.post(f'/api/projects/1/stories/{ids["a"]}/retry',json={'revision':1}).status_code==200
        assert [x[0]['id'] for x in d._claim(4)]==[ids['a']]
        finish(app,ids['a'],'Root repaired and checked.')
        assert [x[0]['id'] for x in d._claim(4)]==[ids['b']]


def test_done_column_alone_and_stale_handoff_cannot_release_a_story(app):
    p=active(app,[node('a'),node('b',depends_on=['a'])]);c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    with s.begin() as db: db.get(Card,ids['a']).column='done'
    assert Dispatcher(s,settings)._claim(2)==[]
    rid=finish(app,ids['a'],'Verified first result.')
    assert c.post(f'/api/projects/1/stories/{ids["a"]}/accept',json={'run_id':rid,'summary':'Accepted first result.'}).status_code==200
    finish(app,ids['a'],'Newer result failed.',stage='failed',error='Synthetic failure')
    with s.begin() as db: db.get(Card,ids['a']).column='done'
    assert Dispatcher(s,settings)._claim(2)==[]
    task=next(t for t in c.get('/api/projects/1').json()['tasks'] if t['node_key']=='b')
    assert 'latest run has not succeeded' in task['blocked_reasons'][0]['reason']


def test_approved_dag_still_blocks_if_a_board_dependency_edge_is_missing(app):
    from models import CardDependency
    p=active(app,[node('a'),node('b',depends_on=['a'])]);c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    with s.begin() as db:
        db.delete(db.get(CardDependency,(ids['b'],ids['a'])))
        assert projects.claim_context(db,db.get(Card,ids['b'])) is None
    task=next(t for t in c.get('/api/projects/1').json()['tasks'] if t['node_key']=='b')
    assert task['blocked_by']==[ids['a']]
    assert [x[0]['id'] for x in Dispatcher(s,settings)._claim(4)]==[ids['a']]


def test_shared_memory_round_trip_through_adapter_and_automatic_dispatch(app):
    import asyncio
    from tests.test_dispatcher_adapter_bridge import StubAdapter
    class RecordingAdapter(StubAdapter):
        async def result(self,run_id):
            result=await super().result(run_id)
            result['result_text']='Synthetic artifact completed and checked.'
            result['model']['reported']='gpt-6.1-sol'
            return result
    p=active(app,[node('a'),node('b',depends_on=['a'])]);c,s,wd,settings=app
    assert policy_request(c,p).status_code==200
    with s.begin() as db: projects.memory(db,db.get(Project,p['id']),'decision','Shared operator decision.','operator')
    adapter=RecordingAdapter();d=Dispatcher(s,settings,adapters={'codex':adapter})
    async def run():
        assert await d.tick()==1
        await asyncio.gather(*d._tasks.values())
        assert await d.tick()==1
        await asyncio.gather(*d._tasks.values())
        assert await d.tick()==0
    asyncio.run(run())
    assert c.get('/api/projects/1').json()['state']=='complete'
    assert len(adapter.specs)==2
    downstream=adapter.specs[1]
    assert 'Shared operator decision.' in downstream['prompt']
    assert 'Synthetic artifact completed and checked.' in downstream['prompt']
    assert any(r['kind']=='handoff' for r in downstream['context']['memory_refs'])
    with s() as db:
        captured=db.scalar(select(projects.ProjectMemory).where(projects.ProjectMemory.kind=='context',
            projects.ProjectMemory.run_id==int(downstream['run_id'])))
        assert captured.text==downstream['prompt']


# ------------------------------------------------------------------ context: digests, ledger file, cache-friendly order

def long_handoff(tag, n=4000):
    return (f'# {tag} handoff\n\n**Status:** done with one caveat.\n\n## Changes\n- changed module {tag}\n\n## Checks\n- pytest: 12 passed\n\n'
            + ('Filler detail line. ' * (n // 20)) + '\n\n## Remaining risks\n- {tag} needs a real device\n\n## Next-story guidance\n- start from {tag}\n')

def test_digest_keeps_status_changes_checks_and_risks_and_points_at_the_ledger():
    text = long_handoff('alpha')
    d = projects._digest(text, 700, 'ledger #9')
    assert len(d) <= 700 and d.startswith('# alpha handoff')
    for needle in ('Status', 'Changes', 'Checks', 'Remaining risks', 'Next-story guidance', 'ledger #9'):
        assert needle in d
    assert 'Filler detail line.' not in d
    assert projects._digest('short text', 700, 'ledger #1') == 'short text'
    assert len(projects._digest('x' * 5000, 300, 'ledger #2')) <= 300                     # no headings: still bounded

def test_story_context_digests_the_lineage_keeps_direct_text_and_writes_the_full_ledger(app):
    p=active(app,[node('a'),node('b',depends_on=['a']),node('c',depends_on=['b'])]);c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    with s.begin() as db:
        project=db.get(Project,1)
        projects.memory(db,project,'handoff',long_handoff('A',6000),'claude',ids['a'])
        projects.memory(db,project,'handoff',long_handoff('B',3000),'claude',ids['b'])
        projects.memory(db,project,'decision','Operator selected approved retry route for the unrelated story.','operator',ids['a'])
    with s() as db:
        raw=projects.context(db,db.get(Project,1),'c')
        payload=json.loads(raw.split('Run output is proposed evidence; operator acceptance is required.\n',1)[1])
        by_card={m['card_id']:m for m in payload['accepted_memory'] if m['kind']=='handoff'}
        assert '[digest of' in by_card[ids['a']]['text'] and len(by_card[ids['a']]['text'])<=projects.CONTEXT_DIGEST_LIMIT     # earlier story: digest
        assert len(by_card[ids['b']]['text'])>projects.CONTEXT_DIGEST_LIMIT                                                    # direct prerequisite: fuller text
        assert payload['memory_compaction']['digested']>=1
        path=Path(payload['memory_compaction']['full_ledger'])
        assert path.is_file() and path.stat().st_mode & 0o777==0o600 and path.parent.name=='project-ledgers'
        ledger=path.read_text()
        assert 'Filler detail line.' in ledger and ledger.count('# A handoff')==1 and ledger.count('# B handoff')==1            # nothing omitted there
        assert ledger.startswith('<!-- last_id:')
        before=path.stat().st_mtime_ns; projects.context(db,db.get(Project,1),'c'); assert path.stat().st_mtime_ns==before        # rewritten only when it changed

def test_prompt_puts_the_stable_parts_first_and_the_story_last(app):
    p=active(app,[dict(node('a'),title='Story A'),dict(node('b'),title='Story B')]);c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    with s() as db:
        pa=projects.claim_context(db,db.get(Card,ids['a']))
        # RCD holds a sequential story until its predecessor is accepted, so the second prompt is built the
        # way the claim builds it: the shared context first, the story's own text last.
        pb=projects.context(db,db.get(Project,1),'b',db.get(Card,ids['b']).working_dir)+'\n\nYOUR STORY (do this now)\n'+db.get(Card,ids['b']).body
        bodies={ids['a']:db.get(Card,ids['a']).body.rstrip(),ids['b']:db.get(Card,ids['b']).body.rstrip()}
    for prompt,card in ((pa,ids['a']),(pb,ids['b'])):
        assert prompt.index('YOUR STORY (do this now)')>prompt.index('"brief"')>prompt.index('MCD SHARED PROJECT CONTEXT')
        assert bodies[card] and prompt.rstrip().endswith(bodies[card])                              # the story's own text is last
    shared=0
    for x,y in zip(pa,pb):
        if x!=y:break
        shared+=1
    assert shared>2000 and shared>len(pa)*0.4                                                    # a long shared prefix for prompt caching

def test_story_context_drops_unrelated_decisions_but_keeps_lineage_and_recent_global_ones(app):
    p=active(app,[node('a'),node('b',depends_on=['a']),node('other')]);c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    with s.begin() as db:
        project=db.get(Project,1)
        for i in range(8):projects.memory(db,project,'decision',f'Other story decision {i}','operator',ids['other'])
        projects.memory(db,project,'decision','Lineage decision for story A.','operator',ids['a'])
        for i in range(6):projects.memory(db,project,'decision',f'Global decision {i}','operator')
    with s() as db:
        raw=projects.context(db,db.get(Project,1),'b')
    assert 'Lineage decision for story A.' in raw
    assert 'Global decision 5' in raw and 'Global decision 4' in raw and 'Global decision 3' in raw and 'Global decision 0' not in raw
    assert 'Other story decision 0' not in raw


def test_prerequisite_integration_works_without_cherry_pick_empty_drop(app,monkeypatch):
    """Older git (2.43 on Ubuntu 24.04, 2.39 on Raspberry Pi OS) has no `cherry-pick --empty=drop`: the
    integration must not rely on it, and a commit the story already holds is skipped, not an error."""
    import project_workspaces
    c,s,wd,settings=app;init_repo(wd)
    real=project_workspaces.git
    def old_git(path,*args):
        if '--empty=drop' in args: raise HTTPException(409,'unknown option')
        return real(path,*args)
    monkeypatch.setattr(project_workspaces,'git',old_git)
    git(wd,'checkout','-q','-b','story');(wd/'a.txt').write_text('a');git(wd,'add','.');git(wd,'commit','-m','a')
    commit=git(wd,'rev-parse','HEAD');git(wd,'checkout','-q','codex/test-project')
    included,head=project_workspaces.prepare(wd,[{'commits':[commit]}],[])
    assert included==[commit] and (wd/'a.txt').read_text()=='a'
    # the same commit again is already present: it becomes empty and is dropped without an error
    included,head2=project_workspaces.prepare(wd,[{'commits':[commit]}],[])
    assert included==[commit] and head2==head

@pytest.mark.parametrize('agent', ['claude','codex','grok','hermes','openclaw'])
def test_delegator_pipeline_keeps_assigned_agent_and_model_during_role_change(app, monkeypatch, agent):
    monkeypatch.setattr(projects.RoleStore, 'delegator', lambda self: agent)
    p=new(app); client=app[0]
    response=client.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True})
    assert response.status_code == 200, response.text
    p=response.json(); route=p['pipeline']['delegator']
    with app[1]() as db:
        assert db.get(Card,p['pipeline']['card_id']).agent == agent
    selected=p['pipeline']['choices'][0]
    finish(app,p['pipeline']['card_id'],json.dumps({**selected,'rationale':'test choice'}));advance(app)
    p=client.get('/api/projects/1').json()
    monkeypatch.setattr(projects.RoleStore, 'delegator', lambda self: 'codex' if agent != 'codex' else 'claude')
    finish(app,p['pipeline']['card_id'],json.dumps({'nodes':[node('story')]}));advance(app)
    p=client.get('/api/projects/1').json()
    assert p['pipeline']['delegator'] == route
    # Automatic planning pins its selected planner as the separate return reviewer.
    # A later global Coordinator role change cannot replace either assignment.
    assert p['pipeline']['reviewer'] == selected
    with app[1]() as db:
        card=db.get(Card,p['pipeline']['card_id'])
        assert card.agent == selected['agent']
        assert (card.model or '') == selected['model']

def test_free_only_setup_can_plan_with_hermes_without_subscription_clis(app, monkeypatch, tmp_path):
    monkeypatch.setattr(AgentSpec, 'available', lambda self, settings: self.id == 'hermes')
    config=tmp_path/'free-hermes.yaml';config.write_text('model:\n  default: openrouter/free\n')
    app[3].hermes_config_path=config
    p=new(app);client=app[0]
    response=client.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True})
    assert response.status_code == 200, response.text
    p=response.json()
    assert p['pipeline']['choices'] == [{'agent':'hermes','model':'openrouter/free'}]
    assert p['pipeline']['delegator'] == {'agent':'hermes','model':'openrouter/free'}
    with app[1]() as db:
        card=db.get(Card,p['pipeline']['card_id'])
        assert card.agent == 'hermes' and card.model == 'openrouter/free'


def test_assignment_change_requires_new_operator_coordination_review(app, monkeypatch):
    store=projects.RoleStore(app[3]);store.folder.mkdir(parents=True)
    store.state.write_text(json.dumps({'roles':{'codex':'delegator'},'workspace':'','targets':[]}))
    p=new(app);client=app[0]
    response=client.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True,'delegator_revision':'a'*64})
    assert response.status_code == 409
    assert 'assignment changed' in response.json()['detail']
    response=client.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True,'delegator_revision':store.status()['revision']})
    assert response.status_code == 200, response.text
    assert response.json()['pipeline']['delegator']['agent'] == 'codex'

def test_paused_project_can_retier_only_unstarted_subscription_stories(app):
    claude = dict(node('claude-work'), assignee='claude', model='claude-opus-5-5')
    human = dict(node('human-review'), assignee='human', model='')
    p = active(app, [node('codex-work'), claude, human]); c, sessions, _, _ = app
    assert c.post('/api/projects/1/retier', json={
        'revision': 1, 'claude_model': 'claude-haiku-5-5', 'codex_model': 'gpt-6-luna', 'acknowledge': True,
    }).status_code == 409
    p = c.post('/api/projects/1/pause', json={'revision': 1}).json()
    running = next(t for t in p['tasks'] if t['node_key'] == 'codex-work')
    with sessions.begin() as db:
        db.get(Card, running['card_id']).column = 'running'
    response = c.post('/api/projects/1/retier', json={
        'revision': 1, 'claude_model': 'claude-haiku-5-5', 'codex_model': 'gpt-6-luna', 'acknowledge': True,
    })
    assert response.status_code == 200, response.text
    p = response.json(); tasks = {t['node_key']: t for t in p['tasks'] if t['role'] == 'story'}
    assert tasks['codex-work']['model'] == 'gpt-6.1-sol'
    assert tasks['claude-work']['model'] == 'claude-haiku-5-5'
    assert tasks['human-review']['model'] is None
    assert p['state'] == 'paused' and p['document']['planning_bias'] == 50
    with sessions() as db:
        manifest = json.loads(db.get(Project, 1).approved_manifest)
        assert manifest['fallback_models'] == {'claude': 'claude-haiku-5-5', 'codex': 'gpt-6-luna'}
        assert manifest['route_amendments'][-1]['cards'][0]['card_id'] == tasks['claude-work']['card_id']

def test_retier_requires_operator_acknowledgement(app):
    p = active(app, [node('work')]); c = app[0]
    c.post('/api/projects/1/pause', json={'revision': p['revision']})
    response = c.post('/api/projects/1/retier', json={
        'revision': p['revision'], 'claude_model': 'claude-haiku-5-5', 'codex_model': 'gpt-6-luna',
    })
    assert response.status_code == 422

def test_incomplete_read_story_can_be_repaired_as_execution_only_while_paused(app):
    p = active(app, [dict(node('matrix'), mode='read')]); c, sessions, _, _ = app
    c.post('/api/projects/1/pause', json={'revision': 1})
    c.post('/api/projects/1/retier', json={
        'revision': 1, 'claude_model': 'claude-haiku-5-5', 'codex_model': 'gpt-6-luna', 'acknowledge': True,
    })
    with sessions.begin() as db: db.get(Project, 1).state = 'active'
    card_id = next(t['card_id'] for t in c.get('/api/projects/1').json()['tasks'] if t['role'] == 'story')
    finish(app, card_id, 'Task is not complete. Tests were NOT EXECUTED and nothing was implemented.')
    c.post('/api/projects/1/pause', json={'revision': 1})
    response = c.post(f'/api/projects/1/stories/{card_id}/repair-execution', json={'revision': 1, 'acknowledge': True})
    assert response.status_code == 200, response.text
    task = next(t for t in response.json()['tasks'] if t['card_id'] == card_id)
    assert (task['column'], task['agent'], task['model'], task['mode']) == ('queued', 'codex', 'gpt-6-luna', 'edit')
    assert response.json()['state'] == 'paused'
    with sessions() as db:
        manifest = json.loads(db.get(Project, 1).approved_manifest)
        node_data = next(n for n in manifest['document']['nodes'] if n['key'] == 'matrix')
        assert node_data['mode'] == 'edit'
        assert manifest['route_amendments'][-1]['kind'] == 'repair_incomplete_execution'

def free_config(settings):
    settings.openclaw_config_path.write_text(json.dumps({'agents':{'defaults':{'models':{
        'openrouter/example/code:free':{},'openrouter/google/gemini-2.5-flash':{},'other/free:free':{}}},
        'list':[{'id':'mm-developer'}]}}))
    return {'agent':'openclaw','model':'openrouter/example/code:free','agent_target':'mm-developer'}

def test_go_free_approves_only_same_story_and_pins_free_model(app):
    p=active(app,[node('a'),node('b',depends_on=['a'])]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    rid=finish(app,cid,'Unverified edits remain.',stage='failed',error="You've hit your session limit")
    route=free_config(settings)
    before=c.get(f'/api/cards/{cid}').json()
    detail=c.get('/api/projects/1').json()
    assert next(t for t in detail['tasks'] if t['card_id']==cid)['free_retry_routes']==[route]
    with s() as db: original=json.loads(db.get(Project,1).approved_manifest)
    data={'revision':1,'run_id':rid,'model':route['model'],'agent_target':route['agent_target']}
    url=f'/api/projects/1/stories/{cid}/go-free'
    r=c.post(url,json=data);assert r.status_code==200,r.text
    after=c.get(f'/api/cards/{cid}').json()
    assert (after['agent'],after['model'],after['agent_target'],after['column'])==('openclaw',route['model'],'mm-developer','queued')
    for key in ('body','working_dir','mode','acceptance','approved_at'): assert before[key]==after[key]
    assert len(r.json()['tasks'])==len(detail['tasks'])
    assert next(t for t in r.json()['tasks'] if t['node_key']=='b')['blocked_by']==[cid]
    with s() as db:
        m=json.loads(db.get(Project,1).approved_manifest)
        assert m['hash']==original['hash'] and m['document']==original['document']
        assert m['free_retries']['a']['source_run_id']==rid
    assert c.post(url,json=data).status_code==409  # double click cannot create a duplicate
    claimed=Dispatcher(s,settings)._claim(2)
    assert len(claimed)==1 and claimed[0][0]['id']==cid
    argv=claimed[0][0]['argv'];assert argv[argv.index('--model')+1]==route['model']
    assert 'MCD GO FREE' in argv[argv.index('-m')+1]
    finish(app,cid,stage='failed',error='429 rate limit')
    assert c.get(f'/api/cards/{cid}').json()['column']=='failed'  # never silently escalates
    assert Dispatcher(s,settings)._claim(2)==[]
    assert 'Unverified edits remain.' in c.get('/api/projects/1/context').text

@pytest.mark.parametrize('change,code', [('paid',422),('stale_run',409),('stale_revision',409),('paused',409),('removed_target',422),('uninstalled',422),('ordinary_failure',409)])
def test_go_free_rejects_unapproved_or_stale_requests(app,monkeypatch,change,code):
    p=active(app,[node('a')]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    rid=finish(app,cid,stage='failed',error='test failed' if change=='ordinary_failure' else 'usage limit reached')
    route=free_config(settings)
    data={'revision':1,'run_id':rid,'model':route['model'],'agent_target':route['agent_target']}
    if change=='paid': data['model']='openrouter/google/gemini-2.5-flash'
    if change=='stale_run': data['run_id']=999
    if change=='stale_revision': data['revision']=2
    if change=='paused': c.post('/api/projects/1/pause',json={'revision':1})
    if change=='removed_target': settings.openclaw_config_path.write_text('{}')
    if change=='uninstalled': monkeypatch.setattr(AgentSpec,'available',lambda self,settings:False)
    r=c.post(f'/api/projects/1/stories/{cid}/go-free',json=data);assert r.status_code==code,r.text
    after=c.get(f'/api/cards/{cid}').json();assert after['agent']=='codex' and after['column']=='failed'

def test_go_free_revalidates_native_configuration_before_claim(app):
    p=active(app,[node('a')]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    rid=finish(app,cid,stage='failed',error='usage limit reached');route=free_config(settings)
    r=c.post(f'/api/projects/1/stories/{cid}/go-free',json={'revision':1,'run_id':rid,'model':route['model'],'agent_target':route['agent_target']})
    assert r.status_code==200,r.text
    settings.openclaw_config_path.write_text('{}')
    assert Dispatcher(s,settings)._claim(2)==[]
    assert c.get(f'/api/cards/{cid}').json()['column']=='failed'
    assert 'no longer configured' in c.get('/api/projects/1').json()['error']


def test_project_model_lock_stops_quota_handoff_and_can_be_disabled(app):
    p=active(app,[node('a',routes=[{'agent':'claude','model':'claude-sonnet-5-5'}]),node('b',depends_on=['a'])])
    c,s,wd,settings=app
    assert p['model_lock'] is False
    endpoint=f"/api/projects/{p['id']}/model-lock"
    assert c.post(endpoint,json={'revision':2,'enabled':True}).status_code==409
    assert c.post(endpoint,json={'revision':1,'enabled':'true'}).status_code==422
    locked=c.post(endpoint,json={'revision':1,'enabled':True})
    assert locked.status_code==200 and locked.json()['model_lock'] is True
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    d=Dispatcher(s,settings);assert len(d._claim(2))==1
    finish(app,cid,'Partial work',stage='failed',error='usage limit reached')
    card=c.get(f'/api/cards/{cid}').json()
    assert (card['agent'],card['model'],card['column'])==('codex','gpt-6.1-sol','failed')
    assert d._claim(2)==[]
    assert 'enabled project model lock' in c.get('/api/projects/1/context').text
    assert c.post(endpoint,json={'revision':1,'enabled':False}).json()['model_lock'] is False
    assert c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1}).status_code==200
    assert len(d._claim(2))==1
    finish(app,cid,stage='failed',error='usage limit reached')
    card=c.get(f'/api/cards/{cid}').json()
    assert card['agent']=='claude' and card['column']=='queued'


def test_project_model_lock_disables_transport_retry_and_preclaim_rerouting(app):
    import time
    from models import ProviderLimit
    from agents import RunMeta
    p=active(app,[node('a',routes=[{'agent':'claude','model':'claude-sonnet-5-5'}])])
    c,s,wd,settings=app;cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    assert c.post('/api/projects/1/model-lock',json={'revision':1,'enabled':True}).status_code==200
    with s.begin() as db:
        db.add(ProviderLimit(provider='codex',detected_at=int(time.time()),last_seen_at=int(time.time()),lift_at=int(time.time())+3600,rerouting=True,handoffs=0,rerouted=0))
        db.get(Card,cid).max_attempts=3
    d=Dispatcher(s,settings);assert len(d._claim(1))==1
    with s() as db:
        card=db.get(Card,cid);run=db.scalar(select(Run).where(Run.card_id==cid))
        assert card.agent=='codex' and run.agent=='codex'
        rid=run.id
    d._finish(rid,cid,'failed',1,'HTTP 503 service unavailable',RunMeta(),.1)
    with s() as db:
        card=db.get(Card,cid)
        assert card.column=='failed' and card.retry_after is None and card.agent=='codex'
        assert db.scalar(select(ProviderLimit)).rerouted==0


def test_model_lock_requires_submitted_project(app):
    p=new(app)
    assert app[0].post(f"/api/projects/{p['id']}/model-lock",json={'revision':1,'enabled':True}).status_code==409


def test_model_lock_stops_interruption_requeue(app):
    import time
    p=active(app,[node('a')]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    c.post('/api/projects/1/model-lock',json={'revision':1,'enabled':True})
    d=Dispatcher(s,settings);assert len(d._claim(1))==1
    with s.begin() as db:
        run=db.scalar(select(Run).where(Run.card_id==cid));run.stage='interrupted'
        d._requeue_or_fail(db,run,int(time.time()))
        assert db.get(Card,cid).column=='failed'


# ------------------------------------------------------------------------------------- replanning and the standards message
def _planner_text(app, fresh):
    c, s, wd, settings = app
    p = new(app, [node('a', description='UNIQUE-EXISTING-STORY-TEXT')])
    pid = p['id']
    r = c.post(f'/api/projects/{pid}/plan', json={'revision': 1, 'approve_coordination': True, 'fresh': fresh}).json()
    assert r['pipeline']['fresh'] is fresh
    selected = next(v for v in r['pipeline']['choices'] if v['agent'] == 'codex')
    finish(app, r['pipeline']['card_id'], json.dumps({**selected, 'rationale': 'Fit'}))
    advance(app)
    nxt = c.get(f'/api/projects/{pid}').json()
    assert nxt['pipeline']['step'] == 'plan'
    with s() as db:
        return db.get(Card, nxt['pipeline']['card_id']).body


def test_planning_from_scratch_does_not_show_the_planner_the_stories_it_would_repeat(app):
    """A free planner given the old stories returned them unchanged even after the brief and working directory changed."""
    assert 'UNIQUE-EXISTING-STORY-TEXT' in _planner_text(app, False)


def test_the_standards_message_lists_each_problem_on_its_own_line_and_the_allowed_areas_once():
    std = {'source': 'repository', 'property': 'site', 'areas': [{'slug': 'user-interface'}, {'slug': 'tests-only'}]}
    broken = ["a: area 'x' is not one of this repository's areas", "b: area 'y' is not one of this repository's areas", 'c: risk low is below the standards minimum high for area tests-only']
    text = projects.standards_message(std, broken)
    lines = text.split('\n')
    assert lines[0] == 'This plan breaks the repository standards (site):' and lines[1:4] == ['- ' + b for b in broken]
    assert text.count('Areas these standards list:') == 1 and 'tests-only, user-interface' in text
    only_risk = projects.standards_message(std, broken[2:])
    assert 'Areas these standards list' not in only_risk                       # the list only appears when an area is the problem


def test_the_project_reports_what_its_plan_breaks_before_anyone_submits(app):
    c = app[0]
    clean = new(app, [node('a')])
    assert clean['standards_check']['problems'] == []
    low = new(app, [node('b', area='authentication-and-sessions', risk='low')])
    found = low['standards_check']
    assert found['source'] == 'starter' and any('b: risk low is below the standards minimum high' in x for x in found['problems'])
    assert new(app)['standards_check'] is None                                  # no stories, nothing to check
    refused = c.post(f'/api/projects/{low["id"]}/submit', json={'revision': 1, 'approve_coordination': True, 'approve_api_work': True})
    assert refused.status_code == 422 and refused.json()['detail'].startswith('This plan breaks the starter standards:\n- b: risk low')


def test_the_planner_prompt_omits_the_current_stories_when_planning_from_scratch(app):
    assert 'UNIQUE-EXISTING-STORY-TEXT' not in _planner_text(app, True)


def test_a_phase_key_or_a_repeated_key_in_hermes_dispatch_order_is_ignored_and_a_real_problem_falls_back():
    stories={k:{'depends_on':d} for k,d in (('a',[]),('b',['a']),('c',['b']))}
    nodes=[{'key':'ph','kind':'phase','depends_on':[]},*({'key':k,'kind':'story','depends_on':v['depends_on']} for k,v in stories.items())]
    got,note=projects.usable_dispatch_order(['ph','a','b','b','c'],stories,nodes)
    assert got==['a','b','c'] and 'ignored keys that are not stories: ph' in note and 'repeated' in note             # the 2026-10-16 failure: a phase listed among the stories
    assert projects.usable_dispatch_order(['a','b','c'],stories,nodes)==(['a','b','c'],None)
    for bad in (['a','c'],['c','b','a'],'nonsense',None,['x','y']):
        got,note=projects.usable_dispatch_order(bad,stories,nodes)
        assert got==['a','b','c'] and 'could not be used' in note


def test_a_failed_openclaw_story_gets_other_free_models_and_cannot_pick_the_one_that_just_failed(app):
    n=dict(node('a'),assignee='openclaw',model='openrouter/example/code:free',agent_target='mm-developer')
    p=active(app,[n]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    route=free_config(settings)
    settings.openclaw_config_path.write_text(json.dumps({'agents':{'defaults':{'models':{
        'openrouter/example/code:free':{},'openrouter/other/model:free':{}}},'list':[{'id':'mm-developer'}]}}))
    rid=finish(app,cid,'',stage='failed',error='OpenClaw provider timed out: the gateway reported an LLM request timeout.')
    task=next(t for t in c.get('/api/projects/1').json()['tasks'] if t['card_id']==cid)
    assert [r['model'] for r in task['free_retry_routes']]==['openrouter/other/model:free']                 # not the model that just timed out
    same=c.post(f'/api/projects/1/stories/{cid}/go-free',json={'revision':1,'run_id':rid,'model':route['model'],'agent_target':'mm-developer'})
    assert same.status_code==422 and 'different free model' in same.json()['detail']
    ok=c.post(f'/api/projects/1/stories/{cid}/go-free',json={'revision':1,'run_id':rid,'model':'openrouter/other/model:free','agent_target':'mm-developer'})
    assert ok.status_code==200,ok.text
    assert next(t for t in ok.json()['tasks'] if t['card_id']==cid)['model']=='openrouter/other/model:free'


def test_a_failed_story_can_be_retried_on_a_low_cost_subscription_model_and_optionally_in_edit_mode(app):
    n=dict(node('a'),assignee='openclaw',model='openrouter/example/code:free',agent_target='mm-developer',mode='read')
    p=active(app,[n]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    rid=finish(app,cid,'',stage='failed',error='OpenClaw provider timed out')
    task=next(t for t in c.get('/api/projects/1').json()['tasks'] if t['card_id']==cid)
    assert {'agent':'claude','model':'claude-haiku-5-5'} in task['low_cost_routes'] and {'agent':'codex','model':'gpt-6-luna'} in task['low_cost_routes']
    base={'revision':1,'run_id':rid,'agent':'codex'}
    assert c.post(f'/api/projects/1/stories/{cid}/low-cost-retry',json={**base,'run_id':rid+99}).status_code==409                   # only the current failed run
    assert c.post(f'/api/projects/1/stories/{cid}/low-cost-retry',json={**base,'edit_mode':True}).status_code==422                  # edit mode needs acknowledgement
    ok=c.post(f'/api/projects/1/stories/{cid}/low-cost-retry',json={**base,'edit_mode':True,'acknowledge':True})
    assert ok.status_code==200,ok.text
    t=next(t for t in ok.json()['tasks'] if t['card_id']==cid)
    assert (t['column'],t['agent'],t['model'],t['mode'])==('queued','codex','gpt-6-luna','edit')
    with s() as db:
        m=json.loads(db.get(Project,1).approved_manifest)
        assert m['cost_retries']['a']['route']=={'agent':'codex','model':'gpt-6-luna'} and m['route_amendments'][-1]['kind']=='low_cost_retry'
        assert next(x for x in m['document']['nodes'] if x['key']=='a')['mode']=='edit'
        assert {'agent':'codex','model':'gpt-6-luna'} in projects.approved_story_routes(db.get(Project,1),projects.binding(db,cid))
        from models import ProjectMemory
        assert db.scalar(select(ProjectMemory).where(ProjectMemory.text.like('%low-cost subscription route%')))


def test_a_failed_story_can_be_retried_on_a_paid_model_only_with_acknowledgement_and_for_that_story(app):
    n=dict(node('a'),assignee='openclaw',model='openrouter/example/code:free',agent_target='mm-developer')
    p=active(app,[n,node('b',depends_on=['a'])]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    free_config(settings)
    rid=finish(app,cid,'',stage='failed',error='OpenClaw provider timed out')
    task=next(t for t in c.get('/api/projects/1').json()['tasks'] if t['card_id']==cid)
    paid='openrouter/google/gemini-2.5-flash'
    assert [r['model'] for r in task['paid_retry_routes']]==[paid]                                          # configured, not free, not the Google BYOK list
    base={'revision':1,'run_id':rid,'model':paid,'agent_target':'mm-developer'}
    assert c.post(f'/api/projects/1/stories/{cid}/pay-retry',json=base).status_code==422                   # needs acknowledgement
    assert c.post(f'/api/projects/1/stories/{cid}/pay-retry',json={**base,'acknowledge':True,'model':'openrouter/example/code:free'}).status_code==422   # a free model is not a paid one
    assert c.post(f'/api/projects/1/stories/{cid}/pay-retry',json={**base,'acknowledge':True,'run_id':rid+9}).status_code==409
    ok=c.post(f'/api/projects/1/stories/{cid}/pay-retry',json={**base,'acknowledge':True})
    assert ok.status_code==200,ok.text
    t=next(t for t in ok.json()['tasks'] if t['card_id']==cid)
    assert (t['column'],t['agent'],t['model'])==('queued','openclaw',paid)
    with s() as db:
        from models import ProjectMemory
        m=json.loads(db.get(Project,1).approved_manifest)
        assert m['paid_retries']['a']['route']=={'agent':'openclaw','model':paid} and m['route_amendments'][-1]['kind']=='paid_retry'
        assert {'agent':'openclaw','model':paid} in projects.approved_story_routes(db.get(Project,1),projects.binding(db,cid))
        assert db.scalar(select(ProjectMemory).where(ProjectMemory.text.like('%PAID retry%')))
        assert 'paid_retries' not in m or 'b' not in m['paid_retries']                                      # only this story


def test_a_timed_out_story_is_retried_only_with_an_explicit_acknowledgement_and_then_really_dispatches(app):
    """2026-10-16: after a provider timeout every retry was silently re-failed by the dispatcher; the operator had no way to authorize one."""
    from models import RunEvent
    n=dict(node('a'),assignee='openclaw',model='openrouter/example/code:free',agent_target='mm-developer')
    c,s,wd,settings=app;init_repo(wd)
    p=active(app,[n])
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    rid=finish(app,cid,'',stage='timeout',error='OpenClaw provider timed out')
    r=c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1})
    assert r.status_code==422 and 'timed out' in r.json()['detail']                                      # no silent re-fail: the operator is told what to confirm
    ok=c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1,'acknowledge_timeout':True})
    assert ok.status_code==200,ok.text
    with s() as db:
        ev=[e.text for e in db.scalars(select(RunEvent).where(RunEvent.run_id==rid,RunEvent.kind=='note'))]
        assert any(t.startswith('RETRY_AUTHORIZED') for t in ev)
    claimed=Dispatcher(s,settings)._claim(3)
    assert [a['id'] for a,_ in claimed]==[cid]                                                          # the dispatcher now starts it instead of re-failing the card


def test_an_unacknowledged_timeout_still_fails_closed_in_the_dispatcher_and_every_retry_path_needs_the_acknowledgement(app):
    n=dict(node('a'),assignee='openclaw',model='openrouter/example/code:free',agent_target='mm-developer',mode='read')
    p=active(app,[n]);c,s,wd,settings=app
    init_repo(wd)
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    free_config(settings)
    settings.openclaw_config_path.write_text(json.dumps({'agents':{'defaults':{'models':{'openrouter/example/code:free':{},'openrouter/other/model:free':{},'openrouter/google/gemini-2.5-flash':{}}},'list':[{'id':'mm-developer'}]}}))
    rid=finish(app,cid,'',stage='timeout',error='OpenClaw provider timed out')
    bodies={'go-free':{'revision':1,'run_id':rid,'model':'openrouter/other/model:free','agent_target':'mm-developer'},
        'low-cost-retry':{'revision':1,'run_id':rid,'agent':'claude'},
        'pay-retry':{'revision':1,'run_id':rid,'model':'openrouter/google/gemini-2.5-flash','agent_target':'mm-developer','acknowledge':True}}
    for path,body in bodies.items():
        r=c.post(f'/api/projects/1/stories/{cid}/{path}',json=body)
        assert r.status_code==422 and 'timed out' in r.json()['detail'],(path,r.text)
    # the dispatcher alone still refuses a timed-out story that nobody authorized
    with s.begin() as db: db.get(Card,cid).column='queued'
    assert Dispatcher(s,settings)._claim(3)==[]
    with s() as db: assert db.get(Card,cid).column=='failed'
    # with the acknowledgement a route change goes through and is recorded
    ok=c.post(f'/api/projects/1/stories/{cid}/low-cost-retry',json={**bodies['low-cost-retry'],'acknowledge_timeout':True})
    assert ok.status_code==200,ok.text


def test_a_returned_plan_cannot_leave_an_implementation_story_read_only(app):
    """2026-10-16: a free planner marked every story Read, including the ones that write and commit files; none of them could ever commit."""
    p=new(app);c=app[0]
    p=c.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True}).json()
    selected=next(v for v in p['pipeline']['choices'] if v['agent']=='codex')
    finish(app,p['pipeline']['card_id'],json.dumps({**selected,'rationale':'Fit'}));advance(app)
    p=c.get('/api/projects/1').json()
    nodes=[dict(node('impl'),work_kind='implement',mode='read'),dict(node('docs',depends_on=['impl']),work_kind='docs',mode='read'),
           dict(node('check',depends_on=['docs']),work_kind='review',mode='read')]
    finish(app,p['pipeline']['card_id'],json.dumps({'nodes':nodes}));advance(app)
    p=c.get('/api/projects/1').json()
    finish(app,p['pipeline']['card_id'],json.dumps({'nodes':nodes}));advance(app)
    p=c.get('/api/projects/1').json();assert p['state']=='review'
    modes={n['key']:n['mode'] for n in p['document']['nodes'] if n['kind']=='story'}
    assert modes=={'impl':'edit','docs':'edit','check':'read'}                                           # only the review story stays read-only
    assert any(m['kind']=='checkpoint' and 'from Read to Edit' in m['text'] for m in p['memory'])


def test_fix_implement_modes_leaves_human_review_and_edit_stories_alone():
    doc={'nodes':[{'kind':'phase','key':'p','mode':'read','work_kind':'implement'},
        {'kind':'story','key':'h','assignee':'human','mode':'read','work_kind':'implement','title':'Human'},
        {'kind':'story','key':'r','assignee':'codex','mode':'read','work_kind':'research','title':'Research'},
        {'kind':'story','key':'e','assignee':'codex','mode':'edit','work_kind':'implement','title':'Done'},
        {'kind':'story','key':'i','assignee':'claude','mode':'read','work_kind':'implement','title':'Build it'}]}
    assert projects.fix_implement_modes(doc)==['Build it']
    assert [n['mode'] for n in doc['nodes']]==['read','read','read','edit','edit']


def test_choosing_the_scratch_area_gives_the_project_its_own_private_folder_and_any_other_folder_is_kept(app):
    """A project is a button push: the default working directory is a new private scratch folder, a repository folder is an explicit choice."""
    c,s,wd,settings=app
    root=settings.data_dir/'workspaces';root.mkdir(parents=True,exist_ok=True)
    settings.workdir_roots=(wd.parent,root)
    assert c.get('/api/workdirs').json()['scratch_root']==str(root)
    mk=lambda title,dir:c.post('/api/projects',json={'title':title,'brief':'Build it.','working_dir':str(dir),'nodes':[]})
    one=mk('Simple Business Website',root);two=mk('Simple Business Website',root)
    assert one.status_code==201 and two.status_code==201,one.text
    a,b=one.json()['document']['working_dir'],two.json()['document']['working_dir']
    assert a!=b and Path(a).is_dir() and Path(b).is_dir() and Path(a).parent==root and Path(a).name.startswith('scratch-simple-business-website-')
    assert oct(Path(a).stat().st_mode & 0o777)=='0o700'
    kept=mk('Repository work',wd)                                                                         # a specific choice stays exactly as chosen
    assert kept.status_code==201 and kept.json()['document']['working_dir']==str(wd)
    assert Path(kept.json()['document']['working_dir']).name=='proj'
    # saving a draft that still names the scratch area gets a folder too; one that already has its own folder keeps it
    p=one.json()
    saved=c.patch(f'/api/projects/{p["id"]}',json={'revision':p['revision'],'document':p['document']})
    assert saved.status_code==200 and saved.json()['document']['working_dir']==a


def test_a_failed_validation_does_not_leave_an_empty_scratch_folder_behind(app):
    c,s,wd,settings=app
    root=settings.data_dir/'workspaces';root.mkdir(parents=True,exist_ok=True)
    settings.workdir_roots=(wd.parent,root)
    before=set(root.iterdir())
    r=c.post('/api/projects',json={'title':'Bad','brief':'x','working_dir':str(root),'nodes':[{'key':'a','title':'','kind':'nonsense'}]})
    assert r.status_code>=400
    assert set(root.iterdir())==before


def test_when_the_scratch_area_is_not_an_allowed_root_the_directory_is_left_alone(app):
    c,s,wd,settings=app
    settings.workdir_roots=(wd.parent,)
    assert c.get('/api/workdirs').json()['scratch_root'] is None


def test_a_closed_project_can_be_deleted_with_everything_kept_for_it_but_never_the_folder(app):
    from models import Project, ProjectMemory, ProjectTask
    p=active(app,[node('a'),node('b',depends_on=['a'])])
    c,s,wd,settings=app
    pid=p['id']
    (wd/'site.html').write_text('<p>the work</p>')
    finish(app,next(t['card_id'] for t in p['tasks'] if t['node_key']=='a'),'Done work.')
    with s.begin() as db:
        paid = db.scalar(select(Run).where(Run.card_id==next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')))
        paid.cost_usd=0.25
    path=f'/api/projects/{pid}/delete'
    assert c.post(path,json={'revision':1,'confirm':True}).status_code==409                    # active: close it first
    closed=c.post(f'/api/projects/{pid}/close',json={'revision':1,'reason':'Replanning from a new brief'})
    assert closed.status_code==200,closed.text
    rev=closed.json()['revision']
    assert c.post(path,json={'revision':rev}).status_code==422                                 # explicit confirmation required
    assert c.post(path,json={'revision':rev+7,'confirm':True}).status_code==409                # stale revision
    ledger=settings.data_dir/'project-ledgers'/f'project-{pid}.md'
    ledger.parent.mkdir(parents=True,exist_ok=True);ledger.write_text('ledger')
    outputs=settings.data_dir/'project-outputs'/f'project-{pid}'/'story-1'
    outputs.mkdir(parents=True);(outputs/'out.md').write_text('x')
    grants=settings.agent_git_grants_file
    grants.parent.mkdir(parents=True,exist_ok=True);grants.write_text(json.dumps({str(pid):{'clones':[]},'99':{'clones':[]}}))
    r=c.post(path,json={'revision':rev,'confirm':True})
    assert r.status_code==200,r.text
    assert r.json()['deleted']==pid and Path(r.json()['working_dir_kept']).resolve()==wd.resolve()
    assert (wd/'site.html').read_text()=='<p>the work</p>'                                     # the folder and its files are never touched
    assert c.get(f'/api/projects/{pid}').status_code==404
    assert pid not in [x['id'] for x in c.get('/api/projects').json()['projects']]
    with s() as db:
        from models import UsageRecord
        retained=[json.loads(r.payload) for r in db.scalars(select(UsageRecord))]
        assert any(r.get('source')=='retained accounting' and r.get('reported_cost_usd')==0.25 for r in retained)
        assert db.get(Project,pid) is None
        assert not db.scalars(select(ProjectTask).where(ProjectTask.project_id==pid)).all()
        assert not db.scalars(select(ProjectMemory).where(ProjectMemory.project_id==pid)).all()
        assert not db.scalars(select(Card).where(Card.id.in_([t['card_id'] for t in p['tasks']]))).all()
    assert not ledger.exists() and not outputs.parent.exists()
    assert json.loads(grants.read_text())=={'99':{'clones':[]}}                                 # only this project's grants go


def test_only_a_closed_or_completed_project_can_be_deleted(app):
    c,s,wd,settings=app
    draft=new(app,[node('a')])
    assert c.post(f'/api/projects/{draft["id"]}/delete',json={'revision':1,'confirm':True}).status_code==409     # close it first
    closed=c.post(f'/api/projects/{draft["id"]}/close',json={'revision':1,'reason':'Not needed'})
    assert closed.status_code==200,closed.text
    assert c.post(f'/api/projects/{draft["id"]}/delete',json={'revision':closed.json()['revision'],'confirm':True}).status_code==200
    assert c.get(f'/api/projects/{draft["id"]}').status_code==404
    live=active(app,[node('a')])
    for state in ('paused',):
        c.post(f'/api/projects/{live["id"]}/pause',json={'revision':1})
        assert c.post(f'/api/projects/{live["id"]}/delete',json={'revision':1,'confirm':True}).status_code==409
    assert c.get(f'/api/projects/{live["id"]}').status_code==200


def test_small_planner_slips_are_tidied_but_real_problems_are_still_refused(app):
    """A free planner returned a good plan with an empty route model on human stories, a blank touches entry and work_kind 'tests'; that must not
    cost the plan or another planning turn."""
    from fastapi import HTTPException
    c,s,wd,settings=app
    doc=new(app)['document']
    phase=dict(key='p',kind='phase',title='Phase',description='A phase.',parent=None,depends_on=[])
    agent=dict(node('a'),parent='p',work_kind='tests',touches=['','src/app.js'],routes=[dict(agent='claude',model='claude-sonnet-5-5'),dict(agent='claude',model='')])
    human=dict(node('h'),parent='p',assignee='human',depends_on=['a'],routes=[dict(agent='hermes',model='')],touches=[''])
    out=projects.proposal(doc,[phase,agent,human],settings)
    by={n['key']:n for n in out['nodes']}
    assert by['a']['work_kind']=='test'
    assert by['a']['touches']==['src/app.js']
    assert by['a']['routes']==[dict(agent='claude',model='claude-sonnet-5-5')]             # only the empty-model route is dropped
    assert by['h']['routes']==[] and by['h']['touches']==[]
    from pydantic import ValidationError
    with pytest.raises((HTTPException,ValidationError)):
        projects.proposal(doc,[phase,dict(agent,work_kind='nonsense')],settings)           # an unknown work kind is still refused
    with pytest.raises((HTTPException,ValidationError)):
        projects.proposal(doc,[phase,dict(agent,touches=['/etc/passwd'])],settings)        # a real path problem is still refused


UNFINISHED='**Not verified.** The static checks passed but nothing could be rendered; the browser checks did not run.'

def test_the_operator_can_accept_a_story_whose_agent_reported_it_unfinished_with_the_reason_recorded(app):
    p=active(app,[node('a'),node('b',depends_on=['a'])])
    c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    rid=finish(app,ids['a'],UNFINISHED,stage='failed',error='The agent explicitly reported unfinished work or unmet story acceptance criteria.')
    assert c.get(f'/api/cards/{ids["a"]}').json()['column']=='failed'
    path=f'/api/projects/{p["id"]}/stories/{ids["a"]}/accept-despite-report'
    assert c.post(path,json={'run_id':rid,'reason':'short'}).status_code==422                           # a real reason is required
    assert c.post(path,json={'run_id':rid+99,'reason':'Rendering is checked in the preview.'}).status_code==409    # must be the latest failed run
    r=c.post(path,json={'run_id':rid,'reason':'The browser checks cannot run in a sandbox; I will verify rendering in the preview.'})
    assert r.status_code==200,r.text
    assert c.get(f'/api/cards/{ids["a"]}').json()['column']=='done'
    memory=c.get(f'/api/projects/{p["id"]}').json()['memory']
    handoff=next(m['text'] for m in memory if m['kind']=='handoff' and m['card_id']==ids['a'])
    assert handoff.startswith("ACCEPTED BY THE OPERATOR DESPITE THE AGENT'S UNFINISHED REPORT") and 'verify rendering in the preview' in handoff and 'nothing could be rendered' in handoff
    assert any(m['kind']=='decision' and 'despite its unfinished report' in m['text'] for m in memory)
    with s() as db: assert db.get(Run,rid).stage=='failed'                                              # the run history is not rewritten
    advance(app)
    assert c.get(f'/api/cards/{ids["b"]}').json()['column']=='queued'                                    # the dependent is released
    with s() as db: assert projects.dependency_blocks(db,ids['b'])==[]                                  # and the dispatcher may start it
    assert c.post(path,json={'run_id':rid,'reason':'Already accepted, so this changes nothing.'}).status_code==200

def test_only_a_run_that_finished_and_reported_unfinished_work_can_be_accepted_this_way(app):
    p=active(app,[node('a'),node('b'),node('c',assignee='human')])
    c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    def accept(key,rid): return c.post(f'/api/projects/{p["id"]}/stories/{ids[key]}/accept-despite-report',json={'run_id':rid,'reason':'I am sure about this one.'})
    crash=finish(app,ids['a'],'',stage='failed',error='timeout after 1800s')
    assert accept('a',crash).status_code==409 and 'crashed or timed out' in accept('a',crash).text      # nothing to accept: retry it
    ok=finish(app,ids['b'],'Verified artifact ready.',stage='succeeded')
    assert accept('b',ok).status_code==409                                                              # not failed
    assert c.post(f'/api/projects/{p["id"]}/stories/{ids["c"]}/accept-despite-report',json={'run_id':1,'reason':'A human story is decided.'}).status_code==422
    assert c.post(f'/api/projects/{p["id"]}/stories/999/accept-despite-report',json={'run_id':1,'reason':'No such story here.'}).status_code==404


def test_a_reviewed_continuation_that_still_reports_unfinished_work_can_be_accepted_anyway(app):
    """Pilot 2026-10-28: an approved read-only continuation succeeded but said 'Status: incomplete', so it sat in review.
    Approve handoff refused the report and Accept anyway only took failed stories, leaving no way forward."""
    p=active(app,[node('a'),node('b',depends_on=['a'])])
    c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    rid=finish(app,ids['a'],'Status: not complete, operator acceptance required. Quota and browser capture are unverified.',stage='failed')
    with s.begin() as db:                                                                                 # what an output-continuation grant leaves behind
        db.get(Run,rid).stage='succeeded';db.get(Run,rid).error=None;db.get(Card,ids['a']).column='review'
    refused=c.post(f'/api/projects/{p["id"]}/stories/{ids["a"]}/accept',json={'run_id':rid,'summary':'Looks fine to me.'})
    assert refused.status_code==409 and 'Accept anyway' in refused.text                                  # the refusal names the way out
    task=next(t for t in c.get(f'/api/projects/{p["id"]}').json()['tasks'] if t['card_id']==ids['a'])
    assert task['column']=='review' and task['run_stage']=='succeeded' and task['incomplete_reason']
    r=c.post(f'/api/projects/{p["id"]}/stories/{ids["a"]}/accept-despite-report',json={'run_id':rid,'reason':'Quota and preview are dashboard-owned; the report is enough.'})
    assert r.status_code==200,r.text
    assert c.get(f'/api/cards/{ids["a"]}').json()['column']=='done'
    with s() as db:
        assert db.get(Run,rid).stage=='succeeded'
        assert projects.dependency_blocks(db,ids['b'])==[]      # pilot story 16 stayed queued: the prerequisite check ignored Accept anyway


@pytest.mark.parametrize('state,column', [('active','queued'),('active','backlog'),('paused','queued')])
def test_pending_story_can_switch_subscription_without_changing_work(app, pending_subscriptions, state, column):
    app[3].dispatch_free_only=False
    p=active(app,[node('a',assignee='claude',model='claude-sonnet-5-5'),node('b',depends_on=['a'])])
    c,s,wd,settings=app;cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    with s.begin() as db:
        project=db.get(Project,p['id']);project.state=state
        card=db.get(Card,cid);card.column=column
        before=(card.body,card.mode,card.working_dir)
        original=json.loads(project.approved_manifest)['document']
    body={'revision':p['revision'],'agent':'codex','model':'gpt-6-luna',
          'expected_agent':'claude','expected_model':'claude-sonnet-5-5','acknowledge':True}
    path=f'/api/projects/{p["id"]}/stories/{cid}/route'
    assert c.post(path,json={**body,'acknowledge':False}).status_code==422
    response=c.post(path,json=body);assert response.status_code==200,response.text
    assert response.json()['state']==state
    with s() as db:
        project=db.get(Project,p['id']);card=db.get(Card,cid)
        assert (card.agent,card.model,card.column)==('codex','gpt-6-luna',column)
        assert (card.body,card.mode,card.working_dir)==before
        manifest=json.loads(project.approved_manifest)
        assert manifest['document']==original
        context=projects.context(db,project,'a')
        assert '"assignee": "codex"' in context and '"model": "gpt-6-luna"' in context
        assert manifest['route_amendments'][-1]['kind']=='queued_route_change'
        assert {'agent':'codex','model':'gpt-6-luna'} in projects.approved_story_routes(project,projects.binding(db,cid))
    assert c.post(path,json=body).status_code==409

@pytest.mark.parametrize('column', ['running','done','review','failed'])
def test_pending_route_change_refuses_started_or_finished_story(app, pending_subscriptions, column):
    p=active(app,[node('a',assignee='claude',model='claude-sonnet-5-5')]);c,s,_,_=app
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    with s.begin() as db:db.get(Card,cid).column=column
    body={'revision':p['revision'],'agent':'codex','model':'gpt-6-luna','expected_agent':'claude',
          'expected_model':'claude-sonnet-5-5','acknowledge':True}
    assert c.post(f'/api/projects/{p["id"]}/stories/{cid}/route',json=body).status_code==409


@pytest.fixture
def pending_subscriptions(monkeypatch):
    import billing
    monkeypatch.setattr(billing,'DEFAULT_ACCOUNTS',{**billing.DEFAULT_ACCOUNTS,
        'claude':{'mode':'subscription','monthly_usd':20.0},
        'codex':{'mode':'subscription','monthly_usd':20.0}})


def test_pending_route_options_respect_host_membership_policy(app,pending_subscriptions):
    c,s,_,settings=app
    assert c.patch('/api/routes/policy/cost',json={'membership':False}).status_code==200
    with s() as db:
        assert projects.pending_subscription_routes(db,settings)==[]
    assert c.patch('/api/routes/policy/cost',json={'membership':True}).status_code==200
    with s() as db:
        assert {'agent':'codex','model':'gpt-6-luna'} in projects.pending_subscription_routes(db,settings)


def test_pending_route_refuses_output_continuation(app,pending_subscriptions):
    p=active(app,[node('a',assignee='claude',model='claude-sonnet-5-5')]);c,s,_,_=app
    cid=next(t['card_id'] for t in p['tasks'] if t['node_key']=='a')
    with s.begin() as db:
        project=db.get(Project,p['id']);manifest=json.loads(project.approved_manifest)
        manifest['output_continuations']={'a':{'state':'queued'}};project.approved_manifest=json.dumps(manifest)
    response=c.post(f'/api/projects/{p["id"]}/stories/{cid}/route',json={'revision':p['revision'],
        'agent':'codex','model':'gpt-6-luna','expected_agent':'claude','expected_model':'claude-sonnet-5-5','acknowledge':True})
    assert response.status_code==409 and 'output continuation' in response.text

def test_reviewed_map_can_be_replanned_before_dispatch_and_restored(app):
    """A reviewed map has no execution to pause; revision planning remains reversible."""
    c, s, wd, settings = app
    original = new(app, [node('old-map')])
    with s.begin() as db:
        db.get(Project, original['id']).state = 'review'
    source = c.get(f'/api/projects/{original["id"]}').json()
    assert source['state'] == 'review' and not source['tasks']
    planned = c.post(f'/api/projects/{source["id"]}/replan', json={
        'revision': source['revision'], 'reason': 'Add automated preview verification before dispatch.',
        'acknowledge': True, 'approve_coordination': True}).json()
    assert planned['state'] == 'planning'
    assert planned['pipeline']['replan']['source_state'] == 'review'
    assert planned['pipeline']['replan']['source_document']['nodes'][0]['key'] == 'old-map'
    finish(app, planned['pipeline']['card_id'], json.dumps(next(v for v in planned['pipeline']['choices'] if v['agent'] == 'codex'))); advance(app)
    planned = c.get(f'/api/projects/{source["id"]}').json()
    finish(app, planned['pipeline']['card_id'], json.dumps({'nodes': [node('preview-check')]})); advance(app)
    planned = c.get(f'/api/projects/{source["id"]}').json()
    finish(app, planned['pipeline']['card_id'], json.dumps({'nodes': [node('preview-check')]})); advance(app)
    replacement = c.get(f'/api/projects/{source["id"]}').json()
    assert replacement['state'] == 'review' and replacement['revision'] == 2 and replacement['can_cancel_replan']
    restored = c.post(f'/api/projects/{source["id"]}/cancel-replan', json={'revision': replacement['revision']}).json()
    assert restored['state'] == 'review' and restored['revision'] == 1
    assert restored['document']['nodes'][0]['key'] == 'old-map'
    assert not restored['can_cancel_replan']

def test_paused_project_replan_replaces_only_unstarted_work_and_can_be_discarded(app):
    """A continuation plan is idempotent: old cards/runs survive and old queued work cannot dispatch."""
    c, s, wd, settings = app
    p = active(app, [node('old-a'), node('old-b', depends_on=['old-a'])])
    old = [t for t in p['tasks'] if t['role'] == 'story']
    paused = c.post(f'/api/projects/{p["id"]}/pause', json={'revision': p['revision']}).json()
    assert paused['state'] == 'paused'
    missing = c.post(f'/api/projects/{p["id"]}/replan', json={'revision': paused['revision'], 'reason': 'The delivery scope changed.', 'acknowledge': False, 'approve_coordination': True})
    assert missing.status_code == 422
    planned = c.post(f'/api/projects/{p["id"]}/replan', json={'revision': paused['revision'], 'reason': 'The delivery scope changed.', 'acknowledge': True, 'approve_coordination': True}).json()
    assert planned['state'] == 'planning' and planned['pipeline']['replan']['source_revision'] == 1
    # A duplicate click does not create a second planning card.
    again = c.post(f'/api/projects/{p["id"]}/replan', json={'revision': planned['revision'], 'reason': 'The delivery scope changed.', 'acknowledge': True, 'approve_coordination': True}).json()
    assert again['pipeline']['card_id'] == planned['pipeline']['card_id']
    finish(app, planned['pipeline']['card_id'], json.dumps(next(v for v in planned['pipeline']['choices'] if v['agent'] == 'codex'))); advance(app)
    planned = c.get(f'/api/projects/{p["id"]}').json()
    finish(app, planned['pipeline']['card_id'], json.dumps({'nodes': [node('new-work')]})); advance(app)
    planned = c.get(f'/api/projects/{p["id"]}').json()
    finish(app, planned['pipeline']['card_id'], json.dumps({'nodes': [node('new-work')]})); advance(app)
    proposed = c.get(f'/api/projects/{p["id"]}').json()
    assert proposed['state'] == 'review' and proposed['revision'] == 2 and proposed['can_cancel_replan']
    # The operator can keep the approved revision without deleting any history.
    restored = c.post(f'/api/projects/{p["id"]}/cancel-replan', json={'revision': 2}).json()
    assert restored['state'] == 'paused' and restored['revision'] == 1
    # Replan again and approve it: old unstarted cards are retained but cannot dispatch.
    planned = c.post(f'/api/projects/{p["id"]}/replan', json={'revision': 1, 'reason': 'The delivery scope changed.', 'acknowledge': True, 'approve_coordination': True}).json()
    finish(app, planned['pipeline']['card_id'], json.dumps(next(v for v in planned['pipeline']['choices'] if v['agent'] == 'codex'))); advance(app)
    planned = c.get(f'/api/projects/{p["id"]}').json(); finish(app, planned['pipeline']['card_id'], json.dumps({'nodes': [node('new-work')]})); advance(app)
    planned = c.get(f'/api/projects/{p["id"]}').json(); finish(app, planned['pipeline']['card_id'], json.dumps({'nodes': [node('new-work')]})); advance(app)
    proposed = c.get(f'/api/projects/{p["id"]}').json()
    dispatched = c.post(f'/api/projects/{p["id"]}/submit', json={'revision': 2, 'approve_coordination': True, 'approve_api_work': True}).json()
    finish(app, dispatched['pipeline']['card_id'], json.dumps({'order': ['new-work']})); advance(app)
    final = c.get(f'/api/projects/{p["id"]}').json()
    old_after = {t['card_id']: t for t in final['tasks'] if t['card_id'] in {x['card_id'] for x in old}}
    assert final['state'] == 'active'
    assert all(t['column'] == 'backlog' and t['superseded'] for t in old_after.values())
    active_cards = {card['id']: card for card in c.get('/api/cards').json()['cards']}
    assert all(active_cards[card_id]['superseded'] is True for card_id in old_after)
    assert all(c.get(f'/api/cards/{card_id}').json()['superseded'] is True for card_id in old_after)
    assert any(t['node_key'] == 'new-work' and t['revision'] == 2 for t in final['tasks'])


def test_media_stories_already_done_in_media_studio_are_recorded_not_asked_again(app):
    """Pilot 2026-10-29: all seven slots were published at the start, yet each generate/publish story still asked for the same handoff."""
    human=dict(assignee='human',model='',mode='read')
    p=active(app,[node('inv'),dict(node('gen',depends_on=['inv'],media_stage='generate'),**human),dict(node('pub',depends_on=['gen'],media_stage='publish'),**human),
                  node('integ',depends_on=['pub'])])
    c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    (wd/'media').mkdir(parents=True,exist_ok=True);(wd/'assets/img').mkdir(parents=True,exist_ok=True)
    (wd/'media/slots.json').write_text(json.dumps({'slots':[{'name':'hero','kind':'image','prompt':'A doorway.'}]}))
    advance(app)
    assert next(t for t in c.get('/api/projects/1').json()['tasks'] if t['node_key']=='gen')['column']!='done'      # blocked by inv, and nothing made yet
    rid=finish(app,ids['inv'],'Wrote the media inventory.')
    assert c.post(f'/api/projects/1/stories/{ids["inv"]}/accept',json={'run_id':rid,'summary':'Inventory checked.'}).status_code==200
    advance(app)
    q=c.get('/api/projects/1').json();states={t['node_key']:t['column'] for t in q['tasks'] if t['role']=='story'}
    assert states['gen']!='done' and states['pub']!='done'                                                            # unmade art is still the operator's call
    (wd/'assets/img/hero.jpg').write_bytes(b'\xff\xd8 published')
    advance(app)
    q=c.get('/api/projects/1').json();states={t['node_key']:t['column'] for t in q['tasks'] if t['role']=='story'}
    assert states['gen']=='done' and states['pub']=='done' and states['integ']!='done'
    recorded=[m['text'] for m in q['memory'] if m['kind']=='handoff' and m['text'].startswith('Recorded by MCD')]
    assert len(recorded)==2 and all('(hero)' in t and 'nothing new was generated or spent' in t for t in recorded)


def test_a_failed_host_verifier_cannot_be_accepted_as_if_it_passed(app):
    """Pilot 2026-10-29: the verifier failed (exit 1) and the human story still offered acceptance as though it had worked."""
    p=active(app,[dict(node('verify',host_action='preview-verify'),assignee='human',model='',mode='read')]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    r=c.post(f'/api/projects/1/stories/{cid}/accept',json={'summary':'Looks fine.'})
    assert r.status_code==409 and 'get a pass' in r.text                                                               # never run
    with s.begin() as db:
        projects.memory(db,db.get(projects.Project,1),'checkpoint',projects.HOST_VERIFY+'failed (exit 1).\n\n{"status": "failed"}','operator',cid)
    with s() as db: assert projects.last_host_verify(db,db.get(projects.Project,1),cid)['ok'] is False
    assert c.post(f'/api/projects/1/stories/{cid}/accept',json={'summary':'Looks fine.'}).status_code==409
    with s.begin() as db:
        projects.memory(db,db.get(projects.Project,1),'checkpoint',projects.HOST_VERIFY+'passed.\n\n{"status": "passed"}','operator',cid)
    r=c.post(f'/api/projects/1/stories/{cid}/accept',json={'summary':'Verifier passed on the host.'})
    assert r.status_code==200 and r.json()['state']=='complete',r.text


def test_an_accepted_handoff_is_not_taken_back_when_a_later_release_reads_its_report_more_strictly(app):
    """Pilot 2026-10-29: story #17 was accepted with a report that began "Story incomplete:". 0.6.84 started reading that as unfinished,
    and every story after it was silently refused by the server while the board showed nothing blocking."""
    p=active(app,[node('a'),node('b',depends_on=['a'])]);c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    rid=finish(app,ids['a'],'Created the inventory and checked it.')
    assert c.post(f'/api/projects/1/stories/{ids["a"]}/accept',json={'run_id':rid,'summary':'Accepted.'}).status_code==200
    with s.begin() as db:
        db.get(Run,rid).result_text='Story incomplete: estimates remain unverified.'     # the accepted report, as a stricter reader now sees it
    with s() as db:
        assert projects.dependency_blocks(db,ids['b'])==[]
        db.get(Run,rid)                                                                       # an unaccepted run with that report still blocks
    with s.begin() as db:
        db.query(projects.ProjectMemory).filter_by(card_id=ids['a'],kind='handoff').delete()
    with s() as db:
        assert projects.dependency_blocks(db,ids['b'])[0]['card_id']==ids['a']


def test_the_host_preview_panel_is_told_why_the_server_would_refuse_the_action(app):
    p=active(app,[node('a'),dict(node('verify',host_action='preview-verify',depends_on=['a']),assignee='human',model='',mode='read')]);c,s,wd,settings=app
    ids={t['node_key']:t['card_id'] for t in p['tasks'] if t['role']=='story'}
    (wd/'tools').mkdir(parents=True,exist_ok=True);(wd/'tools/verify-preview.sh').write_text('#!/usr/bin/env bash\necho ok\n')
    body=c.get(f'/api/projects/1/stories/{ids["verify"]}/host-preview').json()
    assert body['available'] and len(body['blocked_by'])==1 and f'#{ids["a"]}' in body['blocked_by'][0]
    assert c.post(f'/api/projects/1/stories/{ids["verify"]}/host-preview',json={'action':'verify'}).status_code==409
    rid=finish(app,ids['a'],'Done and checked.')
    c.post(f'/api/projects/1/stories/{ids["a"]}/accept',json={'run_id':rid,'summary':'Accepted.'})
    assert c.get(f'/api/projects/1/stories/{ids["verify"]}/host-preview').json()['blocked_by']==[]
