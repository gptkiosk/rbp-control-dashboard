"""Route policy and route catalog: synthetic configuration only; no provider or CLI is invoked."""
import json

import pytest

from agents import AgentSpec, REGISTRY
from settings import get_settings
import model_selection
import projects
import route_catalog
import route_policy as rp
import route_reliability


@pytest.fixture
def app(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(AgentSpec, 'available', lambda self, settings: True)
    client = make_client()
    cfg = tmp_path / 'hermes.yaml'
    cfg.write_text('model:\n  default: openrouter/free\nfallback_model:\n  - model: x-ai/grok-4.5\n')
    settings = get_settings()
    settings.hermes_config_path = cfg
    settings.dispatch_free_only = False
    (settings.data_dir / 'models').mkdir(parents=True, exist_ok=True)
    (settings.data_dir / 'models/openrouter.json').write_text(json.dumps({'models': [
        {'id': 'x-ai/grok-4.6', 'free': False, 'prompt_per_m': 3.0, 'completion_per_m': 15.0},
        {'id': 'google/gemma-4-31b-it:free', 'free': True, 'prompt_per_m': 0.0, 'completion_per_m': 0.0},
        {'id': 'anthropic/claude-sonnet-5-5', 'free': False, 'prompt_per_m': 3.0, 'completion_per_m': 15.0}]}))
    with client:
        assert client.patch('/api/billing', json={'accounts': {a: {'mode': 'subscription', 'monthly_usd': 20} for a in ('claude', 'codex', 'grok')}}).status_code == 200
        yield client, client.app.state.sessions, settings, tmp_path


def route(runtime, model, cost_class='subscription'):
    return {'runtime': runtime, 'model': model, 'provider': rp.provider_of(runtime, model), 'cost_class': cost_class}


def keys(rows):
    return {(r['runtime'], r['model']) for r in rows}


@pytest.mark.parametrize('runtime,model,provider', [
    ('claude', 'claude-opus-5-5', 'anthropic'), ('codex', 'gpt-6.1-sol', 'openai'), ('grok', 'grok-build-0.1', 'xai'),
    ('hermes', 'x-ai/grok-4.5', 'xai'), ('openclaw', 'openrouter/x-ai/grok-4.5', 'xai'), ('hermes', 'anthropic/claude-sonnet-5-5', 'anthropic'),
    ('hermes', 'google/gemma-4-31b-it:free', 'google'), ('hermes', 'meta-llama/llama-4:free', 'meta'), ('hermes', 'vendor/small:free', 'vendor'),
    ('hermes', 'openrouter/free', 'router'), ('openclaw', 'openrouter/openrouter/free', 'router'), ('hermes', 'openrouter/auto', 'router'),
    ('hermes', 'grok-4.5', 'xai'), ('hermes', '', 'router')])
def test_provider_is_who_makes_the_model_and_router_aliases_are_unknown(runtime, model, provider):
    assert rp.provider_of(runtime, model) == provider


def test_each_scope_only_narrows_and_says_why():
    xai = rp.Policy(providers=['xai'])
    assert rp.reason(route('grok', 'grok-4.6'), None, xai, None, 'planner') is None
    assert rp.reason(route('claude', 'claude-opus-5-5'), None, xai, None, 'planner') == 'App policy: anthropic is not an allowed provider'
    assert rp.reason(route('hermes', 'openrouter/free', 'free'), None, xai, None, 'planner') == 'App policy: provider varies per request'
    # A project cannot widen: no filter of its own, and paid switched on, still leaves the app's limits in force.
    wide = rp.Policy(cost=rp.Cost(paid=True))
    assert rp.reason(route('claude', 'claude-opus-5-5'), None, xai, wide, 'planner').startswith('App policy')
    assert rp.reason(route('hermes', 'x-ai/grok-4.5', 'paid'), None, xai, wide, 'planner') == 'App policy: paid API is off'
    # Narrower project filters apply on top; a feature's own rule replaces its scope's base rule for that feature.
    assert rp.reason(route('grok', 'grok-4.6'), None, xai, rp.Policy(models=rp.Models(allow=['grok-build-0.1'])), 'stories') == 'Project policy: not in the allowed models'
    stories = rp.Policy(features={'stories': rp.Filter(cost=rp.Cost(membership=False))})
    assert rp.reason(route('grok', 'grok-4.6'), None, stories, None, 'stories') == 'App policy: membership routes are off'
    assert rp.reason(route('grok', 'grok-4.6'), None, stories, None, 'planner') is None
    managed = rp.Policy(runtimes=['grok', 'hermes'])
    assert rp.reason(route('codex', 'gpt-6.1-sol'), managed, rp.Policy(), None, 'chat') == 'Managed by this installation: codex is not allowed'
    assert rp.reason(route('codex', 'gpt-6.1-sol'), None, rp.Policy(models=rp.Models(block=['gpt-6.1-sol'])), None, 'chat') == 'App policy: this model is blocked'


def test_free_models_from_any_provider_never_include_router_aliases():
    xai_free = rp.Policy(providers=['xai'], any_free=True)
    assert rp.reason(route('hermes', 'google/gemma-4-31b-it:free', 'free'), None, xai_free, None, 'chat') is None
    assert rp.reason(route('hermes', 'openrouter/free', 'free'), None, xai_free, None, 'chat') == 'App policy: provider varies per request'
    assert rp.reason(route('hermes', 'anthropic/claude-sonnet-5-5', 'paid'), None, rp.Policy(providers=['xai'], any_free=True, cost=rp.Cost(paid=True)), None, 'chat') \
        == 'App policy: anthropic is not an allowed provider'
    assert rp.reason(route('hermes', 'google/gemma-4-31b-it:free', 'free'), None, rp.Policy(cost=rp.Cost(free=False)), None, 'chat') == 'App policy: free models are off'


def test_unreviewed_price_is_never_offered_and_only_hermes_coordinates():
    assert rp.reason(route('hermes', 'x-ai/grok-4.6', None), None, rp.Policy(), None, 'chat').startswith('Price not reviewed')
    assert rp.reason(route('grok', 'grok-4.6'), None, rp.Policy(), None, 'coordinator') == 'Only Hermes coordinates in this version'


def test_default_policy_keeps_todays_cost_classes(app):
    c, sessions, settings, _ = app
    settings.dispatch_free_only = True
    with sessions() as s:
        policy, saved = rp.load_app(s, settings)
        assert not saved and policy.cost == rp.Cost(free=True, membership=False, paid=False)
    assert c.patch('/api/billing', json={'limits': {'allow_subscription_in_free_only': True}}).status_code == 200
    with sessions() as s:
        assert rp.load_app(s, settings)[0].cost == rp.Cost(free=True, membership=True, paid=False)
    settings.dispatch_free_only = False
    with sessions() as s:
        assert rp.load_app(s, settings)[0].cost == rp.Cost(free=True, membership=True, paid=True)


def test_routes_api_lists_allowed_and_hidden_routes_with_reasons(app):
    c, _, settings, _ = app
    planner = c.get('/api/routes', params={'feature': 'planner'}).json()
    allowed = keys(planner['allowed'])
    assert {('claude', 'claude-opus-5-5'), ('codex', 'gpt-6.1-sol'), ('grok', 'grok-build-0.1'), ('hermes', 'openrouter/free')} <= allowed
    hidden = {(r['runtime'], r['model']): r['hidden_because'] for r in planner['hidden']}
    assert hidden[('hermes', 'x-ai/grok-4.5')].startswith('Price not reviewed')
    assert planner['scope'] == {'managed': False, 'managed_error': None, 'app_saved': False, 'project': None}
    row = next(r for r in planner['allowed'] if r['model'] == 'grok-build-0.1')
    assert row['provider'] == 'xai' and row['cost_class'] == 'subscription' and row['reliability']['attempts'] == 0
    assert c.get('/api/routes', params={'feature': 'everything'}).status_code == 422


def test_grok_policy_leaves_one_clear_path_for_every_feature(app):
    """The lockdown example from the design: Grok Build for work, Hermes on an xAI model (API-billed) for the Coordinator only."""
    c, _, settings, _ = app
    settings.dispatch_route_classes = {'hermes||x-ai/grok-4.5': 'paid'}
    policy = {'providers': ['xai'], 'cost': {'free': False, 'membership': True, 'paid': False},
              'features': {'coordinator': {'providers': ['xai'], 'cost': {'free': False, 'membership': False, 'paid': True}}},
              'defaults': {'planner': {'runtime': 'grok', 'model': 'grok-build-0.1'}}}
    assert c.put('/api/routes/policy', json={'policy': policy, 'confirm': False}).status_code == 422
    saved = c.put('/api/routes/policy', json={'policy': policy, 'confirm': True})
    assert saved.status_code == 200 and saved.json()['app_saved']
    for feature in ('planner', 'stories', 'chat', 'tasks'):
        body = c.get('/api/routes', params={'feature': feature}).json()
        assert {r['runtime'] for r in body['allowed']} == {'grok'}, feature
    assert c.get('/api/routes', params={'feature': 'planner'}).json()['default'] == {'runtime': 'grok', 'model': 'grok-build-0.1'}
    coordinator = c.get('/api/routes', params={'feature': 'coordinator'}).json()
    assert keys(coordinator['allowed']) == {('hermes', 'x-ai/grok-4.5')}
    assert coordinator['default'] is None or coordinator['default'] == {'runtime': 'hermes', 'model': 'x-ai/grok-4.5'}
    assert 'openrouter/free' in coordinator['default_note'] and 'provider varies' in coordinator['default_note']
    hidden = {(r['runtime'], r['model']): r['hidden_because'] for r in coordinator['hidden']}
    assert hidden[('grok', 'grok-4.6')] == 'Only Hermes coordinates in this version'
    # The cached OpenRouter list adds xAI models for Hermes and OpenClaw once a policy names xAI; their price is still unreviewed.
    assert hidden[('hermes', 'x-ai/grok-4.6')].startswith('Price not reviewed')


def test_nothing_allowed_says_why(app):
    c, _, _, _ = app
    assert c.put('/api/routes/policy', json={'policy': {'providers': ['xai'], 'cost': {'free': True, 'membership': False, 'paid': False}}, 'confirm': True}).status_code == 200
    body = c.get('/api/routes', params={'feature': 'coordinator'}).json()
    assert body['allowed'] == [] and body['default'] is None
    assert body['empty_reason'].startswith('No Coordinator route is allowed. Most common reason:')


def test_managed_policy_cannot_be_widened_and_fails_closed(app):
    c, _, settings, tmp_path = app
    managed = tmp_path / 'managed.json'
    managed.write_text(json.dumps({'runtimes': ['grok', 'hermes'], 'providers': ['xai']}))
    settings.managed_route_policy = managed
    assert c.put('/api/routes/policy', json={'policy': {'cost': {'free': True, 'membership': True, 'paid': True}}, 'confirm': True}).status_code == 200
    body = c.get('/api/routes', params={'feature': 'chat'}).json()
    assert {r['runtime'] for r in body['allowed']} == {'grok'} and body['scope']['managed']
    hidden = {(r['runtime'], r['model']): r['hidden_because'] for r in body['hidden']}
    assert hidden[('claude', 'claude-opus-5-5')] == 'Managed by this installation: claude is not allowed'
    view = c.get('/api/routes/policy').json()
    assert view['managed']['providers'] == ['xai'] and view['managed_error'] is None
    managed.write_text('{"providers": "not a list"}')
    body = c.get('/api/routes', params={'feature': 'chat'}).json()
    assert body['allowed'] == [] and 'invalid' in body['scope']['managed_error']
    managed.unlink()
    assert c.get('/api/routes', params={'feature': 'chat'}).json()['allowed'] == []


def test_project_policy_narrows_and_keeps_the_saved_planner_as_default(app):
    c, sessions, settings, tmp_path = app
    workspace = tmp_path / 'ws/proj'
    workspace.mkdir(parents=True, exist_ok=True)
    settings.workdir_roots = (tmp_path / 'ws',)
    created = c.post('/api/projects', json={'title': 'Synthetic routes', 'brief': 'Inspect one file.', 'working_dir': str(workspace),
                                            'planner_agent': 'codex', 'planner_model': 'gpt-6.1-sol'})
    assert created.status_code == 201, created.text
    pid = created.json()['id']
    same = c.get('/api/routes', params={'feature': 'planner', 'project_id': pid}).json()
    assert same['scope']['project'] == 'same_as_app' and same['default'] == {'runtime': 'codex', 'model': 'gpt-6.1-sol'}
    doc = created.json()['document']
    doc['route_policy'] = {'runtimes': ['claude']}
    saved = c.patch(f'/api/projects/{pid}', json={'revision': created.json()['revision'], 'document': doc})
    assert saved.status_code == 200, saved.text
    narrowed = c.get('/api/routes', params={'feature': 'planner', 'project_id': pid}).json()
    assert narrowed['scope']['project'] == 'narrowed'
    assert {r['runtime'] for r in narrowed['allowed']} == {'claude'}
    assert narrowed['default']['runtime'] == 'claude' and 'codex is not allowed' in narrowed['default_note']


def test_damaged_saved_policy_never_widens(app):
    _, sessions, settings, _ = app
    from models import BillingConfig
    with sessions() as s:
        row = s.get(BillingConfig, 1)
        payload = json.loads(row.payload)
        payload['route_policy'] = {'providers': 'all of them'}
        row.payload = json.dumps(payload)
        s.commit()
        policy, saved = rp.load_app(s, settings)
        assert saved and policy.cost == rp.Cost(free=True, membership=False, paid=False)
    assert rp.load_project({'route_policy': {'runtimes': 'all'}}).runtimes == []


def test_former_model_lists_come_from_the_runtime_tables(app):
    """The scattered lists now read the agent registry; each route they name is in the catalog."""
    _, sessions, settings, _ = app
    found = {(r, m) for r, _, m in route_catalog.candidates(settings)}
    assert {(r['agent'], r['model']) for r in model_selection.planning_routes()} <= found
    for agent in ('claude', 'codex'):
        for bias in (0, 50, 100):
            assert (agent, projects.subscription_model(agent, bias)) in found
            assert (agent, projects.subscription_model(agent, bias, planner=True)) in found
    with sessions() as s:
        assert {(r['agent'], r['model']) for r in route_reliability.options(s, settings)} <= found
    for row in projects.execution_catalog(settings):
        assert {(row['agent'], m) for m in row['models']} <= found | {(row['agent'], m) for m in REGISTRY[row['agent']].suggested_models}
