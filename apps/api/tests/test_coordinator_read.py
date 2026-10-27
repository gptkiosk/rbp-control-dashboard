"""One context contract through operator UI, paired Discord and scoped native agents."""
import json
from sqlalchemy import select
import host_readiness
import profiles
import model_profiles as mp
from models import Project, ProjectTask, Card, Run
from tests.test_profiles import paired, call, pref, signed, OWNER
from tests.test_auth import secured, begin, complete
from tests.test_agent_access import issue, agent


def make_project(c, wd):
    r=c.post('/api/projects',json={'title':'Illustrated site','brief':'Local illustrated site',
        'working_dir':str(wd),'project_type':'local-website','nodes':[]})
    assert r.status_code==201,r.text
    return r.json()


def test_context_manifest_matches_across_ui_discord_and_native_scope(secured,tmp_path,monkeypatch):
    # The context text carries live host facts; a container engine that flips between calls is not a context mismatch.
    monkeypatch.setattr(host_readiness,'check_tools',lambda settings:{'tools':[{'id':'node','installed':True},{'id':'docker','installed':True},{'id':'gh','installed':True}]})
    monkeypatch.setattr(host_readiness,'system_tools_health',lambda settings:{'checks':[{'id':'docker','ok':True}]})
    bridge,_=paired(secured,tmp_path)
    project=make_project(secured,tmp_path/'ws/proj')
    ui=secured.get('/api/projects/coordinator',params={'operation':'context','project_id':project['id']})
    remote=call(bridge,'context',project_id=project['id'])
    assert ui.status_code==remote.status_code==200
    assert ui.json()['context_manifest']==remote.json()['context_manifest']
    assert ui.json()['text']==remote.json()['text']
    _,secret=issue(secured,'read')
    native=agent(secured,secret)
    r=native.get('/api/agent-tools/coordinator',params={'operation':'context','project_id':project['id']})
    assert r.status_code==200 and r.json()['context_manifest']==ui.json()['context_manifest']
    assert 'packaged-app-delivery.md' not in r.text
    assert native.get('/api/agent-tools/coordinator',params={'operation':'task','task_id':1}).status_code==403
    assert native.post('/api/agent-tools/coordinator',json={'operation':'dispatch'}).status_code==403


def test_native_and_discord_discover_exact_capability_limits(secured,tmp_path):
    b,_=paired(secured,tmp_path)
    caps=call(b,'capabilities')
    assert caps.status_code==200
    media=next(x for x in caps.json()['workflow'] if x['feature']=='media_generate_select_publish')
    assert media['discord_actions']==[] and media['operator_link']=='/projects?view=media'
    types=call(b,'types').json()['types']
    assert {x['id'] for x in types}=={'local-website','gcp-hosted-website','gcp-hosted-app','packaged-app','other'}
    assert call(b,'status',project_id=1).status_code==403
    assert call(b,'task',task_id=1).status_code==403


def test_project_owner_and_diagnostic_permission_are_checked_before_results(secured,tmp_path):
    b,_=paired(secured,tmp_path)
    project=make_project(secured,tmp_path/'ws/proj')
    pref(secured,allow_discord_diagnostics=True)
    created=secured.post('/api/cards',json={'title':'Verify site','body':'private task','assignee_type':'human'}).json()
    cid=created['id']
    with secured.app.state.sessions.begin() as s:
        s.add(ProjectTask(card_id=cid,project_id=project['id'],revision=1,node_key='verify',role='story'))
        p=s.get(Project,project['id']);p.created_by='another@example.com'
    assert call(b,'task',task_id=cid).status_code==403
    assert call(b,'status',project_id=project['id']).status_code==403
    assert call(b,'context',project_id=project['id']).status_code==403
    assert secured.get('/api/projects/coordinator',params={'operation':'status','project_id':project['id']}).status_code==403


def test_discord_intake_preserves_the_selected_template(secured,tmp_path):
    b,_=paired(secured,tmp_path)
    result=call(b,'intake',title='Local site',brief='Build an illustrated theme switching site',project_type='local-website')
    assert result.status_code==200,result.text
    assert result.json()['document']['project_type']=='local-website'
    context=call(b,'context',project_id=result.json()['id']).json()
    assert context['context_manifest']['project_type']=='local-website'
    assert 'web-app-delivery.md' not in context['context_manifest']['guides']
    assert call(b,'intake',title='Other',brief='x',project_type='../secret').status_code==422
