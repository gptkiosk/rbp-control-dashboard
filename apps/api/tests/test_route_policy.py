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
    (settings.data_dir / 'models/openrouter.json').write_text(json.dumps({'fetched_at': 1792000000, 'models': [
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


def test_unreviewed_price_counts_as_paid_except_while_planning():
    unknown = route('hermes', 'x-ai/grok-4.6', None)
    assert rp.reason(unknown, None, rp.Policy(), None, 'chat') == 'App policy: paid API is off (price not reviewed, so it counts as paid)'
    assert rp.reason(unknown, None, rp.Policy(cost=rp.Cost(paid=True)), None, 'chat') is None
    assert rp.reason(unknown, None, rp.Policy(), None, 'planner', unknown_ok=True) is None
    assert rp.reason(unknown, None, rp.Policy(providers=['anthropic']), None, 'planner', unknown_ok=True) == 'App policy: xai is not an allowed provider'
    assert rp.reason(route('grok', 'grok-4.6'), None, rp.Policy(), None, 'coordinator', 'hermes') == 'The Coordinator is hermes (Settings → Agent roles)'
    assert rp.reason(route('codex', 'gpt-6.1-sol'), None, rp.Policy(), None, 'coordinator', 'codex') is None


def test_membership_comes_before_free_and_paid_api_is_the_last_resort():
    assert sorted(['paid', None, 'free', 'subscription'], key=rp.cost_rank) == ['subscription', 'free', 'paid', None]


def test_the_first_policy_keeps_what_the_host_allowed_and_retires_the_switches(sessions, monkeypatch):
    from types import SimpleNamespace
    from models import BillingConfig
    with sessions() as s:
        assert rp.default_app(s, SimpleNamespace(dispatch_free_only=True)).cost == rp.Cost(free=True, membership=True, paid=False)
        assert rp.default_app(s, SimpleNamespace(dispatch_free_only=False)).cost == rp.Cost(free=True, membership=True, paid=True)
        s.add(BillingConfig(id=1, payload=json.dumps({'limits': {'allow_subscription_in_free_only': False, 'allow_paid_in_free_only': True, 'per_run_cap_usd': 2}})))
        s.flush()
        assert rp.default_app(s, SimpleNamespace(dispatch_free_only=True)).cost == rp.Cost(free=True, membership=False, paid=True)
        assert rp.ensure_saved(s, SimpleNamespace(dispatch_free_only=True)) is True
        assert rp.ensure_saved(s, SimpleNamespace(dispatch_free_only=False)) is False      # written once; the retired setting is not read again
        payload = json.loads(s.get(BillingConfig, 1).payload)
        assert payload['limits'] == {'per_run_cap_usd': 2} and payload['route_policy']['cost'] == {'free': True, 'membership': False, 'paid': True}


def test_free_models_from_any_provider_never_include_router_aliases():
    xai_free = rp.Policy(providers=['xai'], any_free=True)
    assert rp.reason(route('hermes', 'google/gemma-4-31b-it:free', 'free'), None, xai_free, None, 'chat') is None
    assert rp.reason(route('hermes', 'openrouter/free', 'free'), None, xai_free, None, 'chat') == 'App policy: provider varies per request'
    assert rp.reason(route('hermes', 'anthropic/claude-sonnet-5-5', 'paid'), None, rp.Policy(providers=['xai'], any_free=True, cost=rp.Cost(paid=True)), None, 'chat') \
        == 'App policy: anthropic is not an allowed provider'
    assert rp.reason(route('hermes', 'google/gemma-4-31b-it:free', 'free'), None, rp.Policy(cost=rp.Cost(free=False)), None, 'chat') == 'App policy: free models are off'


def test_routes_api_lists_allowed_and_hidden_routes_with_reasons(app):
    c, _, settings, _ = app
    assert c.patch('/api/routes/policy/cost', json={'paid': False}).status_code == 200   # the seeded value differs by product (RCD off, MCD on)
    planner = c.get('/api/routes', params={'feature': 'planner'}).json()
    allowed = keys(planner['allowed'])
    assert {('claude', 'claude-opus-5-5'), ('codex', 'gpt-6.1-sol'), ('grok', 'grok-build-0.1'), ('hermes', 'openrouter/free')} <= allowed
    hidden = {(r['runtime'], r['model']): r['hidden_because'] for r in planner['hidden']}
    assert hidden[('hermes', 'x-ai/grok-4.5')] == 'App policy: paid API is off (price not reviewed, so it counts as paid)'
    assert planner['scope'] == {'managed': False, 'managed_error': None, 'app_saved': True, 'project': None}   # written once at startup
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
    # x-ai/grok-4.5 is reviewed as paid; x-ai/grok-4.6 (added from the cached OpenRouter list once a policy names xAI) is unreviewed, which
    # counts as paid. The reviewed one comes first.
    assert [(r['runtime'], r['model']) for r in coordinator['allowed']] == [('hermes', 'x-ai/grok-4.5'), ('hermes', 'x-ai/grok-4.6')]
    assert coordinator['default'] == {'runtime': 'hermes', 'model': 'x-ai/grok-4.5'}
    assert 'openrouter/free' in coordinator['default_note'] and 'provider varies' in coordinator['default_note']
    hidden = {(r['runtime'], r['model']): r['hidden_because'] for r in coordinator['hidden']}
    assert hidden[('grok', 'grok-4.6')] == 'The Coordinator is hermes (Settings → Agent roles)'
    planner_hidden = {(r['runtime'], r['model']): r['hidden_because'] for r in c.get('/api/routes', params={'feature': 'planner'}).json()['hidden']}
    assert planner_hidden[('hermes', 'x-ai/grok-4.6')] == 'App policy: paid API is off (price not reviewed, so it counts as paid)'


def test_nothing_allowed_says_why(app):
    c, _, _, _ = app
    assert c.put('/api/routes/policy', json={'policy': {'providers': ['xai'], 'cost': {'free': True, 'membership': False, 'paid': False}}, 'confirm': True}).status_code == 200
    body = c.get('/api/routes', params={'feature': 'coordinator'}).json()
    assert body['allowed'] == [] and body['default'] is None
    # The nearest route is named with its actionable reason, not the policy filter that removed the rest.
    assert body['empty_reason'] == 'No Coordinator route is allowed. Nearest: Hermes · x-ai/grok-4.5: App policy: paid API is off (price not reviewed, so it counts as paid).'


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


def test_xai_lockdown_end_to_end(app):
    """Managed xAI policy: Hermes coordinates on an xAI model (paid API, approved per plan), Grok Build plans, runs stories and chats, and
    nothing else is offered, planned, submitted or admitted."""
    c, sessions, settings, tmp_path = app
    from models import Card, ChatThread, Project
    from project_schemas import Action
    settings.dispatch_route_classes = {'hermes||x-ai/grok-4.5': 'paid'}
    managed = tmp_path / 'managed.json'
    managed.write_text(json.dumps({'providers': ['xai'], 'cost': {'free': False, 'membership': True, 'paid': False},
                                   'features': {'coordinator': {'providers': ['xai'], 'cost': {'free': False, 'membership': False, 'paid': True}}}}))
    settings.managed_route_policy = managed
    workspace = tmp_path / 'ws/proj'
    workspace.mkdir(parents=True, exist_ok=True)
    settings.workdir_roots = (tmp_path / 'ws',)
    # The app policy cannot widen the managed one, even with every cost class switched on.
    assert c.patch('/api/routes/policy/cost', json={'free': True, 'membership': True, 'paid': True}).status_code == 200
    for feature in ('planner', 'stories', 'chat', 'tasks'):
        assert {r['runtime'] for r in c.get('/api/routes', params={'feature': feature}).json()['allowed']} == {'grok'}, feature
    created = c.post('/api/projects', json={'title': 'Lockdown', 'brief': 'Inspect one file.', 'working_dir': str(workspace)})
    assert created.status_code == 201, created.text
    pid = created.json()['id']
    plan = {'revision': 1, 'approve_coordination': True}
    refused = c.post(f'/api/projects/{pid}/plan', json=plan)
    assert refused.status_code == 422 and 'x-ai/grok-4.5 uses API billing' in refused.json()['detail']
    planned = c.post(f'/api/projects/{pid}/plan', json={**plan, 'approve_api_planning': True})
    assert planned.status_code == 200, planned.text
    with sessions() as s:
        p = s.get(Project, pid)
        pipeline = json.loads(p.pipeline)
        assert pipeline['delegator'] == {'agent': 'hermes', 'model': 'x-ai/grok-4.5'}
        assert pipeline['choices'] and {r['agent'] for r in pipeline['choices']} == {'grok'}
        assert {row['agent'] for row in pipeline['execution_catalog']} == {'grok'}
        coordinate = s.get(Card, pipeline['card_id'])
        assert (coordinate.agent, coordinate.model) == ('hermes', 'x-ai/grok-4.5')
        assert rp.run_reason(s, settings, coordinate, coordinate.model) is None
        # A story on another provider is refused at admission; a Grok Build story is admitted.
        outsider = Card(agent='claude', model='claude-opus-5-5', title='x', body='x', mode='read', working_dir=str(workspace), column='queued',
                        position=1, timeout_s=30, created_by='test', created_at=1, updated_at=1)
        s.add(outsider); s.flush()
        assert rp.run_reason(s, settings, outsider, 'claude-opus-5-5') == 'Managed by this installation: anthropic is not an allowed provider'
        outsider.agent, outsider.model = 'grok', 'grok-build-0.1'
        assert rp.run_reason(s, settings, outsider, 'grok-build-0.1') is None
        chat = ChatThread(agent='grok', model='grok-4.6', title='x', mode='read', working_dir=str(workspace), created_at=1, last_activity_at=1)
        s.add(chat); s.flush()
        assert rp.run_reason(s, settings, chat, 'grok-4.6') is None
        chat.agent, chat.model = 'hermes', 'openrouter/free'
        assert rp.run_reason(s, settings, chat, 'openrouter/free') == 'Managed by this installation: provider varies per request'
        # Plan checks block a story outside the policy and pass a Grok Build one.
        doc = {'nodes': [{'key': 'a', 'kind': 'story', 'assignee': 'codex', 'model': 'gpt-6.1-sol'},
                         {'key': 'b', 'kind': 'story', 'assignee': 'grok', 'model': 'grok-build-0.1', 'routes': [{'agent': 'claude', 'model': 'claude-haiku-5-5'}]}]}
        found = {f['id']: f for f in rp.story_findings(s, settings, doc, p)}
        assert found['route-policy']['severity'] == 'block' and found['route-policy']['stories'] == ['a']
        assert found['route-policy-backups']['severity'] == 'warn' and found['route-policy-backups']['stories'] == ['b']


def test_price_review_in_the_app_classifies_a_route_for_planning_and_admission(app):
    client, sessions, settings, _ = app
    # Listed paid models are candidates once the policy names their provider.
    policy = rp.Policy(providers=['xai', 'google'], cost=rp.Cost(free=True, membership=True, paid=True))
    assert client.put('/api/routes/policy', json={'policy': policy.model_dump(), 'confirm': True}).status_code == 200
    pending = client.get('/api/routes/prices').json()['pending']
    grok46 = next(r for r in pending if (r['runtime'], r['model']) == ('hermes', 'x-ai/grok-4.6'))
    gemma = next(r for r in pending if (r['runtime'], r['model']) == ('hermes', 'google/gemma-4-31b-it:free'))
    assert grok46['can_mark_free'] is False and gemma['can_mark_free'] is True
    # A listed paid model cannot be reviewed as free, and a membership is not set here.
    refused = client.put('/api/routes/prices', json={'runtime': 'hermes', 'model': 'x-ai/grok-4.6', 'cost_class': 'free'})
    assert refused.status_code == 422 and 'no cost' in refused.json()['detail']
    assert client.put('/api/routes/prices', json={'runtime': 'grok', 'model': 'grok-4.6', 'cost_class': 'subscription'}).status_code == 422
    body = client.put('/api/routes/prices', json={'runtime': 'hermes', 'model': 'x-ai/grok-4.6', 'cost_class': 'paid'}).json()
    assert {'runtime': 'hermes', 'target': '', 'model': 'x-ai/grok-4.6', 'cost_class': 'paid'} in body['reviewed']
    assert ('hermes', 'x-ai/grok-4.6') not in keys(body['pending'])
    assert client.put('/api/routes/prices', json={'runtime': 'hermes', 'model': 'google/gemma-4-31b-it:free', 'cost_class': 'free'}).status_code == 200
    from types import SimpleNamespace
    from dispatch_gate import reviewed_route_class
    with sessions() as s:
        assert reviewed_route_class(s, settings, SimpleNamespace(agent='hermes', agent_target=''), 'x-ai/grok-4.6') == 'paid'
        assert reviewed_route_class(s, settings, SimpleNamespace(agent='openclaw', agent_target=''), 'x-ai/grok-4.6') is None   # exact route only
    chat = client.get('/api/routes', params={'feature': 'chat'}).json()
    assert next(r for r in chat['allowed'] if r['model'] == 'x-ai/grok-4.6' and r['runtime'] == 'hermes')['cost_class'] == 'paid'
    # The installation's configured classes still win, and clearing a review returns the route to "not reviewed".
    settings.dispatch_route_classes = {'hermes||x-ai/grok-4.6': 'free'}
    try:
        with sessions() as s:
            assert reviewed_route_class(s, settings, SimpleNamespace(agent='hermes', agent_target=''), 'x-ai/grok-4.6') == 'free'
    finally:
        settings.dispatch_route_classes = {}
    body = client.put('/api/routes/prices', json={'runtime': 'hermes', 'model': 'x-ai/grok-4.6', 'cost_class': None}).json()
    assert ('hermes', 'x-ai/grok-4.6') in keys(body['pending'])


def test_managed_policy_names_the_runtimes_it_leaves(app):
    client, _, settings, tmp_path = app
    assert client.get('/api/routes/policy').json()['managed_runtimes'] is None
    assert rp.runtimes_allowed(rp.Policy(providers=['xai'])) == ['grok', 'hermes', 'openclaw']
    assert rp.runtimes_allowed(rp.Policy(cost=rp.Cost(free=True, membership=False, paid=False))) == ['hermes', 'openclaw']
    assert rp.runtimes_allowed(rp.Policy(runtimes=['grok'], features={'coordinator': rp.Filter(runtimes=['hermes'])})) == ['grok', 'hermes']
    managed = tmp_path / 'managed.json'
    managed.write_text(json.dumps({'providers': ['xai'], 'runtimes': ['grok', 'hermes']}))
    settings.managed_route_policy = managed
    try:
        assert client.get('/api/routes/policy').json()['managed_runtimes'] == ['grok', 'hermes']
        managed.write_text('not json')
        assert client.get('/api/routes/policy').json()['managed_runtimes'] == []
    finally:
        settings.managed_route_policy = None
