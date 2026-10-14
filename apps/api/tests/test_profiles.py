"""Private profiles and bounded native Discord planning; no provider turns or messages."""
import importlib.util,json,sys,time
from pathlib import Path
from types import SimpleNamespace,ModuleType
from contextvars import ContextVar
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from models import UserCredential,UserProfile,Project,ProjectDelivery,Card
from settings import get_settings
from tests.test_auth import secured,begin,complete
from tests.test_agent_access import agent,issue
from agents import AgentSpec
import profiles,projects,project_delivery,project_diagram

CHANNEL='123456789012345678';USER='234567890123456789';MESSAGE='345678901234567890'
OWNER='operator@example.com'

def signed(c):assert complete(c,begin(c)).status_code==303
def pref(c,**kw):
    data=c.get('/api/profile').json()['preferences'];data.update(kw)
    r=c.put('/api/profile',json=data);assert r.status_code==200,r.text;return r.json()
def bridge(c):
    token=profiles.bridge_token(get_settings())
    return TestClient(c.app,base_url='http://127.0.0.1:8800',client=('127.0.0.1',1111),headers={'X-Mac-Control':'1','Authorization':'Bearer '+token})
def call(b,action,**kw):return b.post('/api/hermes-projects',json={'action':action,'discord_user_id':USER,'discord_channel_id':CHANNEL,'source_message_id':MESSAGE,**kw})
def paired(c,tmp_path,**kw):
    signed(c);pref(c,discord_channel_id=CHANNEL,working_dir=str(tmp_path/'ws/proj'),**kw)
    r=c.post('/api/profile/discord/pair');assert r.status_code==200,r.text
    code=r.json()['code'];b=bridge(c);assert call(b,'pair',code=code).status_code==200
    return b,code

def test_credentials_encrypted_write_only_and_profile_isolated(secured):
    signed(secured);key='sk-or-test-secret-value-never-export'
    r=secured.put('/api/profile/credentials/openrouter',json={'value':key});assert r.status_code==200
    assert key not in r.text and key not in secured.get('/api/profile').text
    settings=get_settings();assert (settings.data_dir/'vault.key').stat().st_mode & 0o777==0o600
    with secured.app.state.sessions() as s:
        row=s.get(UserCredential,(OWNER,'openrouter'));assert key not in row.ciphertext
        assert profiles.credential(s,OWNER,'openrouter',settings)==key
    secured.post('/auth/logout');assert complete(secured,begin(secured),email='reviewer@example.com',sub='subject2').status_code==303
    assert secured.get('/api/profile').json()['credentials']==[]
    secured.delete('/api/profile/credentials/openrouter')
    with secured.app.state.sessions() as s:assert s.get(UserCredential,(OWNER,'openrouter'))

@pytest.mark.parametrize('body',[{'value':'short-secret','extra':'private-value'},{'value':['private-value']},{'value':'x'}])
def test_invalid_secret_input_never_echoes_raw_input(secured,body):
    signed(secured);r=secured.put('/api/profile/credentials/openrouter',json=body)
    assert r.status_code==422 and 'private-value' not in r.text and 'short-secret' not in r.text

def test_vault_refuses_shared_modes_symlinks_and_wrong_key(secured,tmp_path):
    signed(secured);key='sk-or-test-private'
    secured.put('/api/profile/credentials/openrouter',json={'value':key});settings=get_settings();path=settings.data_dir/'vault.key'
    path.chmod(0o644)
    assert secured.put('/api/profile/credentials/openrouter',json={'value':key}).status_code==503
    path.chmod(0o600);original=path.rename(tmp_path/'original');path.symlink_to(original)
    assert secured.put('/api/profile/credentials/openrouter',json={'value':key}).status_code==503
    path.unlink();path.write_bytes(profiles.Fernet.generate_key());path.chmod(0o600)
    with secured.app.state.sessions() as s:
        with pytest.raises(HTTPException):profiles.credential(s,OWNER,'openrouter',settings)

def test_preference_validation_appearance_and_manual_spending(secured,monkeypatch):
    signed(secured);p=secured.get('/api/profile').json();assert p['preferences']['planning_bias']==50
    assert secured.patch('/api/profile/appearance',json={'theme':'light'}).status_code==200
    assert secured.get('/api/profile').json()['preferences']['theme']=='light'
    p['preferences'].update(dashboard_origin='https://untrusted.example')
    assert secured.put('/api/profile',json=p['preferences']).status_code==422
    secured.put('/api/profile/credentials/openrouter',json={'value':'sk-or-test-private'})
    monkeypatch.setattr('openrouter_costs.fetch_key',lambda k:{'month_usd':1.25,'byok_month_usd':.30})
    r=secured.post('/api/profile/openrouter/check');assert r.json()['spending']['month_usd']==1.25
    assert 'sk-or' not in r.text

def test_pairing_consumed_channel_bound_and_expired(secured,tmp_path):
    b,code=paired(secured,tmp_path)
    assert secured.get('/api/profile').json()['discord_linked']
    assert call(b,'pair',code=code).status_code==403
    with secured.app.state.sessions() as s:
        row=s.get(UserProfile,OWNER);assert row.pair_hash is None and row.pair_expires is None
    code=secured.post('/api/profile/discord/pair').json()['code']
    assert call(b,'pair',code=code,discord_channel_id='456789012345678901').status_code==403
    with secured.app.state.sessions.begin() as s:s.get(UserProfile,OWNER).pair_expires=int(time.time())-1
    assert call(b,'pair',code=code).status_code==403
    secured.post('/api/profile/discord/unlink');assert call(b,'list').status_code==403

def test_bridge_scope_local_only_and_other_profile_refused(secured,tmp_path):
    b,_=paired(secured,tmp_path)
    assert b.get('/api/profile').status_code in {401,403}
    assert call(b,'list').status_code==200
    assert call(b,'list',discord_user_id='456789012345678901').status_code==403
    assert b.post('/api/hermes-projects',json={'action':'execute'}).status_code==422
    for headers in ({'Origin':'http://127.0.0.1:8800'},{'X-Forwarded-For':'127.0.0.1'}):
        assert b.post('/api/hermes-projects',headers=headers,json={}).status_code==403
    _,old=issue(secured);assert call(agent(secured,old),'list').status_code==401

def test_intake_questions_idempotency_revision_and_separate_approval(secured,tmp_path,monkeypatch):
    monkeypatch.setattr(AgentSpec,'available',lambda self,settings:True)
    import billing   # RCD ships free-only; planning picks a subscription agent, so this test opts in to them
    monkeypatch.setattr(billing,'DEFAULT_ACCOUNTS',{**billing.DEFAULT_ACCOUNTS,
        'claude':{'mode':'subscription','monthly_usd':20.0},'codex':{'mode':'subscription','monthly_usd':20.0}})
    b,_=paired(secured,tmp_path)
    r=call(b,'intake');assert r.json()['needs_information']==['title','brief']
    assert call(b,'intake',title='A project',brief='Build a bounded feature',request_planning=True).status_code==403
    with secured.app.state.sessions() as s:assert not s.scalars(select(Project)).all()
    pref(secured,allow_discord_planning=True)
    r=call(b,'intake',title='A project',brief='Build a bounded feature',request_planning=True)
    assert r.status_code==200,r.text;p=r.json();assert p['state']=='planning' and p['document']['planning_bias']==50
    r=call(b,'intake',title='A project',brief='Build a bounded feature',request_planning=True)
    assert r.status_code==200 and r.json()['id']==p['id']
    with secured.app.state.sessions() as s:assert len(s.scalars(select(Project)).all())==1 and len(s.scalars(select(Card)).all())==1
    assert call(b,'plan',project_id=p['id'],revision=99).status_code==409
    with secured.app.state.sessions.begin() as s:
        row=s.get(Project,p['id']);row.state='draft';d=projects.document(row);d['planner_agent']='hermes';row.document=json.dumps(d)
    assert call(b,'plan',project_id=p['id'],revision=1).status_code==403

def map_project(c,wd):
    r=c.post('/api/projects',json={'title':'Portable feature','brief':'Review a small map','working_dir':str(wd),'nodes':[
        {'key':'phase','kind':'phase','title':'Design'},
        {'key':'a','title':'Build the first bounded slice','parent':'phase','description':'Implement','scope':'a.txt','acceptance':'Pass checks'},
        {'key':'b','title':'Integrate accepted changes','parent':'phase','description':'Integrate','scope':'b.txt','acceptance':'Review artifacts','depends_on':['a']} ]})
    assert r.status_code==201,r.text
    return r.json()

def test_diagram_requires_human_request_and_creates_private_png(secured,tmp_path):
    from PIL import Image
    b,_=paired(secured,tmp_path);p=map_project(secured,tmp_path/'ws/proj')
    assert call(b,'diagram',project_id=p['id']).status_code==422
    r=call(b,'diagram',project_id=p['id'],diagram_requested=True);assert r.status_code==200,r.text
    with secured.app.state.sessions() as s:
        row=s.scalar(select(ProjectDelivery));paths=json.loads(row.images);assert row.status=='pending' and len(paths)==1
        path=Path(paths[0]);assert path.stat().st_mode & 0o777==0o600
        with Image.open(path) as im:assert im.format=='PNG' and im.width==1500
        assert 'MEDIA:' not in row.message
    assert call(b,'diagram',project_id=p['id'],diagram_requested=True).status_code==200
    with secured.app.state.sessions() as s:assert len(s.scalars(select(ProjectDelivery)).all())==1

def test_delivery_confirmed_once_uncertain_not_retried_and_disabled_held(secured,tmp_path):
    b,_=paired(secured,tmp_path);p=map_project(secured,tmp_path/'ws/proj');sessions=secured.app.state.sessions;settings=get_settings()
    with sessions.begin() as s:s.get(Project,p['id']).state='review'
    calls=[]
    def sender(to,text):calls.append((to,text));return '567890123456789012'
    messenger=project_delivery.ProjectMessenger(sessions,settings,sender)
    messenger.tick();messenger.tick();assert len(calls)==1
    with sessions.begin() as s:
        row=s.scalar(select(ProjectDelivery));assert row.status=='sent'
        assert 'Would you like a project diagram' in row.message
        doc=s.get(Project,p['id']);doc.revision+=1
    messenger.sender=lambda *args:None;messenger.tick();messenger.tick()
    with sessions() as s:assert len(s.scalars(select(ProjectDelivery).where(ProjectDelivery.status=='uncertain')).all())==1
    call(b,'diagram',project_id=p['id'],diagram_requested=True);secured.post('/api/profile/discord/unlink');messenger.tick()
    with sessions() as s:assert s.scalar(select(ProjectDelivery).where(ProjectDelivery.source_key.endswith(':diagram'))).status=='held'

def native():
    path=Path(__file__).resolve().parents[3]/'integrations/hermes/mcd-projects/__init__.py'
    spec=importlib.util.spec_from_file_location('mcd_native',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def test_native_identity_cannot_be_forged_by_arguments_or_environment(monkeypatch):
    mod=native();unset=object();context=SimpleNamespace(_UNSET=unset,_VAR_MAP={})
    for name,value in [('PLATFORM','discord'),('USER_ID',USER),('CHAT_ID',CHANNEL),('MESSAGE_ID',MESSAGE)]:
        var=ContextVar(name,default=unset);context._VAR_MAP['HERMES_SESSION_'+name]=var
        monkeypatch.setenv('HERMES_SESSION_'+name,value)
    gateway=ModuleType('gateway');gateway.session_context=context;monkeypatch.setitem(sys.modules,'gateway',gateway)
    calls=[];monkeypatch.setattr(mod,'transport',lambda payload:calls.append(payload) or {'ok':True})
    assert 'unavailable' in mod.handle({'action':'list'}) and not calls
    for name,value in [('PLATFORM','discord'),('USER_ID',USER),('CHAT_ID',CHANNEL),('MESSAGE_ID',MESSAGE)]:context._VAR_MAP['HERMES_SESSION_'+name].set(value)
    assert json.loads(mod.handle({'action':'list'}))=={'ok':True}
    assert calls[0]['discord_user_id']==USER
    assert 'unavailable' in mod.handle({'action':'list','discord_user_id':'456789012345678901'}) and len(calls)==1


def test_ai_defaults_free_first_and_explicit_membership_settings(secured):
    signed(secured)
    preferences = secured.get('/api/profile').json()['preferences']
    assert preferences['ai_agent'] == 'hermes'
    assert preferences['ai_model'] == 'openrouter/free'
    preferences.update(ai_agent='codex', ai_model='gpt-6-luna')
    result = secured.put('/api/profile', json=preferences)
    assert result.status_code == 200
    assert result.json()['preferences']['ai_model'] == 'gpt-6-luna'
    preferences.update(ai_agent='unrecognized')
    assert secured.put('/api/profile', json=preferences).status_code == 422
