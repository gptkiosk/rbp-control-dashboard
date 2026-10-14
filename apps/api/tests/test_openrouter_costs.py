import json
import httpx
from openrouter_costs import OpenRouterCosts, configured_keys, fetch_key, amount


def test_local_keys_resolve_and_override_without_exposing_credentials(tmp_path):
    for name in ('.hermes', '.openclaw', '.mac-control'):
        (tmp_path / name).mkdir()
    (tmp_path / '.hermes/.env').write_text('OPENROUTER_API_KEY="sk-or-shared"\n')
    (tmp_path / '.openclaw/.env').write_text('OPENROUTER_API_KEY=sk-or-shared\n')
    config = tmp_path / '.openclaw/openclaw.json'
    config.write_text(json.dumps({'models': {'providers': {'openrouter': {'apiKey': 'OPENROUTER_API_KEY'}}}}))
    assert configured_keys(tmp_path) == {'hermes': 'sk-or-shared', 'openclaw': 'sk-or-shared'}
    config.write_text(json.dumps({'models': {'providers': {'openrouter': {'apiKey': 'sk-or-literal'}}}}))
    assert configured_keys(tmp_path)['openclaw'] == 'sk-or-literal'
    (tmp_path / '.mac-control/.env').write_text('MAC_CONTROL_OPENROUTER_OPENCLAW_KEY=sk-or-override\n')
    assert configured_keys(tmp_path)['openclaw'] == 'sk-or-override'


def test_missing_and_secret_reference_never_sent(tmp_path):
    (tmp_path / '.openclaw').mkdir()
    (tmp_path / '.openclaw/.env').write_text('OPENROUTER_API_KEY=sk-or-fallback\n')
    (tmp_path / '.openclaw/openclaw.json').write_text(json.dumps({'models': {'providers': {'openrouter': {'apiKey': {'source': 'env', 'id': 'OTHER_KEY'}}}}}))
    assert configured_keys(tmp_path) == {'hermes': None, 'openclaw': None}


def test_shared_key_requested_once_and_no_key_in_payload():
    calls=[]
    def fetch(key):
        calls.append(key)
        return {'month_usd': 0.0, 'byok_month_usd': 0.00012, 'lifetime_usd': 4}
    m=OpenRouterCosts(fetch=fetch, resolve=lambda _: {'hermes': 'sk-or-secret', 'openclaw': 'sk-or-secret'}, clock=lambda: 100)
    m.refresh()
    assert calls == ['sk-or-secret']
    assert len(m.payload['meters']) == 1
    row=m.payload['meters'][0]
    assert row['agents'] == ['hermes','openclaw']
    assert row['month_usd'] == 0 and row['byok_month_usd'] == 0.00012
    assert 'sk-or-secret' not in json.dumps(m.payload)
    assert row['updated_at'] == 100 and row['state'] == 'ready'


def test_stale_failure_and_rotation_do_not_mix_keys():
    keys={'hermes':'sk-or-one','openclaw':None}
    def fetch(key):
        if fetch.fail: raise RuntimeError('Secret sk-or-one server body')
        return {'month_usd':2}
    fetch.fail=False
    m=OpenRouterCosts(fetch=fetch,resolve=lambda _: keys,clock=lambda:100)
    m.refresh()
    fetch.fail=True
    m.refresh()
    row=m.payload['meters'][0]
    assert row['state']=='stale' and row['month_usd']==2
    assert 'Secret' not in json.dumps(m.payload)
    keys['hermes']='sk-or-two'
    m.refresh()
    row=m.payload['meters'][0]
    assert row['state']=='unavailable' and 'month_usd' not in row
    assert len(m.cache)==1


def test_distinct_keys_and_unreadable_config():
    m=OpenRouterCosts(fetch=lambda _: {'month_usd':1},resolve=lambda _: {'hermes':'sk-or-one','openclaw':'sk-or-two'})
    m.refresh()
    assert len(m.payload['meters'])==2
    def broken(_): raise ValueError('private config content')
    m.resolve=broken
    m.refresh()
    assert m.payload['meters']==[] and len(m.payload['unavailable_agents'])==2
    assert 'private' not in json.dumps(m.payload)


def test_fetch_allowlist_endpoint_and_no_redirects(monkeypatch):
    calls=[]
    class Client:
        def __init__(self, **kwargs): calls.append(kwargs)
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,headers):
            calls.append((url,headers))
            return httpx.Response(200,request=httpx.Request('GET',url),json={'data':{'usage':3,'usage_monthly':0,'byok_usage_monthly':0.004,'label':'secret label','untrusted':'private'}})
    monkeypatch.setattr('openrouter_costs.httpx.Client',Client)
    result=fetch_key('sk-or-test')
    assert calls[0]=={'timeout':6,'follow_redirects':False,'trust_env':False}
    assert calls[1]==('https://openrouter.ai/api/v1/key',{'Authorization':'Bearer sk-or-test'})
    assert result['month_usd']==0 and result['byok_month_usd']==0.004
    assert 'label' not in result and 'untrusted' not in result


def test_invalid_amounts_are_unknown_not_free():
    for value in (True,float('nan'),float('inf'),-1,'2',None): assert amount(value) is None
    assert amount(0)==0


def test_api_returns_separate_key_meter_without_adding_to_captured_estimates(make_client):
    from types import SimpleNamespace
    with make_client() as client:
        meter={'meters':[{'id':'one','agents':['hermes','openclaw'],'month_usd':30,'state':'ready'}], 'unavailable_agents':[], 'checked_at':100}
        client.app.state.collector=SimpleNamespace(usage_scanner=SimpleNamespace(status={}),openrouter_costs=SimpleNamespace(payload=meter))
        data=client.get('/api/agents/usage?agent=hermes&target=session1').json()
        assert data['openrouter']==meter
        assert data['summary']['api_equivalent_usd'] is None
        client.app.state.collector=None
