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
    extra_cli_agents = []  # agents the CLI reports that the config file does not show (seen on a Pi)

    def fake_run(argv, timeout=30, limit=2000):
        calls.append(argv)
        if argv[-1] == '--version':
            return 0, 'tool 2026.6.11'
        if argv[1:4] == ['agents', 'list', '--json']:
            listed = json.loads(openclaw.read_text())['agents']['list'] + extra_cli_agents
            return 0, '[plugins] ready\n' + json.dumps([{'id': a['id'], 'isDefault': False} for a in listed])
        if argv[1:3] == ['agents', 'add']:
            cfg = json.loads(openclaw.read_text())
            cfg['agents']['list'].append({'id': argv[3]})
            openclaw.write_text(json.dumps(cfg))
            return 0, '{}'
        return 1, 'unexpected'

    monkeypatch.setattr(agent_setup, 'run', fake_run)
    monkeypatch.setattr(agent_setup, '_JOB', None)
    with client:
        # Product defaults differ (RCD free-only, MCD subscription), so pin billing: Claude Code not set up, Codex on Subscription.
        assert client.patch('/api/billing', json={'accounts': {'claude': {'mode': 'api', 'monthly_usd': 0}, 'codex': {'mode': 'subscription', 'monthly_usd': 20}}}).status_code == 200
        prefs = client.get('/api/profile').json()['preferences']
        prefs['coordinator_bootstrap'].update(platforms=['openclaw', 'claude', 'codex', 'grok'], roles=['developer', 'security'])
        assert client.put('/api/profile', json=prefs).status_code == 200
        yield client, client.app.state.sessions, settings, calls, openclaw, prefs, extra_cli_agents


def test_checks_are_deterministic_and_name_the_fix(setup_app):
    c, _, settings, calls, _, _, _ = setup_app
    body = c.get('/api/profile/coordinator-bootstrap/setup').json()
    rows = {r['id']: r for r in body['checks']}
    assert rows['openclaw']['state'] == 'ready' and rows['openclaw']['model'] == 'openrouter/free'
    assert rows['grok']['state'] == 'missing' and rows['grok']['link'] == '/profile#agent-tools'
    assert rows['claude']['state'] == 'needs_action' and rows['claude']['link'] == '/agents?action=billing'
    assert rows['codex']['state'] == 'ready'
    assert not any(argv[1:3] == ['agents', 'add'] for argv in calls)  # checking never registers anything
    assert body['digest'] == c.get('/api/profile/coordinator-bootstrap/setup').json()['digest']


def test_apply_creates_only_missing_agents_and_never_overwrites(setup_app):
    c, _, settings, calls, openclaw, _, _ = setup_app
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
    started = c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': preview['digest']})
    assert started.status_code == 200, started.text
    assert started.json()['job']['items'][0]['id'] == developer
    agent_setup.wait()
    body = c.get('/api/profile/coordinator-bootstrap/setup').json()
    assert body['job']['state'] == 'done' and body['job']['items'][0]['state'] == 'done'
    assert any(line.startswith('$ openclaw agents add ' + developer) for line in body['job']['log'])
    assert any('Kept existing' in line and 'SOUL.md' in line for line in body['job']['log'])
    assert body['verified'] and all(ch['action'] == 'keep' for ch in body['changes'])
    assert (Path(folder) / 'SOUL.md').read_text() == 'mine'
    assert settings.product_short_name in (Path(folder) / 'AGENTS.md').read_text()
    adds = [argv for argv in calls if argv[1:3] == ['agents', 'add']]
    assert [a[3] for a in adds] == [developer] and '--non-interactive' in adds[0]
    assert body['last']['results'][0]['outcome'] == 'done'


def test_a_failed_registration_is_reported_and_the_others_still_apply(setup_app, monkeypatch):
    c, _, settings, calls, _, prefs, _ = setup_app
    prefs['coordinator_bootstrap']['roles'] = ['developer', 'security', 'reviewer']
    assert c.put('/api/profile', json=prefs).status_code == 200
    real = agent_setup.run
    monkeypatch.setattr(agent_setup, 'run', lambda argv, timeout=30, limit=2000: (1, 'gateway down') if argv[1:4] == ['agents', 'add', agent_setup.agent_id(settings, 'developer')] else real(argv, timeout, limit))
    preview = c.get('/api/profile/coordinator-bootstrap/setup').json()
    assert c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': preview['digest']}).status_code == 200
    agent_setup.wait()
    body = c.get('/api/profile/coordinator-bootstrap/setup').json()
    states = {i['id']: i['state'] for i in body['job']['items']}
    assert states[agent_setup.agent_id(settings, 'developer')] == 'failed' and states[agent_setup.agent_id(settings, 'reviewer')] == 'done'
    assert body['job']['state'] == 'failed' and not body['verified'] and 'gateway down' in json.dumps(body['last'])


def test_agents_the_cli_reports_count_as_registered_even_when_the_config_file_omits_them(setup_app):
    c, _, settings, calls, _, _, extra = setup_app
    extra.append({'id': agent_setup.agent_id(settings, 'developer')})
    body = c.get('/api/profile/coordinator-bootstrap/setup').json()
    agents = [ch for ch in body['changes'] if ch['kind'] == 'agent']
    assert agents and all(ch['action'] == 'keep' for ch in agents)
    assert agent_setup.agent_id(settings, 'developer') in body['agents']


def test_a_project_can_submit_to_an_agent_only_the_cli_reports(setup_app, monkeypatch):
    # The Pi case: OpenClaw lists the role agent, its config file does not. Submission checks targets through native_routes.
    import native_routes
    c, _, settings, _, _, _, extra = setup_app
    developer = agent_setup.agent_id(settings, 'developer')
    extra.append({'id': developer})
    monkeypatch.setattr(native_routes, '_cli_agents', lambda settings, wait=False: [{'id': developer, 'name': developer, 'model': '', 'default': False}])
    assert developer in {t['id'] for t in native_routes.read(settings)['openclaw']['targets']}
    preview = c.get('/api/profile/coordinator-bootstrap/setup').json()
    assert c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': preview['digest']}).status_code == 200
    agent_setup.wait()
    first = c.post('/api/profile/coordinator-bootstrap/start')
    assert first.status_code == 201, first.text
    pid = first.json()['project_id']
    result = c.post(f'/api/projects/{pid}/submit', json={'revision': 1, 'approve_coordination': True, 'approve_api_work': True})
    assert result.status_code == 200, result.text


def test_an_agent_that_already_exists_is_not_a_failure(setup_app, monkeypatch):
    c, _, settings, _, _, _, _ = setup_app
    real = agent_setup.run
    monkeypatch.setattr(agent_setup, 'run', lambda argv, timeout=30, limit=2000: (1, 'Error: agent "x" already exists') if argv[1:3] == ['agents', 'add'] else real(argv, timeout, limit))
    preview = c.get('/api/profile/coordinator-bootstrap/setup').json()
    assert c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': preview['digest']}).status_code == 200
    agent_setup.wait()
    job = c.get('/api/profile/coordinator-bootstrap/setup').json()['job']
    assert job['state'] == 'done' and 'Already registered' in job['items'][0]['detail']


def test_custom_mode_makes_no_changes(setup_app):
    c, _, _, calls, _, prefs, _ = setup_app
    prefs['coordinator_bootstrap']['mode'] = 'custom'
    assert c.put('/api/profile', json=prefs).status_code == 200
    body = c.get('/api/profile/coordinator-bootstrap/setup').json()
    assert body['mode'] == 'custom' and body['changes'] == []
    assert body['verified']  # OpenClaw already has an agent and is ready
    assert c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': body['digest']}).status_code == 409
    assert not any(argv[1:3] == ['agents', 'add'] for argv in calls)


def test_validation_project_waits_for_setup_then_runs_one_read_story_per_ready_platform(setup_app):
    c, sessions, settings, _, _, _, _ = setup_app
    refused = c.post('/api/profile/coordinator-bootstrap/start')
    assert refused.status_code == 409
    preview = c.get('/api/profile/coordinator-bootstrap/setup').json()
    assert c.post('/api/profile/coordinator-bootstrap/setup/apply', json={'digest': preview['digest']}).status_code == 200
    agent_setup.wait()
    assert c.get('/api/profile/coordinator-bootstrap/setup').json()['verified']
    first = c.post('/api/profile/coordinator-bootstrap/start')
    assert first.status_code == 201, first.text
    pid = first.json()['project_id']
    assert c.post('/api/profile/coordinator-bootstrap/start').json()['project_id'] == pid
    nodes = c.get(f'/api/projects/{pid}').json()['document']['nodes']
    stories = [n for n in nodes if n['assignee'] != 'human']
    assert [n['assignee'] for n in stories] == ['openclaw', 'codex']
    assert stories[0]['agent_target'] == agent_setup.agent_id(settings, 'developer') and stories[0]['mode'] == 'read'
    # Each story names its model: the dispatch gate refuses a blank one (PRICE_UNKNOWN).
    assert stories[0]['model'] == 'openrouter/free' and stories[1]['model'] == 'gpt-6-luna'
    assert nodes[-1]['assignee'] == 'human' and nodes[-1]['depends_on'] == ['validate-openclaw', 'validate-codex']
    result = c.post(f'/api/projects/{pid}/submit', json={'revision': 1, 'approve_coordination': True, 'approve_api_work': True})
    assert result.status_code == 200, result.text
    with sessions() as s:
        assert not list(s.scalars(select(Run.id)))


def test_the_real_runner_starts_a_command_with_this_products_agent_environment():
    # Not faked: building the environment must work in this product (MCD and RCD build it differently).
    import sys
    code, out = agent_setup.run([sys.executable, '-c', 'import os; print("ok", "MAC_CONTROL_DATA_DIR" in os.environ)'])
    assert (code, out) == (0, 'ok False')
