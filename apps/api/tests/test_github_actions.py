import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from github_actions import ActionError, GithubActionGuard, GithubActionTransport, plan
from github_config import GithubConfigStore
from github_read import GithubReader

ACTOR = 'operator@example.test'
SHA = 'a' * 40


class FakeTransport:
    def __init__(self):
        self.sent, self.checked = [], []
        self.fail_preflight = self.fail_send = False

    def preflight(self, preview):
        self.checked.append(preview)
        if self.fail_preflight:
            raise RuntimeError('private diagnostic')

    def send(self, preview):
        self.sent.append(preview)
        if self.fail_send:
            raise subprocess.TimeoutExpired('fake-gh', 15)
        return {'acknowledged': True}


@pytest.fixture
def gate(tmp_path):
    store = GithubConfigStore(tmp_path)
    store.save({'version': 1, 'enabled': True, 'account': 'operator', 'repos': ['synthetic/repo'], 'public_only': False, 'poll_seconds': 900})
    reader = GithubReader('never-real-gh', store)
    return GithubActionGuard(tmp_path, reader, enabled=True, transport=FakeTransport())


def issue(**changes):
    return {'kind': 'issue', 'repo': 'synthetic/repo', 'content': {'title': 'Synthetic title', 'body': 'Exact synthetic body'}, **changes}


def approved(gate, value=None):
    draft = gate.draft(value or issue(), ACTOR)
    preview = gate.review(draft['id'], ACTOR)
    assert preview['preview']['destination'].startswith('https://github.com/synthetic/repo/')
    return gate.approve(draft['id'], preview['fingerprint'], preview['nonce'], ACTOR)


def test_baseline_drafting_never_sends_and_duplicate_is_durable(gate):
    a = gate.draft(issue(), ACTOR)
    assert gate.draft(issue(), ACTOR)['id'] == a['id']
    restarted = GithubActionGuard(gate.path.parent, gate.reader, enabled=True, transport=gate.transport)
    assert restarted.draft(issue(), ACTOR)['id'] == a['id']
    assert not gate.transport.checked and not gate.transport.sent
    assert gate.path.stat().st_mode & 0o777 == 0o600
    assert gate.get(a['id'])['audit'][-1]['event'] == 'duplicate_suppressed'


def test_disabled_writes_and_missing_approval_never_preflight(gate):
    a = gate.draft(issue(), ACTOR)
    with pytest.raises(ActionError):
        gate.execute(a['id'], a['fingerprint'], ACTOR)
    a = approved(gate)
    gate.enabled = False
    with pytest.raises(ActionError):
        gate.execute(a['id'], a['fingerprint'], ACTOR)
    assert not gate.transport.checked and not gate.transport.sent


def test_exact_preview_replay_and_operator_binding(gate):
    a = gate.draft(issue(), ACTOR)
    p = gate.review(a['id'], ACTOR)
    for fingerprint, nonce in [('0' * 64, p['nonce']), (p['fingerprint'], 'wrong')]:
        with pytest.raises(ActionError):
            gate.approve(a['id'], fingerprint, nonce, ACTOR)
    gate.approve(a['id'], p['fingerprint'], p['nonce'], ACTOR)
    with pytest.raises(ActionError):
        gate.approve(a['id'], p['fingerprint'], p['nonce'], ACTOR)
    with pytest.raises(ActionError):
        gate.execute(a['id'], p['fingerprint'], 'other@example.test')
    with pytest.raises(ActionError):
        gate.execute(a['id'], '0' * 64, ACTOR)
    assert not gate.transport.sent
    result = gate.execute(a['id'], p['fingerprint'], ACTOR)
    assert result['state'] == 'succeeded'
    assert gate.transport.sent[0]['payload'] == issue()['content']
    assert all(e['actor'] == ACTOR or e['actor'] == 'other@example.test' for e in result['audit'])
    with pytest.raises(ActionError):
        gate.execute(a['id'], p['fingerprint'], ACTOR)
    assert len(gate.transport.sent) == 1


@pytest.mark.parametrize('stage', ['approve', 'execute'])
def test_expiry_fails_closed(gate, stage):
    a = gate.draft(issue(), ACTOR)
    p = gate.review(a['id'], ACTOR)
    if stage == 'execute':
        gate.approve(a['id'], p['fingerprint'], p['nonce'], ACTOR)
    gate.clock = lambda: p['expires_at'] + 1
    with pytest.raises(ActionError):
        if stage == 'approve':
            gate.approve(a['id'], p['fingerprint'], p['nonce'], ACTOR)
        else:
            gate.execute(a['id'], p['fingerprint'], ACTOR)
    assert not gate.transport.sent


@pytest.mark.parametrize('change', [{'enabled': False}, {'repos': ['other/repo']}, {'account': 'other'}, {'public_only': True}])
def test_policy_revocation_after_approval(gate, change):
    a = approved(gate)
    config = gate.reader.config_store.status()
    value = {k: config[k] for k in ('version', 'enabled', 'account', 'repos', 'public_only', 'poll_seconds')}
    gate.reader.config_store.save({**value, **change})
    with pytest.raises(ActionError):
        gate.execute(a['id'], a['fingerprint'], ACTOR)
    assert not gate.transport.checked and not gate.transport.sent


def test_preview_rotation_and_revoke(gate):
    a = gate.draft(issue(), ACTOR)
    old = gate.review(a['id'], ACTOR)
    p = gate.review(a['id'], ACTOR)
    with pytest.raises(ActionError):
        gate.approve(a['id'], old['fingerprint'], old['nonce'], ACTOR)
    gate.approve(a['id'], p['fingerprint'], p['nonce'], ACTOR)
    gate.revoke(a['id'], ACTOR)
    with pytest.raises(ActionError):
        gate.execute(a['id'], p['fingerprint'], ACTOR)
    assert not gate.transport.sent


def test_concurrent_and_restarted_execution_sends_once(gate):
    a = approved(gate)
    guards = [GithubActionGuard(gate.path.parent, gate.reader, enabled=True, transport=gate.transport) for _ in range(6)]
    def run(g):
        try:
            return g.execute(a['id'], a['fingerprint'], ACTOR)['state']
        except ActionError:
            return 'denied'
    with ThreadPoolExecutor(max_workers=6) as pool:
        states = list(pool.map(run, guards))
    assert states.count('succeeded') == 1 and states.count('denied') == 5
    assert len(gate.transport.sent) == 1


@pytest.mark.parametrize('fail', ['preflight', 'send'])
def test_uncertain_and_preflight_failure_never_retry(gate, fail):
    a = approved(gate)
    setattr(gate.transport, 'fail_' + fail, True)
    with pytest.raises(ActionError) as error:
        gate.execute(a['id'], a['fingerprint'], ACTOR)
    assert 'private diagnostic' not in str(error.value)
    state = 'blocked' if fail == 'preflight' else 'uncertain'
    assert gate.get(a['id'])['state'] == state
    restarted = GithubActionGuard(gate.path.parent, gate.reader, enabled=True, transport=gate.transport)
    with pytest.raises(ActionError):
        restarted.execute(a['id'], a['fingerprint'], ACTOR)
    assert len(gate.transport.sent) == (fail == 'send')


def test_crash_after_claim_remains_permanently_claimed(gate):
    a = approved(gate)
    def crash(_):
        raise SystemExit('synthetic crash')
    gate.transport.send = crash
    with pytest.raises(SystemExit):
        gate.execute(a['id'], a['fingerprint'], ACTOR)
    restarted = GithubActionGuard(gate.path.parent, gate.reader, enabled=True, transport=FakeTransport())
    assert restarted.get(a['id'])['state'] == 'claimed'
    with pytest.raises(ActionError):
        restarted.execute(a['id'], a['fingerprint'], ACTOR)
    assert not restarted.transport.sent


@pytest.mark.parametrize('value', [issue(repo='../repo'), issue(repo='other/repo'), issue(kind='shell'), issue(content={'title': 'x', 'body': 'y', 'endpoint': '/bad'}), issue(content={'title': '', 'body': 'y'})])
def test_untrusted_or_outside_scope_drafts_are_denied_and_audited(gate, value):
    with pytest.raises(ActionError):
        gate.draft(value, ACTOR)
    with gate.connect() as db:
        assert db.execute('SELECT event FROM audit').fetchone()[0] == 'draft_denied'
    assert not gate.transport.sent


@pytest.mark.parametrize('kind,content,method,path', [
    ('issue', {'title': 'x', 'body': 'y'}, 'POST', '/issues'),
    ('comment', {'number': 12, 'body': 'y'}, 'POST', '/issues/12/comments'),
    ('pr', {'title': 'x', 'body': 'y', 'head': 'feature', 'base': 'main', 'head_sha': SHA, 'base_sha': SHA, 'draft': True}, 'POST', '/pulls'),
    ('merge', {'number': 12, 'head_sha': SHA, 'method': 'squash', 'commit_title': 'x', 'commit_message': 'y'}, 'PUT', '/pulls/12/merge'),
    ('publication', {'tag': 'v1', 'target_sha': SHA, 'name': 'x', 'body': 'y', 'prerelease': True}, 'POST', '/releases'),
])
def test_all_kinds_use_exact_reviewed_payload(gate, kind, content, method, path):
    a = approved(gate, {'kind': kind, 'repo': 'synthetic/repo', 'content': content})
    assert a['preview']['content'] == content
    gate.execute(a['id'], a['fingerprint'], ACTOR)
    sent = gate.transport.sent[0]
    assert sent['method'] == method and sent['endpoint'] == 'repos/synthetic/repo' + path
    if kind == 'merge':
        assert sent['payload']['sha'] == SHA
    if kind == 'publication':
        assert sent['payload']['generate_release_notes'] is False and sent['payload']['make_latest'] == 'false'


def test_transport_json_stdin_no_shell_and_no_raw_output(gate, monkeypatch):
    calls = []
    def fake(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"id":1,"private":"not retained"}', stderr='not retained')
    monkeypatch.setattr('github_actions.subprocess.run', fake)
    transport = GithubActionTransport(gate.reader)
    p = plan(issue(content={'title': 'literal $(nope)', 'body': 'literal `nope`\n--flag'}))
    assert transport.send(p) == {'acknowledged': True}
    argv, kwargs = calls[0]
    assert '--hostname' in argv and 'github.com' in argv and '--input' in argv
    assert 'shell' not in kwargs and json.loads(kwargs['input']) == p['payload']
    assert p['content']['body'] not in argv


@pytest.mark.parametrize('kind,remote', [('pr', {'sha': 'b'*40}), ('merge', {'state': 'open', 'draft': False, 'head': {'sha': 'b'*40}}), ('publication', {'object': {'type': 'tag', 'sha': SHA}})])
def test_transport_ref_drift_denied(gate, kind, remote):
    content = {
        'pr': {'title': 'x', 'body': 'y', 'head': 'feature', 'base': 'main', 'head_sha': SHA, 'base_sha': SHA, 'draft': True},
        'merge': {'number': 12, 'head_sha': SHA, 'method': 'squash', 'commit_title': 'x', 'commit_message': 'y'},
        'publication': {'tag': 'v1', 'target_sha': SHA, 'name': 'x', 'body': 'y', 'prerelease': True},
    }[kind]
    p = {**plan({'kind': kind, 'repo': 'synthetic/repo', 'content': content}), 'account': 'operator', 'public_only': False}
    transport = GithubActionTransport(gate.reader)
    gate.reader.auth_status = lambda: {'available': True, 'account': 'operator'}
    transport.request = lambda method, endpoint, payload=None: {'full_name': 'synthetic/repo', 'private': False} if endpoint == 'repos/synthetic/repo' else remote
    with pytest.raises(ActionError):
        transport.preflight(p)


def test_api_requires_operator_even_with_auth_disabled(make_client):
    with make_client() as client:
        for method, path, body in [
            ('POST', '/api/github/actions', issue()),
            ('GET', '/api/github/actions/missing', None),
            ('POST', '/api/github/actions/missing/preview', None),
            ('POST', '/api/github/actions/missing/approve', {'fingerprint': 'a'*64, 'nonce': 'n'*32}),
            ('POST', '/api/github/actions/missing/execute', {'fingerprint': 'a'*64}),
            ('POST', '/api/github/actions/missing/revoke', None),
        ]:
            assert client.request(method, path, json=body).status_code == 403


@pytest.mark.parametrize('stage', ['preflight', 'send'])
def test_process_crash_and_restart_leave_claim_spent(gate, tmp_path, stage):
    import os
    import sys
    from pathlib import Path
    a = approved(gate)
    # Real short-lived Python process, synthetic data only; exits between claim and send.
    script = tmp_path / 'crash.py'
    script.write_text('''
import os, sys
from pathlib import Path
from github_config import GithubConfigStore
from github_read import GithubReader
from github_actions import GithubActionGuard
class Transport:
    def preflight(self, preview):
        if sys.argv[4] == "preflight": os._exit(73)
    def send(self, preview):
        # Synthetic delivery acknowledgement loss; no network or actual gh.
        receipt = Path(sys.argv[1]) / "synthetic-write.txt"
        with receipt.open("a") as f:
            f.write("one synthetic write\\n")
            f.flush()
            os.fsync(f.fileno())
        os._exit(73)
g = GithubActionGuard(Path(sys.argv[1]), GithubReader("never-real-gh", GithubConfigStore(Path(sys.argv[1]))), enabled=True, transport=Transport())
g.execute(sys.argv[2], sys.argv[3], "operator@example.test")
''')
    env = {'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
           'PYTHONDONTWRITEBYTECODE': '1', 'MAC_CONTROL_COLLECTOR_ENABLED': 'false', 'MAC_CONTROL_DISPATCHER_ENABLED': 'false'}
    result = subprocess.run([sys.executable, str(script), str(gate.path.parent), a['id'], a['fingerprint'], stage], env=env, timeout=5, capture_output=True)
    assert result.returncode == 73
    receipt = gate.path.parent / 'synthetic-write.txt'
    assert receipt.exists() == (stage == 'send')
    if receipt.exists():
        assert receipt.read_text() == 'one synthetic write\n'
    restarted = GithubActionGuard(gate.path.parent, gate.reader, enabled=True, transport=FakeTransport())
    assert restarted.get(a['id'])['state'] == 'claimed'
    with pytest.raises(ActionError):
        restarted.execute(a['id'], a['fingerprint'], ACTOR)
    assert not restarted.transport.checked and not restarted.transport.sent


def test_preview_store_tampering_denies(gate):
    a = approved(gate)
    with gate.connect() as db:
        value = json.loads(db.execute('SELECT preview FROM actions').fetchone()[0])
        value['payload']['body'] = 'changed'
        db.execute('UPDATE actions SET preview=?', (json.dumps(value),))
    with pytest.raises(ActionError):
        gate.execute(a['id'], a['fingerprint'], ACTOR)
    assert not gate.transport.sent


def test_repository_case_cannot_bypass_duplicate_suppression(gate):
    a = gate.draft(issue(), ACTOR)
    assert gate.draft(issue(repo='Synthetic/Repo'), ACTOR)['id'] == a['id']


@pytest.mark.parametrize('change', ['account', 'private', 'archived'])
def test_transport_current_account_visibility_and_archival_denied(gate, change):
    p = {**plan(issue()), 'account': 'operator', 'public_only': True}
    transport = GithubActionTransport(gate.reader)
    gate.reader.auth_status = lambda: {'available': True, 'account': 'other' if change == 'account' else 'operator'}
    calls = []
    def remote(method, endpoint, payload=None):
        calls.append(method)
        return {'full_name': 'synthetic/repo', 'private': change == 'private', 'archived': change == 'archived'}
    transport.request = remote
    with pytest.raises(ActionError):
        transport.preflight(p)
    assert calls == ([] if change == 'account' else ['GET'])


def test_api_operator_preview_approve_and_fake_send(make_client):
    client = make_client()
    @client.app.middleware('http')
    async def synthetic_operator(request, call_next):
        request.state.user = {'email': ACTOR, 'method': 'google'}
        return await call_next(request)
    with client:
        client.app.state.github_config.save({'version': 1, 'enabled': True, 'account': 'operator', 'repos': ['synthetic/repo'], 'public_only': False, 'poll_seconds': 900})
        gate = client.app.state.github_actions
        gate.enabled = True
        gate.transport = FakeTransport()
        draft = client.post('/api/github/actions', json=issue())
        assert draft.status_code == 201
        a = draft.json()
        base = '/api/github/actions/' + a['id']
        assert client.post(base + '/execute', json={'fingerprint': a['fingerprint']}).status_code == 409
        p = client.post(base + '/preview').json()
        assert p['preview']['payload'] == issue()['content']
        approval = {'fingerprint': p['fingerprint'], 'nonce': p['nonce']}
        assert client.post(base + '/approve', json=approval).status_code == 200
        assert client.post(base + '/approve', json=approval).status_code == 409
        assert client.post(base + '/execute', json={'fingerprint': p['fingerprint']}).json()['state'] == 'succeeded'
        assert client.post(base + '/execute', json={'fingerprint': p['fingerprint']}).status_code == 409
        result = client.get(base).json()
        assert result['approved_by'] == ACTOR and len(gate.transport.sent) == 1


def test_agent_capabilities_and_peer_boundary_exclude_actions():
    from agent_access import permitted
    from operator_boundary import agent_route
    for method in ('GET', 'POST', 'PUT', 'DELETE'):
        for path in ('/api/github/actions', '/api/github/actions/id/preview', '/api/github/actions/id/approve', '/api/github/actions/id/execute'):
            assert not permitted(method, path, 'draft')
            assert not permitted(method, path, 'read')
            assert not agent_route(method, path, True)
