"""Coordinator setup run by the dashboard: deterministic checks, a previewed apply that only adds what is missing, and the validation project."""
import json

import pytest
from sqlalchemy import select

from agents import AgentSpec
from models import Run
from settings import get_settings
import agent_setup
import routes.profiles as profile_routes


@pytest.fixture
def setup_app(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(AgentSpec, 'available', lambda self, settings: self.id != 'grok')
    monkeypatch.setattr(profile_routes, '_bootstrap_readiness', lambda settings: {'ready': True, 'checks': []})
    client = make_client()
    settings = get_settings()
    hermes = tmp_path / 'hermes.yaml'
    hermes.write_text('model:\n  default: openrouter/free\n')
    openclaw = tmp_path / 'openclaw.json'
    security = agent_setup.agent_id(settings, 'security')
    openclaw.write_text(json.dumps({'agents': {'defaults': {'model': 'openrouter/free'}, 'list': [{'id': security, 'name': 'Security'}]}}))
    settings.hermes_config_path, settings.openclaw_config_path = hermes, openclaw
    calls = []

    def fake_run(argv, timeout=30):
        calls.append(argv)
        if argv[-1] == '--version':
            return 0, 'tool 2026.6.11'
        if argv[1:3] == ['agents', 'add']:
            cfg = json.loads(openclaw.read_text())
            cfg['agents']['list'].append({'id': argv[3]})
            openclaw.write_text(json.dumps(cfg))
            return 0, '{}'
        return 1, 'unexpected'

    monkeypatch.setattr(agent_setup, 'run', fake_run)
    with client:
        # Product defaults differ (RCD free-only, MCD subscription), so pin billing: Claude Code not set up, Codex on Subscription.
        assert client.patch('/api/billing', json={'accounts': {'claude': {'mode': 'api', 'monthly_usd': 0}, 'codex': {'mode': 'subscription', 'monthly_usd': 20}}}).status_code == 200
        prefs = client.get('/api/profile').json()['preferences']
        prefs['coordinator_bootstrap'].update(platforms=['openclaw', 'claude', 'codex', 'grok'], roles=['developer', 'security'])
        assert client.put('/api/profile', json=prefs).status_code == 200
        yield client, client.app.state.sessions, settings, calls, openclaw, prefs


def test_checks_are_deterministic_and_name_the_fix(setup_app):
    c, _, settings, calls, _, _ = setup_app
    body = c.get('/api/profile/coordinator-bootstrap/setup').json()
    rows = {r['id']: r for r in body['checks']}
    assert rows['openclaw']['state'] == 'ready' and rows['openclaw']['model'] == 'openrouter/free'
    assert rows['grok']['state'] == 'missing' and rows['grok']['link'] == '/profile#agent-tools'
    assert rows['claude']['state'] == 'needs_action' and rows['claude']['link'] == '/agents?action=billing'
    assert rows['codex']['state'] == 'ready'
    assert not any('agents' in argv for argv in calls)  # checking runs only --version
    assert body['digest'] == c.get('/api/profile/coordinator-bootstrap/setup').json()['digest']


def test_apply_creates_only_missing_agents_and_never_overwrites(setup_app):
    c, _, settings, calls, openclaw, _ = setup_app
    preview = c.get('/api/profile/coordinator-bootstrap/setup').json()
    developer, security = agent_setup.agent_id(settings, 'developer'), agent_setup.agent_id(settings, 'security')
    actions = {ch['id']: ch['action'] for ch in preview['changes']}
    assert actions[developer] == 'create' and actions[security] == 'keep'
    assert not preview['verified']
    folder = next(ch['path'] for ch in preview['changes'] if ch['id'] == developer)
    from pathlib import Path
    Path(folder).mkdir(parents=True)
    (Path(folder) / 'SOUL.md').write_text('mine')
    assert c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': '0' * 16}).status_code == 409
    done = c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': preview['digest']})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body['verified'] and all(ch['action'] == 'keep' for ch in body['changes'])
    assert (Path(folder) / 'SOUL.md').read_text() == 'mine'
    assert settings.product_short_name in (Path(folder) / 'AGENTS.md').read_text()
    adds = [argv for argv in calls if argv[1:3] == ['agents', 'add']]
    assert [a[3] for a in adds] == [developer] and '--non-interactive' in adds[0]
    assert body['last']['results'][0]['outcome'] == 'done'


def test_custom_mode_makes_no_changes(setup_app):
    c, _, _, calls, _, prefs = setup_app
    prefs['coordinator_bootstrap']['mode'] = 'custom'
    assert c.put('/api/profile', json=prefs).status_code == 200
    body = c.get('/api/profile/coordinator-bootstrap/setup').json()
    assert body['mode'] == 'custom' and body['changes'] == []
    assert body['verified']  # OpenClaw already has an agent and is ready
    assert c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': body['digest']}).status_code == 409
    assert not any(argv[1:3] == ['agents', 'add'] for argv in calls)


def test_validation_project_waits_for_setup_then_runs_one_read_story_per_ready_platform(setup_app):
    c, sessions, settings, _, _, _ = setup_app
    refused = c.post('/api/profile/coordinator-bootstrap/start')
    assert refused.status_code == 409
    preview = c.get('/api/profile/coordinator-bootstrap/setup').json()
    assert c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': preview['digest']}).json()['verified']
    first = c.post('/api/profile/coordinator-bootstrap/start')
    assert first.status_code == 201, first.text
    pid = first.json()['project_id']
    assert c.post('/api/profile/coordinator-bootstrap/start').json()['project_id'] == pid
    nodes = c.get(f'/api/projects/{pid}').json()['document']['nodes']
    stories = [n for n in nodes if n['assignee'] != 'human']
    assert [n['assignee'] for n in stories] == ['openclaw', 'codex']
    assert stories[0]['agent_target'] == agent_setup.agent_id(settings, 'developer') and stories[0]['mode'] == 'read'
    assert nodes[-1]['assignee'] == 'human' and nodes[-1]['depends_on'] == ['validate-openclaw', 'validate-codex']
    result = c.post(f'/api/projects/{pid}/submit', json={'revision': 1, 'approve_coordination': True, 'approve_api_work': True})
    assert result.status_code == 200, result.text
    with sessions() as s:
        assert not list(s.scalars(select(Run.id)))
