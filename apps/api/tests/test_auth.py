import json
import time
from urllib.parse import urlsplit, parse_qs

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from auth import AuthService, cookie_name, safe_next, verify_id_token
from models import AuthSession
from settings import Settings


@pytest.fixture
def secured(make_client, monkeypatch):
    monkeypatch.setenv('MAC_CONTROL_AUTH_ENABLED','true')
    monkeypatch.setenv('MAC_CONTROL_GOOGLE_CLIENT_ID','test-client')
    monkeypatch.setenv('MAC_CONTROL_GOOGLE_CLIENT_SECRET','test-secret')
    monkeypatch.setenv('MAC_CONTROL_AUTH_ALLOWED_EMAILS','["operator@example.com","reviewer@example.com"]')
    with make_client() as original:
        client=TestClient(original.app,base_url='http://127.0.0.1:8800',client=('127.0.0.1',1234),headers={'X-Mac-Control':'1'},follow_redirects=False)
        yield client


def begin(client, next='/agents'):
    response=client.get('/auth/login',params={'next':next})
    assert response.status_code==303
    query=parse_qs(urlsplit(response.headers['location']).query)
    assert query['scope']==['openid email']
    assert query['code_challenge_method']==['S256']
    return query


class Provider:
    def __init__(self, claims): self.claims=claims; self.calls=[]
    async def exchange(self,*args): self.calls.append(args); return self.claims


def complete(client, query, **extra):
    claims={'sub':'subject1','email':'operator@example.com','email_verified':True,'nonce':query['nonce'][0],**extra}
    client.app.state.auth.provider=Provider(claims)
    return client.get('/auth/callback',params={'state':query['state'][0],'code':'private-code'})


def test_every_data_route_and_write_is_protected_but_bootstrap_is_public(secured):
    for path in ('/api/agents','/api/cards','/api/metrics/current','/api/release','/api/github/repos','/api/reports','/api/alerts','/openapi.json','/tasks','/reports'):
        assert secured.get(path).status_code==401
    assert secured.post('/api/cards',json={}).status_code==401
    assert secured.get('/healthz').status_code==200
    assert secured.get('/login').status_code==200
    assert secured.get('/auth/status').json()['user'] is None
    assert secured.get('/assets/app.js').status_code==200
    r=secured.get('/agents',headers={'Accept':'text/html'})
    assert r.status_code==303 and r.headers['location'].startswith('/login?')


def test_allowed_login_hashed_origin_session_replay_logout(secured):
    query=begin(secured)
    r=complete(secured,query)
    assert r.status_code==303 and r.headers['location']=='/agents'
    cookie=r.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Max-Age=43200' in cookie
    raw=secured.cookies.get('mcd_session')
    assert raw and secured.get('/api/agents').status_code==200
    assert secured.get('/auth/status').json()['user']['email']=='operator@example.com'
    with secured.app.state.sessions() as s:
        row=s.scalars(select(AuthSession)).one()
        assert row.token_hash!=raw and raw not in row.token_hash
    # Login state is consumed; replay cannot create another session.
    assert complete(secured,query).headers['location']=='/login?error=signin_failed'
    assert secured.post('/auth/logout').status_code==200
    assert secured.get('/api/agents').status_code==401
    with secured.app.state.sessions() as s: assert not s.scalars(select(AuthSession)).all()


@pytest.mark.parametrize('claims',[{'email':'stranger@gmail.com'},{'email_verified':False},{'nonce':'wrong'},{'email_verified':'true'},{'sub':''}])
def test_nonallowed_unverified_or_replayed_identity_refused(secured,claims):
    q=begin(secured)
    r=complete(secured,q,**claims)
    assert r.headers['location']=='/login?error=signin_failed'
    assert secured.get('/api/agents').status_code==401


def test_cookie_binding_missing_state_expiry_and_open_redirect(secured):
    q=begin(secured,'https://evil.example/')
    assert secured.app.state.auth.flows[q['state'][0]]['next']=='/'
    secured.cookies.clear()
    r=complete(secured,q)
    assert r.headers['location']=='/login?error=signin_failed'
    assert not secured.app.state.auth.provider.calls
    q=begin(secured)
    secured.app.state.auth.clock=lambda:time.time()+301
    assert complete(secured,q).headers['location']=='/login?error=signin_failed'
    assert not secured.app.state.auth.provider.calls


def test_session_expiry_and_allowlist_change_revoke_access(secured):
    q=begin(secured); complete(secured,q)
    secured.app.state.auth.settings.auth_allowed_emails=('other@example.com',)
    assert secured.get('/api/agents').status_code==401
    secured.app.state.auth.settings.auth_allowed_emails=('operator@example.com',)
    secured.app.state.auth.clock=lambda:time.time()+43201
    assert secured.get('/api/agents').status_code==401


def test_recovery_token_permissions_revocation_and_rate_limit(secured):
    path=secured.app.state.auth.settings.data_dir/'admin-recovery-token'
    assert path.stat().st_mode & 0o777 == 0o600
    token=path.read_text().strip()
    assert secured.post('/auth/recover',json={'token':token}).status_code==200
    assert secured.get('/auth/status').json()['user']['method']=='recovery'
    assert secured.get('/api/agents').status_code==200
    secured.post('/auth/logout')
    for _ in range(4): assert secured.post('/auth/recover',json={'token':'bad'}).status_code==401
    assert secured.post('/auth/recover',json={'token':token}).status_code==429
    assert secured.get('/api/agents').status_code==401


def test_recovery_refuses_proxy_remote_and_cross_site(secured):
    token=(secured.app.state.auth.settings.data_dir/'admin-recovery-token').read_text().strip()
    assert secured.post('/auth/recover',json={'token':token},headers={'X-Forwarded-For':'127.0.0.1'}).status_code==403
    assert secured.post('/auth/recover',json={'token':token},headers={'Origin':'https://evil.example'}).status_code==403
    remote=TestClient(secured.app,base_url='http://127.0.0.1:8800',client=('192.168.1.2',1234),headers={'X-Mac-Control':'1'})
    assert remote.post('/auth/recover',json={'token':token}).status_code==403
    assert remote.get('/auth/status').status_code==403
    assert remote.get('/api/agents').status_code==403


def test_signin_validation_errors_do_not_echo_secrets(secured):
    secret='private-token'*20
    r=secured.post('/auth/recover',json={'token':secret})
    assert r.status_code==422 and secret not in r.text


def test_https_cookie_origin_binding_and_proxy_trust(secured):
    secured.app.state.auth.settings.auth_origins=('http://127.0.0.1:8800','https://mcd.example.com')
    # Middleware captured same mutable settings; fixed origins determine redirect, not forwarding.
    secure=TestClient(secured.app,base_url='https://mcd.example.com',client=('127.0.0.1',1234),headers={'X-Mac-Control':'1'},follow_redirects=False)
    q=begin(secure)
    assert q['redirect_uri']==['https://mcd.example.com/auth/callback']
    r=complete(secure,q)
    assert '__Host-mcd_session' in r.headers['set-cookie'] and 'Secure' in r.headers['set-cookie']
    assert secure.get('/api/agents').status_code==200
    secured.cookies.set('mcd_session',secure.cookies.get('__Host-mcd_session'))
    assert secured.get('/api/agents').status_code==401
    spoof=TestClient(secured.app,base_url='http://mcd.example.com',client=('192.168.1.2',1234))
    assert spoof.get('/auth/status').status_code==403


def test_google_signature_audience_issuer_expiry_and_algorithm():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    claims={'iss':'https://accounts.google.com','aud':'test-client','sub':'sub','iat':int(time.time()),'exp':int(time.time()+300),'email':'operator@example.com','email_verified':True,'nonce':'nonce'}
    token=jwt.encode(claims,key,algorithm='RS256')
    assert verify_id_token(token,key.public_key(),'test-client')['sub']=='sub'
    for delta in ({'aud':'wrong'},{'iss':'https://evil.example'},{'exp':0},{'azp':'wrong'},{'nonce':None}):
        bad=jwt.encode({**claims,**delta},key,algorithm='RS256')
        # Nonce semantic validation is performed against the login flow; missing/null is refused by JWT require.
        with pytest.raises(Exception): verify_id_token(bad,key.public_key(),'test-client')
    with pytest.raises(Exception): verify_id_token(jwt.encode(claims,'x'*32,algorithm='HS256'),key.public_key(),'test-client')


def test_auth_configuration_fails_closed_and_next_path_is_local(tmp_path):
    with pytest.raises(ValueError): Settings(auth_enabled=True,google_client_id='x',google_client_secret='')
    with pytest.raises(ValueError): Settings(auth_origins=('http://192.168.1.2:8800',))
    for path in ('//evil.example','/%2f%2fevil.example','/agents\\evil','/login','/agents\nLocation:evil'):
        assert safe_next(path)=='/'
    assert safe_next('/agents?target=mm-main')=='/agents?target=mm-main'
