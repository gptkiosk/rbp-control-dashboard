"""Fix automatically: raise risks to their area minimum and move high-risk stories off free routes, as a new reviewable revision."""
import pytest

from agents import AgentSpec
from settings import get_settings
import projects


@pytest.fixture
def app(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(AgentSpec, 'available', lambda self, settings: True)
    client = make_client()
    cfg = tmp_path / 'hermes.yaml'
    cfg.write_text('model:\n  default: openrouter/free\n')
    settings = get_settings()
    settings.hermes_config_path = cfg
    with client:
        yield client, client.app.state.sessions, settings, tmp_path / 'ws/proj'


def story(key, area, risk, assignee='openclaw', model='', routes=(), mode='edit'):
    return dict(key=key, title=key, description='Do it.', scope='This folder.', acceptance='It works.', assignee=assignee, model=model, mode=mode,
                routes=[dict(agent=a, model=m) for a, m in routes], work_kind='implement', size='s', risk=risk, estimate_minutes=45,
                area=area, route_reason='Planner choice.')


def test_fix_raises_risk_and_moves_high_risk_stories_off_free_routes(app, monkeypatch):
    c, sessions, settings, workspace = app
    import route_reliability
    # No subscription route on this host, so a high-risk story with no paid fallback is left for the operator (products differ by default).
    monkeypatch.setattr(route_reliability, 'options', lambda s, st: [{'agent': 'openclaw', 'model': 'vendor/m:free', 'allowed': True, 'price_class': 'free'}])
    handoffs = [('hermes', 'google/gemma-4-31b-it:free'), ('claude', 'claude-haiku-5-5'), ('codex', 'gpt-6-luna')]
    nodes = [
        story('deploy-config', 'infrastructure-and-deployment', 'high', 'hermes', 'google/gemma-4-31b-it:free', handoffs),
        story('deploy-verify', 'infrastructure-and-deployment', 'low', 'claude', 'claude-haiku-5-5', mode='read'),
        story('ci-verify', 'dependencies-and-supply-chain', 'low', 'codex', 'gpt-6-luna', mode='read'),
        story('stuck', 'infrastructure-and-deployment', 'high', 'openclaw', 'vendor/m:free'),
    ]
    with sessions() as s:
        p = projects.create(s, dict(title='Arcade', brief='Build it.', working_dir=str(workspace), nodes=nodes), settings, 'operator')
        s.commit(); pid = p.id
    check = c.get(f'/api/projects/{pid}').json()['standards_check']
    assert len(check['problems']) == len(set(check['problems'])) >= 4 and check['fixable'] >= 4
    done = c.post(f'/api/projects/{pid}/standards-fix', json={'revision': 1})
    assert done.status_code == 200, done.text
    body = done.json()
    by_key = {n['key']: n for n in body['document']['nodes']}
    assert by_key['deploy-verify']['risk'] == 'high' and by_key['ci-verify']['risk'] == 'medium'
    assert (by_key['deploy-config']['assignee'], by_key['deploy-config']['model']) == ('claude', 'claude-haiku-5-5')
    assert by_key['deploy-config']['routes'] == [{'agent': 'codex', 'model': 'gpt-6-luna'}]
    assert body['revision'] == 2 and any('raised to high' in f for f in body['fixed'])
    # The story with no non-free fallback is left for the operator, and said so.
    assert body['standards_check']['problems'] == ['stuck: a high-risk story must not use a free-only route; choose a subscription route or a human review']
    assert c.post(f'/api/projects/{pid}/standards-fix', json={'revision': 2}).status_code == 409
    memory = ' '.join(m['text'] for m in body.get('memory', [])) if isinstance(body.get('memory'), list) else ''
    assert not memory or 'Standards fixed automatically' in memory


def test_a_stale_revision_is_refused(app):
    c, sessions, settings, workspace = app
    with sessions() as s:
        p = projects.create(s, dict(title='Arcade', brief='Build it.', working_dir=str(workspace),
                                    nodes=[story('ci-verify', 'dependencies-and-supply-chain', 'low', 'codex', 'gpt-6-luna')]), settings, 'operator')
        s.commit(); pid = p.id
    assert c.post(f'/api/projects/{pid}/standards-fix', json={'revision': 5}).status_code in (409, 422)


def test_stories_without_a_priced_model_get_a_free_model_and_free_fallbacks(app, monkeypatch):
    c, sessions, settings, workspace = app
    import route_reliability
    monkeypatch.setattr(route_reliability, 'options', lambda s, st: [
        {'agent': 'openclaw', 'model': 'vendor/a:free', 'allowed': True, 'price_class': 'free'},
        {'agent': 'openclaw', 'model': 'vendor/b:free', 'allowed': True, 'price_class': 'free'},
        {'agent': 'openclaw', 'model': 'vendor/unreviewed:free', 'allowed': False, 'price_class': None},
        {'agent': 'claude', 'model': 'claude-haiku-5-5', 'allowed': True, 'price_class': 'subscription'}])
    proposed = {'nodes': [{**n, 'kind': 'story', 'agent_target': ''} for n in (story('ui', 'business-logic', 'medium', 'openclaw', ''),
                          story('risky', 'infrastructure-and-deployment', 'high', 'openclaw', ''),
                          story('named', 'business-logic', 'medium', 'claude', 'claude-haiku-5-5'))]}
    with sessions() as s:
        changed = projects.pin_free_routes(s, proposed, settings)
    by = {n['key']: n for n in proposed['nodes']}
    assert changed == ['ui']
    assert by['ui']['model'] == 'vendor/a:free' and by['ui']['routes'] == [{'agent': 'openclaw', 'model': 'vendor/b:free'}]
    assert by['risky']['model'] == '' and by['risky']['routes'] == []  # high risk: no free main model and no free fallbacks
    assert by['named']['model'] == 'claude-haiku-5-5' and by['named']['routes'] == []


def test_one_route_for_every_agent_story(app, monkeypatch):
    c, sessions, settings, workspace = app
    import route_reliability
    monkeypatch.setattr(route_reliability, 'options', lambda s, st: [
        {'agent': 'claude', 'model': 'claude-haiku-5-5', 'allowed': True, 'price_class': 'subscription'},
        {'agent': 'openclaw', 'model': 'vendor/a:free', 'allowed': True, 'price_class': 'free'},
        {'agent': 'codex', 'model': 'gpt-6-luna', 'allowed': False, 'price_class': 'subscription'}])
    nodes = [story('a', 'business-logic', 'medium', 'openclaw', 'vendor/a:free', [('claude', 'claude-haiku-5-5'), ('codex', 'gpt-6-luna')]),
             story('b', 'infrastructure-and-deployment', 'high', 'hermes', 'vendor/x:free'),
             dict(story('h', 'business-logic', 'low', 'human'), mode='read')]
    with sessions() as s:
        p = projects.create(s, dict(title='Arcade', brief='Build it.', working_dir=str(workspace), nodes=nodes), settings, 'operator')
        s.commit(); pid = p.id
    assert c.post(f'/api/projects/{pid}/route-all', json={'revision': 1, 'agent': 'codex', 'model': 'gpt-6-luna'}).status_code == 422
    done = c.post(f'/api/projects/{pid}/route-all', json={'revision': 1, 'agent': 'claude', 'model': 'claude-haiku-5-5'})
    assert done.status_code == 200, done.text
    body = done.json(); by = {n['key']: n for n in body['document']['nodes']}
    assert body['routed'] == ['a', 'b'] and body['revision'] == 2
    assert all((by[k]['assignee'], by[k]['model']) == ('claude', 'claude-haiku-5-5') for k in 'ab')
    # Failover is kept: only the chosen route leaves the fallback list, every other fallback stays.
    assert by['a']['routes'] == [{'agent': 'codex', 'model': 'gpt-6-luna'}] and by['h']['assignee'] == 'human'
    free = c.post(f'/api/projects/{pid}/route-all', json={'revision': 2, 'agent': 'openclaw', 'model': 'vendor/a:free'}).json()
    assert free['routed'] == ['a'] and free['skipped'] == ['b']  # the high-risk story stays off the free route


def test_route_for_all_can_set_the_backups_too(app, monkeypatch):
    c, sessions, settings, workspace = app
    import route_reliability
    monkeypatch.setattr(route_reliability, 'options', lambda s, st: [
        {'agent': 'claude', 'model': 'claude-haiku-5-5', 'allowed': True, 'price_class': 'subscription'},
        {'agent': 'codex', 'model': 'gpt-6-luna', 'allowed': True, 'price_class': 'subscription'},
        {'agent': 'openclaw', 'model': 'vendor/a:free', 'allowed': True, 'price_class': 'free'}])
    nodes = [story('a', 'business-logic', 'medium', 'openclaw', 'vendor/a:free', [('hermes', 'vendor/old:free')]),
             story('b', 'infrastructure-and-deployment', 'high', 'codex', 'gpt-6-luna')]
    with sessions() as s:
        p = projects.create(s, dict(title='Arcade', brief='Build it.', working_dir=str(workspace), nodes=nodes), settings, 'operator')
        s.commit(); pid = p.id
    backups = [{'agent': 'codex', 'model': 'gpt-6-luna'}, {'agent': 'openclaw', 'model': 'vendor/a:free'}]
    body = c.post(f'/api/projects/{pid}/route-all', json={'revision': 1, 'agent': 'claude', 'model': 'claude-haiku-5-5', 'backups': backups}).json()
    by = {n['key']: n for n in body['document']['nodes']}
    assert by['a']['routes'] == backups                                   # the chosen backups, in order, replace the old ones
    assert by['b']['routes'] == [{'agent': 'codex', 'model': 'gpt-6-luna'}]  # high risk: the free backup is left off


def test_fix_moves_a_high_risk_story_with_no_paid_fallback_to_a_subscription_route(app, monkeypatch):
    c, sessions, settings, workspace = app
    import route_reliability
    monkeypatch.setattr(route_reliability, 'options', lambda s, st: [
        {'agent': 'openclaw', 'model': 'vendor/a:free', 'allowed': True, 'price_class': 'free'},
        {'agent': 'claude', 'model': 'claude-haiku-5-5', 'allowed': True, 'price_class': 'subscription'}])
    # The Pi case: raising the risk makes the story high, and it has no fallback that is not free.
    nodes = [story('deploy-verify', 'infrastructure-and-deployment', 'low', 'hermes', 'vendor/x:free', mode='read')]
    with sessions() as s:
        p = projects.create(s, dict(title='Arcade', brief='Build it.', working_dir=str(workspace), nodes=nodes), settings, 'operator')
        s.commit(); pid = p.id
    assert c.get(f'/api/projects/{pid}').json()['standards_check']['fixable'] == 2
    body = c.post(f'/api/projects/{pid}/standards-fix', json={'revision': 1}).json()
    n = body['document']['nodes'][0]
    assert (n['risk'], n['assignee'], n['model']) == ('high', 'claude', 'claude-haiku-5-5')
    assert any('cheapest subscription route' in f for f in body['fixed'])
    assert body['standards_check']['problems'] == []


def test_stories_see_the_whole_brief(app):
    c, sessions, settings, workspace = app
    brief = 'Concept art: neon arcade, CRT glow. ' + 'x' * 7400 + ' FINAL-LINE-OF-THE-BRIEF'
    with sessions() as s:
        p = projects.create(s, dict(title='Arcade', brief=brief, working_dir=str(workspace),
                                    nodes=[story('a', 'business-logic', 'medium', 'claude', 'claude-haiku-5-5')]), settings, 'operator')
        from project_schemas import Action
        projects.submit(s, p, Action(revision=1, approve_coordination=True, approve_api_work=True), settings, 'operator')
        payload = projects.context_payload(s, p, 'a') if hasattr(projects, 'context_payload') else None
        s.commit()
    if payload is not None:
        assert payload['brief'] == brief and 'omitted' not in payload['brief']
    assert projects._context_excerpt(brief, projects.BRIEF_LIMIT) == brief
