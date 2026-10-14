import json
import os
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from models import AgentAccess, Card, Project, ProjectTask
from tests.test_auth import secured, begin, complete

def issue(client, scope="draft", days=7):
    assert complete(client, begin(client)).status_code == 303
    response = client.post('/api/agent-access', json={'scope': scope, 'days': days})
    assert response.status_code == 201, response.text
    data = response.json()
    secret = Path(data['token_file']).read_text().strip()
    assert secret not in response.text and 'token_hash' not in response.text
    return data, secret

def agent(client, secret, host='127.0.0.1'):
    return TestClient(client.app, base_url='http://127.0.0.1:8800', client=(host, 2222),
        headers={'X-Mac-Control':'1', 'Authorization':'Bearer '+secret})

def test_grant_private_hashed_expiring_revocable_and_rotation(secured):
    data, secret = issue(secured, 'read', 1)
    p=Path(data['token_file'])
    assert p.stat().st_mode & 0o777 == 0o600 and p.parent.stat().st_mode & 0o777 == 0o700
    with secured.app.state.sessions() as s:
        row=s.get(AgentAccess,data['id']); assert row.token_hash != secret
    a=agent(secured,secret)
    assert a.get('/api/agent-tools/tasks').status_code==200
    assert a.post('/api/agent-tools/tasks',json={'title':'Denied','assignee_type':'human'}).status_code==403
    assert secret not in secured.get('/api/agent-access').text
    new, newer=issue(secured,'draft')
    assert a.get('/api/agent-tools/tasks').status_code==401
    assert secured.post('/api/agent-access/'+new['id']+'/revoke').status_code==200
    assert agent(secured,newer).get('/api/agent-tools/tasks').status_code==401

@pytest.mark.parametrize('path,method',[('/api/projects','get'),('/api/projects/1/submit','post'),('/api/projects/1/handoff-policy','post'),('/api/projects/1/plan','post'),('/api/cards','get'),('/api/chat/threads','get'),('/api/billing','get'),('/api/agent-access','get'),('/api/mcp/changes/3/approve','post'),('/auth/recover','post'),('/api/agent-tools/tasks/1/approve','post'),('/api/agent-tools/tasks/1','delete'),('/api/runs/1/log','get')])
def test_agent_cannot_escape_curated_routes_even_with_browser_session(secured,path,method):
    _,secret=issue(secured)
    secured.headers['Authorization']='Bearer '+secret
    assert getattr(secured,method)(path).status_code==403

@pytest.mark.parametrize('headers',[{'X-Forwarded-For':'127.0.0.1'},{'X-Forwarded-Proto':'https'},{'Forwarded':'for=127.0.0.1'},{'Origin':'http://127.0.0.1:8800'}])
def test_browser_proxy_and_remote_use_refused(secured,headers):
    _,secret=issue(secured)
    assert agent(secured,secret).get('/api/agent-tools/tasks',headers=headers).status_code==403
    assert agent(secured,secret,'100.80.1.2').get('/api/agent-tools/tasks').status_code==403

def test_draft_ownership_status_approval_validation_and_no_dispatch(secured,tmp_path):
    _,secret=issue(secured)
    a=agent(secured,secret)
    operator_task=secured.post('/api/cards',json={'title':'Operator task','assignee_type':'human'}).json()
    response=a.post('/api/agent-tools/tasks',json={'title':'Operator decision','assignee_type':'human','acceptance':'Decision recorded'})
    assert response.status_code==201,response.text
    card=response.json();assert card['column']=='backlog' and card['created_by']=='hermes' and card['last_run'] is None
    cid=card['id']
    assert a.patch(f'/api/agent-tools/tasks/{cid}',json={'column':'queued'}).status_code==422
    assert a.patch(f'/api/agent-tools/tasks/{cid}',json={'approved_at':1}).status_code==422
    assert a.patch(f'/api/agent-tools/tasks/{cid}',json={'body':None}).status_code==422
    assert a.patch(f'/api/agent-tools/tasks/{operator_task["id"]}',json={'title':'Tampered'}).status_code==403
    assert a.patch(f'/api/agent-tools/tasks/{cid}',json={'title':'Reviewed draft'}).status_code==200
    assert a.post(f'/api/agent-tools/tasks/{cid}/dependencies',json={'depends_on_id':operator_task['id']}).status_code==201
    assert a.post(f'/api/agent-tools/tasks/{cid}/dependencies',json={'depends_on_id':cid}).status_code==422
    assert a.delete(f'/api/agent-tools/tasks/{cid}/dependencies/{operator_task["id"]}').status_code==200
    assert secured.patch(f'/api/cards/{cid}',json={'column':'done'}).status_code==200
    assert a.patch(f'/api/agent-tools/tasks/{cid}',json={'title':'Tampered'}).status_code==403
    workspace=tmp_path/'ws'
    r=a.post('/api/agent-tools/tasks',json={'title':'Push code','agent':'codex','body':'git push','working_dir':str(workspace)})
    assert r.status_code==201,r.text
    assert r.json()['needs_approval'] and r.json()['approved_at'] is None and r.json()['column']=='backlog'
    assert a.post('/api/agent-tools/tasks',json={'title':'Escape','agent':'codex','body':'Read files','working_dir':'/etc'}).status_code==422
    assert a.post('/api/agent-tools/tasks',json={'title':'Smuggle','assignee_type':'human','column':'queued'}).status_code==422
    assert 'command' not in a.get('/api/agent-tools/agents').text

def test_expired_grant_invalid_secret_and_missing_guard_refused(secured):
    data,secret=issue(secured)
    with secured.app.state.sessions.begin() as s:s.get(AgentAccess,data['id']).expires_at=int(time.time())-1
    assert agent(secured,secret).get('/api/agent-tools/tasks').status_code==401
    assert agent(secured,'bad').get('/api/agent-tools/tasks').status_code==401
    _,secret=issue(secured)
    a=agent(secured,secret);del a.headers['X-Mac-Control']
    assert a.post('/api/agent-tools/tasks',json={'title':'Denied','assignee_type':'human'}).status_code==403
    assert secured.get('/api/agent-tools/tasks').status_code==401

def test_credential_directory_symlink_and_permissions_do_not_expand_access(secured,tmp_path):
    assert complete(secured,begin(secured)).status_code==303
    root=secured.app.state.agent_access.token_path.parent
    root.symlink_to(tmp_path,target_is_directory=True)
    assert secured.post('/api/agent-access',json={'scope':'draft','days':7}).status_code==409
    with secured.app.state.sessions() as s:assert not s.scalars(select(AgentAccess)).all()
    root.unlink();root.mkdir(mode=0o755)
    assert secured.post('/api/agent-access',json={'scope':'draft','days':7}).status_code==409

def test_curated_draft_grant_cannot_change_approved_project_dependencies(secured):
    _,secret=issue(secured)
    a=agent(secured,secret)
    cid=a.post('/api/agent-tools/tasks',json={'title':'Human project review','assignee_type':'human'}).json()['id']
    dep=secured.post('/api/cards',json={'title':'Prerequisite','assignee_type':'human'}).json()['id']
    assert a.post(f'/api/agent-tools/tasks/{cid}/dependencies',json={'depends_on_id':dep}).status_code==201
    with secured.app.state.sessions.begin() as s:
        p=Project(document='{}',state='active',created_by='operator',created_at=1,updated_at=1)
        s.add(p);s.flush()
        s.add(ProjectTask(card_id=cid,project_id=p.id,revision=1,node_key='review',role='story'))
    assert a.post(f'/api/agent-tools/tasks/{cid}/dependencies',json={'depends_on_id':dep}).status_code==409
    assert a.delete(f'/api/agent-tools/tasks/{cid}/dependencies/{dep}').status_code==409
