"""Bug reports: scrubbing, the built issue, how it can be sent, and filing through the guarded GitHub action (with a fake transport)."""
import re
import subprocess
from types import SimpleNamespace

import pytest

import bug_reports
from github_actions import ActionError, plan

ACTOR = 'operator@example.test'
OFFICIAL = bug_reports.REPOSITORY


def fake(*parts):
    """Token-shaped strings are built at run time so the secret scanner has nothing to flag in the source."""
    return ''.join(parts)


class FakeTransport:
    def __init__(self):
        self.sent = []

    def preflight(self, preview):
        pass

    def send(self, preview):
        self.sent.append(preview)
        return {'acknowledged': True, 'html_url': f'https://github.com/{OFFICIAL}/issues/42'}


SETTINGS = SimpleNamespace(product_name='Mac Control Dashboard')


def test_scrub_removes_paths_emails_addresses_hosts_and_token_shapes():
    key = fake('sk-', 'a1b2c3d4e5f6g7h8i9j0k1l2')
    pat = fake('ghp_', 'A' * 36)
    jwt = fake('eyJ', 'hbGciOiJIUzI1NiJ9', '.', 'eyJzdWIiOiIxMjM0NTY', '.', 'abcdefghijklmnop')
    text = (f'It broke in /Users/alice/Projects/site and /home/pi/.rcd. Mail alice@example.com. Host miniblaster.tail8043b6.ts.net, '
            f'mac masters-mac-mini.local, ip 100.69.79.112 and 192.168.1.20 but not 127.0.0.1. Key {key}, {pat}, Bearer {fake("abcDEF123456", "ghiJKL")}, '
            f'password=hunter2hunter2, {jwt}, https://user:secretpw@example.com/x, hash {"a" * 64}')
    out, notes = bug_reports.scrub(text)
    for secret in ('alice', '/home/pi', 'alice@', 'tail8043b6', 'masters-mac-mini', '100.69.79.112', '192.168.1.20', key, pat,
                   'abcDEF123456', 'hunter2hunter2', jwt, 'secretpw', 'a' * 64):
        assert secret not in out, secret
    assert 'https://[credentials]@example.com/x' in out        # a link keeps its public host; only the credentials go
    assert '127.0.0.1' in out and '~/Projects/site' in out and '[email]' in out and '[host]' in out
    assert any('home paths' in n for n in notes) and any('tokens' in n for n in notes) and any('emails' in n for n in notes)
    assert bug_reports.scrub('Plain words about a button that does nothing.') == ('Plain words about a button that does nothing.', [])


def test_the_issue_is_built_from_scrubbed_fields_and_a_short_environment_block(monkeypatch):
    monkeypatch.setattr(bug_reports, 'REGISTRY', {'codex': SimpleNamespace(available=lambda s: True), 'grok': SimpleNamespace(available=lambda s: False)})
    built = bug_reports.build({'title': 'Delete is greyed out', 'what': 'See /Users/bob/notes. Mail bob@example.com.', 'expected': 'It deletes',
                               'steps': '1. open the task', 'impact': 'blocks', 'page': '/tasks'}, SETTINGS)
    assert built['title'] == 'Delete is greyed out' and 'bob' not in built['body'] and 'example.com' not in built['body']
    assert '### Environment' in built['body'] and 'Agent runtimes installed: codex' in built['body'] and 'Opened from: /tasks' in built['body']
    assert 'Blocks my work' in built['body'] and built['scrubbed']
    assert built['labels_when_filed_here'] == ['bug-report', 'accepted', 'break-fix']
    assert bug_reports.build({'title': 'x', 'what': 'y', 'impact': 'idea'}, SETTINGS)['labels_when_filed_here'][-1] == 'nice-to-have'
    plain = bug_reports.build({'title': 'x', 'what': 'y'}, SETTINGS, include_environment=False)
    assert '### Environment' not in plain['body']
    for bad in ({'title': '', 'what': 'y'}, {'title': 'x', 'what': ' '}):
        with pytest.raises(ValueError):
            bug_reports.build(bad, SETTINGS)
    odd = bug_reports.build({'title': 'x', 'what': 'y', 'page': '/tasks?token=abc'}, SETTINGS)     # a page that is not a plain route is dropped
    assert 'Opened from' not in odd['body']


def test_the_prefilled_link_points_only_at_the_official_repository_and_fits_a_link():
    built = bug_reports.build({'title': 'T & more', 'what': 'word ' * 600, 'expected': 'e', 'steps': 's'}, SETTINGS)
    assert built['url'].startswith(f'https://github.com/{OFFICIAL}/issues/new?labels=bug-report&title=T%20%26%20more&body=')
    assert len(built['url']) <= bug_reports.URL_MAX and re.fullmatch(r'[A-Za-z0-9%_.~=&?:/-]+', built['url'])
    huge = bug_reports.build({'title': 't', 'what': 'x' * 3000, 'expected': 'y' * 2000, 'steps': 'z ' * 1500}, SETTINGS)
    assert len(huge['url']) <= bug_reports.URL_MAX


def test_capabilities_say_how_a_report_can_be_sent():
    reader = SimpleNamespace(config=lambda: SimpleNamespace(configured=True, repos=(OFFICIAL,)))
    assert bug_reports.capabilities(SimpleNamespace(enabled=True), reader)['mode'] == 'direct'
    off = bug_reports.capabilities(SimpleNamespace(enabled=False), reader)
    assert off['mode'] == 'prefilled' and 'opens on GitHub' in off['reason']
    elsewhere = SimpleNamespace(config=lambda: SimpleNamespace(configured=True, repos=('someone/else',)))
    other = bug_reports.capabilities(SimpleNamespace(enabled=True), elsewhere)
    assert other['mode'] == 'prefilled' and OFFICIAL in other['reason']
    assert bug_reports.capabilities(SimpleNamespace(enabled=True), SimpleNamespace(config=lambda: None))['mode'] == 'prefilled'


def test_the_guarded_issue_action_accepts_a_few_safe_labels_and_nothing_else():
    ok = plan({'kind': 'issue', 'repo': OFFICIAL, 'content': {'title': 't', 'body': 'b', 'labels': ['bug-report', 'nice-to-have']}})
    assert ok['payload']['labels'] == ['bug-report', 'nice-to-have']
    for labels in ([], ['x'] * 6, ['-bad'], ['has/slash'], [1], 'bug', ['a' * 51]):
        with pytest.raises(ActionError):
            plan({'kind': 'issue', 'repo': OFFICIAL, 'content': {'title': 't', 'body': 'b', 'labels': labels}})
    with pytest.raises(ActionError):
        plan({'kind': 'issue', 'repo': OFFICIAL, 'content': {'title': 't', 'body': 'b', 'assignees': ['x']}})
    with pytest.raises(ActionError):
        plan({'kind': 'comment', 'repo': OFFICIAL, 'content': {'number': 1, 'body': 'b', 'labels': ['x']}})


@pytest.fixture
def client(make_client):
    c = make_client()

    @c.app.middleware('http')
    async def operator(request, call_next):
        request.state.user = {'email': ACTOR, 'method': 'google'}
        return await call_next(request)
    with c:
        yield c


def enable(client):
    client.app.state.github_config.save({'version': 1, 'enabled': True, 'account': 'operator', 'repos': [OFFICIAL], 'public_only': False, 'poll_seconds': 900})
    gate = client.app.state.github_actions
    gate.enabled, gate.transport = True, FakeTransport()
    return gate


FORM = {'title': 'Greyed out', 'what': 'The button is disabled. See /Users/me/x', 'impact': 'blocks', 'page': '/tasks'}


def test_routes_need_the_operator(make_client):
    with make_client() as anon:
        assert anon.get('/api/bug-reports/capabilities').status_code == 403
        assert anon.post('/api/bug-reports/preview', json=FORM).status_code == 403
        assert anon.post('/api/bug-reports/file', json={**FORM, 'confirm': True}).status_code == 403


def test_preview_sends_nothing_and_shows_what_was_scrubbed(client):
    gate = enable(client)
    got = client.post('/api/bug-reports/preview', json=FORM)
    assert got.status_code == 201 or got.status_code == 200
    body = got.json()
    assert '/Users/me' not in body['body'] and body['scrubbed'] and body['mode'] == 'direct' and body['url'].startswith('https://github.com/')
    assert gate.transport.sent == []
    assert client.post('/api/bug-reports/preview', json={**FORM, 'title': ''}).status_code == 422
    assert client.post('/api/bug-reports/preview', json={**FORM, 'repo': 'evil/repo'}).status_code == 422   # no way to name another repository


def test_filing_goes_through_the_guarded_action_after_an_explicit_confirm(client):
    gate = enable(client)
    assert client.post('/api/bug-reports/file', json=FORM).status_code == 422                       # no confirm, nothing sent
    done = client.post('/api/bug-reports/file', json={**FORM, 'confirm': True})
    assert done.status_code == 201, done.text
    assert done.json() == {'state': 'succeeded', 'url': f'https://github.com/{OFFICIAL}/issues/42', 'action_id': done.json()['action_id']}
    sent = gate.transport.sent
    assert len(sent) == 1 and sent[0]['repo'] == OFFICIAL and sent[0]['payload']['labels'] == ['bug-report', 'accepted', 'break-fix']
    assert '/Users/me' not in sent[0]['payload']['body']
    again = client.post('/api/bug-reports/file', json={**FORM, 'confirm': True})                   # the identical report is not filed twice
    assert again.status_code == 409 and len(gate.transport.sent) == 1


def test_filing_is_refused_where_only_the_prefilled_page_is_available(client):
    client.app.state.github_actions.enabled = False
    assert client.get('/api/bug-reports/capabilities').json()['mode'] == 'prefilled'
    refused = client.post('/api/bug-reports/file', json={**FORM, 'confirm': True})
    assert refused.status_code == 409 and 'opens on GitHub' in refused.json()['detail']
