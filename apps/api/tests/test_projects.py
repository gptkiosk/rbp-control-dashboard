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
    '## Handoff — incomplete verification\n\nChanges were written but require host testing.',
])
def test_direct_incomplete_handoff_language_is_not_completion(result):
    assert project_outputs.incomplete_error(SimpleNamespace(result_text=result))

@pytest.fixture
def app(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(AgentSpec,'available',lambda self,settings:True)
    client=make_client()
    config=tmp_path/'openclaw.json'
    config.write_text(json.dumps({'agents':{'list':[{'id':'mm-main'},{'id':'mm-developer'},{'id':'mm-security'}]}}))
    get_settings().openclaw_config_path=config
    with client:
        yield client,client.app.state.sessions,tmp_path/'ws/proj',get_settings()

def node(key,**kw):
    return dict(key=key,title=key,description='Implement a bounded local change.',scope='Only this story-owned file.',acceptance='Checks pass and reviewer verifies the artifact.',assignee='codex',model='gpt-6.1-sol',**kw)

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
    cid=p['pipeline']['card_id'];finish(app,cid,json.dumps({'agent':'codex','model':projects.REGISTRY['codex'].default_model() or '', 'rationale':'Fit'}));advance(app)
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
    finish(app,p['pipeline']['card_id'],json.dumps({'agent':'codex','model':projects.REGISTRY['codex'].default_model() or ''}));advance(app)
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
    p=c.get('/api/projects/2').json();assert p['state']=='dispatch_failed' and not any(t['role']=='story' for t in p['tasks'])

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
    r=c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1,'route':choice})
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
    assert c.post(path,json={'revision':1}).status_code==409


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
    assert c.post(f'/api/projects/1/stories/{cid}/retry',json={'revision':1}).status_code==200
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

def test_quota_reported_only_on_stderr_still_hands_off_without_exposing_stderr(app):
    import asyncio,sys
    from tests.test_dispatcher import FakeParser,_drain
    p=active(app,[node('a',routes=[{'agent':'claude','model':'claude-sonnet-5-5'}])]);c,s,wd,settings=app
    cid=next(t['card_id'] for t in p['tasks'] if t['role']=='story')
    def fake_build(*args): return [sys.executable,'-c',"import sys; print('usage limit reached; sensitive-debug-value',file=sys.stderr); sys.exit(1)"]
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
    d=Dispatcher(s,settings);claimed=d._claim(3)
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

@pytest.mark.parametrize('bias,phrase',[(0,'Economy / OpenClaw first'),(50,'Balanced.'),(100,'Capability / Claude and Codex first')])
def test_bias_reaches_each_planning_stage_and_reviewed_edits_win(app,bias,phrase):
    c,s,_,_=app
    c.app.state.collector=SimpleNamespace(subagents={'openclaw':{'agents':[{'id':'mm-developer','name':'Local Dev','model':'openrouter/thinkingmachines/inkling:free','secret':'must-not-propagate'}]}})
    p=new(app,planning_bias=bias)
    def prompt(cid):
        with s() as db: return db.get(Card,cid).body
    p=c.post('/api/projects/1/plan',json={'revision':1,'approve_coordination':True}).json()
    assert phrase in prompt(p['pipeline']['card_id'])
    assert {v['agent'] for v in p['pipeline']['choices']} <= {'codex','claude'}
    finish(app,p['pipeline']['card_id'],json.dumps({'agent':'codex','model':projects.REGISTRY['codex'].default_model() or ''}));advance(app)
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
    payload=json.loads(spec['prompt'].split('Run output is proposed evidence; operator acceptance is required.\n',1)[1])
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
