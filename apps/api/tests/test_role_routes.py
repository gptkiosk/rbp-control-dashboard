import pytest
from role_pack import RoleStore
from tests.test_tool_install_routes import api

@pytest.fixture
def roles_api(api, monkeypatch):
    monkeypatch.setattr(RoleStore, 'available', lambda self: ['hermes','codex'])
    return api

def test_role_changes_need_operator_preview_and_confirmation(roles_api):
    client = roles_api
    body = {'roles':{'codex':'delegator'}}
    before = client.get('/api/roles').json()
    plan = client.post('/api/roles/preview', json=body)
    assert plan.status_code == 200, plan.text
    assert not (client.home/'.codex/AGENTS.md').exists()
    request = {**body, 'plan_sha256':plan.json()['plan_sha256']}
    assert client.post('/api/roles/apply', json=request).status_code == 422
    assert client.post('/api/roles/apply', json={**request, 'confirm':True}).status_code == 200
    assert client.get('/api/roles').json()['delegator'] == 'codex'
    assert (client.home/'.codex/AGENTS.md').exists()
    assert client.post('/api/roles/rollback', json={'confirm':True}).status_code == 200
    assert client.get('/api/roles').json()['roles'] == before['roles']
    assert not (client.home/'.codex/AGENTS.md').exists()

@pytest.mark.parametrize('signed_in,agent', [(False,False),(True,True)])
def test_all_role_routes_refuse_agents_and_signed_out_clients(roles_api, signed_in, agent):
    client=roles_api;client.state['signed_in']=signed_in;client.state['agent']=agent
    for route, body in [('preview',{'roles':{'codex':'delegator'}}), ('apply',{'roles':{'codex':'delegator'},'plan_sha256':'a'*64,'confirm':True}), ('rollback',{'confirm':True}), ('recover',{'confirm':True})]:
        assert client.post('/api/roles/'+route,json=body).status_code == 403
    assert client.get('/api/roles').status_code == 403
    assert not (client.home/'.codex/AGENTS.md').exists()
