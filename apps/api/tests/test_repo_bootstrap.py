"""Repository bootstrap: a private repository can be created only through the guarded action, only after the operator approves the exact preview."""
import json

import pytest

from github_actions import ActionError, GithubActionGuard, GithubActionTransport, plan
from github_config import GithubConfigStore
from github_read import GithubReader
from tests.test_auth import secured  # noqa: F401
from tests.test_profiles import call, paired, pref

ACTOR = 'operator@example.test'
ACCOUNT = 'operator'
NAME = 'bamcio-site'
REPO = f'{ACCOUNT}/{NAME}'


class Net:
    """GitHub as seen through `gh api`, with the answers a test needs."""
    def __init__(self):
        self.calls, self.exists, self.private = [], False, True

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        if method == 'GET':
            if self.exists:
                return {'full_name': REPO, 'private': True}
            raise ActionError('not found')
        return {'id': 99, 'full_name': REPO, 'private': self.private, 'html_url': f'https://github.com/{REPO}'}


def make_guard(tmp_path, net=None, sub=None, **config):
    if sub:
        tmp_path = tmp_path / sub
        tmp_path.mkdir()
    store = GithubConfigStore(tmp_path)
    store.save({'version': 1, 'enabled': True, 'account': ACCOUNT, 'repos': ['synthetic/repo'], 'public_only': False, 'poll_seconds': 900, **config})
    reader = GithubReader('never-real-gh', store)
    reader.auth_status = lambda: {'available': True, 'account': ACCOUNT}
    net = net or Net()
    transport = GithubActionTransport(reader)
    transport.request = net.request
    return GithubActionGuard(tmp_path, reader, enabled=True, transport=transport), net, store


def action(name=NAME, repo=None, description='A small site'):
    return {'kind': 'repository', 'repo': repo or f'{ACCOUNT}/{name}', 'content': {'name': name, 'description': description}}


def run(guard, value=None):
    drafted = guard.draft(value or action(), ACTOR)
    reviewed = guard.review(drafted['id'], ACTOR)
    guard.approve(drafted['id'], reviewed['fingerprint'], reviewed['nonce'], ACTOR)
    return drafted['id'], guard.execute(drafted['id'], reviewed['fingerprint'], ACTOR)


def test_the_request_is_private_with_an_initial_commit_and_nothing_can_change_that():
    p = plan(action())
    assert (p['method'], p['endpoint'], p['payload']) == ('POST', 'user/repos', {'name': NAME, 'description': 'A small site', 'private': True, 'auto_init': True})
    assert p['destination'] == f'https://github.com/{REPO}'
    for extra in ({'private': False}, {'visibility': 'public'}, {'auto_init': False}, {'homepage': 'x'}):
        with pytest.raises(ActionError):
            plan({**action(), 'content': {**action()['content'], **extra}})
    for bad in ('x.git', '.hidden', 'has space', 'a/b', 'x' * 101):
        with pytest.raises(ActionError):
            plan(action(name=bad, repo=f'{ACCOUNT}/{bad}'))
    with pytest.raises(ActionError):
        plan(action(repo=f'{ACCOUNT}/other-name'))                    # the repository part must be the name
    with pytest.raises(ActionError):
        plan(action(description='two\nlines'))


def test_creating_after_approval_adds_the_repository_to_the_allowlist_and_returns_its_link(tmp_path):
    guard, net, store = make_guard(tmp_path)
    action_id, done = run(guard)
    assert done['state'] == 'succeeded' and done['result'] == {'acknowledged': True, 'html_url': f'https://github.com/{REPO}'}
    assert [c[:2] for c in net.calls] == [('GET', f'repos/{REPO}'), ('POST', 'user/repos')]
    assert REPO in store.config().repos and 'synthetic/repo' in store.config().repos
    assert [e['event'] for e in guard.get(action_id)['audit']][-2:] == ['succeeded', 'allowlisted']


def test_nothing_is_created_without_approval_or_for_another_owner_or_a_public_only_host(tmp_path):
    guard, net, store = make_guard(tmp_path)
    drafted = guard.draft(action(), ACTOR)
    with pytest.raises(ActionError):
        guard.execute(drafted['id'], drafted['fingerprint'], ACTOR)       # draft only: no approval, no write
    assert net.calls == []
    with pytest.raises(ActionError):
        guard.draft(action(repo=f'someone-else/{NAME}'), ACTOR)           # only the configured account
    only_public, _, _ = make_guard(tmp_path, sub='p', public_only=True)
    with pytest.raises(ActionError):
        only_public.draft(action(), ACTOR)                                # a public-only host never creates private repositories


def test_an_existing_name_is_refused_and_a_non_private_answer_is_reported_as_uncertain(tmp_path):
    guard, net, store = make_guard(tmp_path)
    net.exists = True
    drafted = guard.draft(action(), ACTOR)
    reviewed = guard.review(drafted['id'], ACTOR)
    guard.approve(drafted['id'], reviewed['fingerprint'], reviewed['nonce'], ACTOR)
    with pytest.raises(ActionError, match='preflight'):
        guard.execute(drafted['id'], reviewed['fingerprint'], ACTOR)
    assert not any(c[0] == 'POST' for c in net.calls)
    guard2, net2, store2 = make_guard(tmp_path, sub='b')
    net2.private = False
    with pytest.raises(ActionError, match='uncertain'):
        run(guard2)
    assert REPO not in store2.config().repos                               # a repository GitHub did not confirm private is not trusted


def test_pending_lists_drafts_with_their_exact_preview_and_recent_finds_by_kind(tmp_path):
    guard, net, store = make_guard(tmp_path)
    drafted = guard.draft(action(), ACTOR)
    guard.draft({'kind': 'issue', 'repo': 'synthetic/repo', 'content': {'title': 't', 'body': 'b'}}, ACTOR)
    assert {a['preview']['kind'] for a in guard.pending()} == {'repository', 'issue'}
    assert [a['id'] for a in guard.recent('repository')] == [drafted['id']]


@pytest.fixture
def operator_client(make_client, monkeypatch):
    client = make_client()

    @client.app.middleware('http')
    async def operator(request, call_next):
        request.state.user = {'email': ACTOR, 'method': 'google'}
        return await call_next(request)
    with client:
        yield client


def wire(client, tmp_path):
    guard, net, store = make_guard(tmp_path, sub='wired')
    client.app.state.github_actions = guard
    client.app.state.github = guard.reader
    return guard, net, store


def test_the_operator_runs_a_draft_only_after_confirming_the_preview_they_read(operator_client, tmp_path):
    guard, net, store = wire(operator_client, tmp_path)
    drafted = guard.draft(action(), ACTOR)
    listed = operator_client.get('/api/github/actions').json()
    assert [a['id'] for a in listed['actions']] == [drafted['id']] and listed['writes_enabled'] is True
    body = {'fingerprint': drafted['fingerprint'], 'confirm': True}
    assert operator_client.post(f"/api/github/actions/{drafted['id']}/run", json={**body, 'confirm': False}).status_code == 422
    assert operator_client.post(f"/api/github/actions/{drafted['id']}/run", json={**body, 'fingerprint': 'a' * 64}).status_code == 409
    assert net.calls == []
    done = operator_client.post(f"/api/github/actions/{drafted['id']}/run", json=body)
    assert done.status_code == 200 and done.json()['state'] == 'succeeded' and done.json()['result']['html_url'].endswith(REPO)
    assert REPO in store.config().repos
    assert operator_client.post(f"/api/github/actions/{drafted['id']}/run", json=body).status_code == 409      # one approval, one execution


def test_hermes_can_only_propose_never_create(secured, tmp_path):  # noqa: F811
    b, _ = paired(secured, tmp_path)
    guard, net, store = make_guard(tmp_path, sub='g')
    secured.app.state.github_actions, secured.app.state.github = guard, guard.reader
    assert call(b, 'propose_repository', repo_name=NAME).status_code == 403                       # switch off by default
    pref(secured, allow_discord_repositories=True)
    off = make_guard(tmp_path, sub='h')[0]
    off.enabled = False
    secured.app.state.github_actions, secured.app.state.github = off, off.reader
    assert call(b, 'propose_repository', repo_name=NAME).status_code == 403                       # GitHub writes off
    secured.app.state.github_actions, secured.app.state.github = guard, guard.reader
    got = call(b, 'propose_repository', repo_name=NAME, repo_description='Site for the test').json()
    assert got['proposal']['repo'] == REPO and got['proposal']['state'] == 'draft' and 'cannot approve' in got['instructions']
    assert net.calls == []                                                                          # nothing reached GitHub
    pending = guard.pending()
    assert len(pending) == 1 and pending[0]['preview']['payload']['private'] is True
    assert call(b, 'propose_repository', repo_name='x.git').status_code == 422
    assert call(b, 'propose_repository').status_code == 422
    status = call(b, 'bootstrap_status').json()
    assert status['repositories'][0]['repo'] == REPO and status['repositories'][0]['state'] == 'draft'
    from sqlalchemy import select
    from models import Card
    with secured.app.state.sessions() as s:
        card = s.scalar(select(Card).where(Card.title.like('Approve new private repository%')))
        assert card.assignee_type == 'human' and 'Nothing has been created yet' in card.body and 'bootstrap' in (card.tags or '')


def test_the_plugin_knows_the_repository_actions():
    from tests.test_profiles import native
    mod = native()
    assert {'repo_name', 'repo_description'} <= mod.FIELDS


# ------------------------------------------------------------------------------------- branch access for agents
def test_a_branch_grant_is_validated_scoped_to_one_project_branch_and_never_main(tmp_path):
    import agent_git
    path = tmp_path / 'agent-git' / 'grants.json'
    grant = agent_git.add_clone(path, 5, REPO, NAME, 'setup')
    assert [(c.dir, c.repo, c.branch) for c in grant.clones] == [(NAME, REPO, 'project-5/setup')]
    assert oct(path.stat().st_mode & 0o777) == '0o600' and agent_git.load(path)[5].clones[0].branch == 'project-5/setup'
    for bad in ({'repo': 'no-slash'}, {'directory': '../x'}, {'directory': '.'}, {'slug': 'main/../x'}, {'slug': 'Upper'}, {'slug': 'x.lock'}):
        args = {'repo': REPO, 'directory': 'other', 'slug': 'ok', **bad}
        with pytest.raises(agent_git.GrantError):
            agent_git.add_clone(path, 5, args['repo'], args['directory'], args['slug'])
    with pytest.raises(agent_git.GrantError):
        agent_git.add_clone(path, 5, REPO, NAME, 'again')                  # one grant per folder
    second = agent_git.add_clone(path, 5, 'operator/other', 'other', 'docs')
    assert len(second.clones) == 2 and 6 not in agent_git.load(path)
    path.write_text('not json')
    with pytest.raises(agent_git.GrantError):
        agent_git.add_clone(path, 7, REPO, NAME, 'setup')                  # an unreadable file is never overwritten
    assert path.read_text() == 'not json'


def test_the_operator_grants_branch_access_only_for_an_allowlisted_repository_after_confirming(operator_client, tmp_path):
    from models import Project
    guard, net, store = wire(operator_client, tmp_path)
    operator_client.app.state.github.config_store = store
    import settings as S
    S.get_settings().agent_git_grants_file = tmp_path / 'grants.json'
    with operator_client.app.state.sessions.begin() as s:
        p = Project(document=json.dumps({'title': 'Site', 'working_dir': str(tmp_path)}), state='draft', created_by=ACTOR, created_at=0, updated_at=0)
        s.add(p)
        s.flush()
        pid = p.id
    url = f'/api/projects/{pid}/git-grant'
    body = {'repo': 'synthetic/repo', 'dir': 'site', 'slug': 'setup'}
    assert operator_client.get(url).json() == {'clones': []}
    assert operator_client.post(url, json=body).status_code == 422                                  # no confirm
    assert operator_client.post(url, json={**body, 'confirm': True, 'repo': 'not/listed'}).status_code == 422
    done = operator_client.post(url, json={**body, 'confirm': True})
    assert done.status_code == 201 and done.json()['clones'] == [{'dir': 'site', 'repo': 'synthetic/repo', 'branch': f'project-{pid}/setup'}]
    assert operator_client.get(url).json()['clones'][0]['branch'] == f'project-{pid}/setup'
    assert operator_client.post(url, json={**body, 'confirm': True}).status_code == 422             # the same folder twice


# ------------------------------------------------------------------------------------- what the planner is told
def test_the_planner_is_told_to_start_with_repository_approval_and_setup_when_a_repository_is_missing():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[3] / 'packs' / 'roles' / 'delegator' / 'plan.txt').read_text()
    assert 'approve creation of the private repository' in text and 'grant branch access' in text
    assert 'Never plan work that creates a repository, pushes to the main branch, or handles secrets' in text


def test_the_planner_is_told_what_a_sandboxed_coding_agent_cannot_run():
    from pathlib import Path
    pack = Path(__file__).resolve().parents[3] / 'packs' / 'roles' / 'delegator'
    text = (pack / 'plan.txt').read_text()
    assert 'cannot reach the local container engine' in text and 'never assign a story to codex' in text
    assert 'verification story' in text and 'a human or to a read-only agent' in text
    assert int((pack / 'VERSION').read_text().strip()) >= 7


def test_the_installation_summary_says_whether_github_writes_are_on_without_naming_repositories(make_client):
    import projects
    import settings as S
    client = make_client()
    with client:
        settings = S.get_settings()
        GithubConfigStore(settings.data_dir).save({'version': 1, 'enabled': True, 'account': 'acme-account', 'repos': ['acme-account/site', 'acme-account/private-thing'], 'public_only': False, 'poll_seconds': 900})
        with client.app.state.sessions() as s:
            text = projects.installation_text(s, settings)
    assert '2 repositories on this install' in text and 'always private' in text
    assert 'private-thing' not in text and 'acme-account' not in text                  # counts only: repository names are not sent to a model


def test_the_planner_requires_verification_and_a_viewable_preview_before_a_visual_approval():
    from pathlib import Path
    pack = Path(__file__).resolve().parents[3] / 'packs' / 'roles' / 'delegator'
    plan = (pack / 'plan.txt').read_text()
    assert "never let the producing story's own report stand as proof" in plan
    assert 'exists, is not empty' in plan and 'referenced by the page or stylesheet' in plan
    assert 'clickable URL' in plan and '127.0.0.1' in plan and 'stops it' in plan and 'tools/verify-preview.sh' in plan and 'trap' in plan
    assert 'PID-specific stop' in plan and 'on failure, and on cancellation' in plan and 'leave the preview running while approval waits' in plan
    assert 'automated preview-verification checkpoint' in (pack / 'review.txt').read_text()
    assert int((pack / 'VERSION').read_text().strip()) >= 9


def test_playwright_from_agent_tools_reaches_stories_and_the_installation_summary(make_client, monkeypatch, tmp_path):
    """Playwright is for visual polish: once Agent tools has it, agents and host actions can load it by name and the planner is told how."""
    import host_readiness
    import projects
    import settings as S
    from legacy_adapters import LegacyAgentAdapter
    monkeypatch.setenv('MAC_CONTROL_AGENT_TOOLS_ROOT', str(tmp_path))
    assert S.managed_playwright_env() == {}                                              # not installed: nothing changes
    (tmp_path / 'tools/playwright/current/node_modules/playwright').mkdir(parents=True)
    env = S.managed_playwright_env()
    assert env == {'NODE_PATH': str(tmp_path / 'tools/playwright/current/node_modules'),
                   'PLAYWRIGHT_BROWSERS_PATH': str(tmp_path / 'tools/playwright/current/browsers')}
    assert {k: LegacyAgentAdapter.env()[k] for k in env} == env
    real = host_readiness.check_tools
    monkeypatch.setattr(host_readiness, 'check_tools', lambda settings=None: {**real(settings), 'tools': [{'id': 'playwright', 'installed': True}]})
    client = make_client()
    with client:
        with client.app.state.sessions() as s:
            text = projects.installation_text(s, S.get_settings())
    assert 'playwright: available' in text and "createRequire(import.meta.url)('playwright')" in text
