"""Repository setup by the dashboard at submission: private repo, starter files, clone, setup branch, GitHub list and branch grant."""
import subprocess
from types import SimpleNamespace

import pytest

import agent_git
import repo_setup
from github_config import GithubConfigStore


@pytest.fixture
def host(tmp_path):
    gh = tmp_path / 'bin' / 'gh'
    gh.parent.mkdir()
    gh.write_text('#!/bin/sh\nexit 0\n'); gh.chmod(0o755)
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)       # an empty repository, as GitHub creates it
    project = tmp_path / 'ws' / 'scratch-arcade'
    project.mkdir(parents=True)
    settings = SimpleNamespace(gh_path=str(gh), agent_tools_path=None, agent_git_grants_file=tmp_path / 'grants.json')
    calls, created = [], []

    def runner(argv, cwd=None, timeout=120):
        if argv[0] == str(gh):
            calls.append(argv[1:])
            if argv[1:3] == ['api', 'user']:
                return 0, 'gptkiosk 1234'
            if argv[1:3] == ['repo', 'view']:
                return (0, '{}') if created else (1, 'not found')
            if argv[1:3] == ['repo', 'create']:
                created.append(argv[3]); return 0, 'created'
            return 1, 'unexpected'
        return repo_setup.run(argv, cwd, timeout)

    store = GithubConfigStore(tmp_path / 'data')
    return SimpleNamespace(settings=settings, runner=runner, remote=remote, project=project, calls=calls, created=created, store=store)


def go(h, **kw):
    return repo_setup.setup(h.settings, 2, str(h.project), 'twodoors-website', 'Through the Little Door', github_store=h.store,
                            runner=h.runner, remote_url=lambda full: str(h.remote), **kw)


def test_first_run_does_every_step_and_a_second_run_does_nothing_new(host):
    made = go(host)
    assert made == {'repo': 'gptkiosk/twodoors-website', 'folder': 'twodoors-website', 'branch': 'project-2/setup', 'done': made['done']}
    assert host.created == ['gptkiosk/twodoors-website'] and ['repo', 'create', 'gptkiosk/twodoors-website', '--private', '--description', 'Through the Little Door'] in host.calls
    clone = host.project / 'twodoors-website'
    assert (clone / 'README.md').read_text().startswith('# Through the Little Door') and (clone / '.gitignore').exists()
    branches = subprocess.run(['git', '-C', str(host.remote), 'branch', '--list'], capture_output=True, text=True).stdout
    assert 'main' in branches and 'project-2/setup' in branches
    assert subprocess.run(['git', '-C', str(clone), 'branch', '--show-current'], capture_output=True, text=True).stdout.strip() == 'project-2/setup'
    author = subprocess.run(['git', '-C', str(clone), 'log', '-1', '--format=%an <%ae>'], capture_output=True, text=True).stdout.strip()
    assert author == 'gptkiosk <1234+gptkiosk@users.noreply.github.com>'
    assert host.store.status()['repos'] == ['gptkiosk/twodoors-website']
    grant = agent_git.load(host.settings.agent_git_grants_file)[2]
    assert [(c.dir, c.repo, c.branch) for c in grant.clones] == [('twodoors-website', 'gptkiosk/twodoors-website', 'project-2/setup')]
    again = go(host)
    assert host.created == ['gptkiosk/twodoors-website'] and again['done'] == ['Agents work on project-2/setup.']


def test_a_folder_that_is_not_this_repository_is_refused(host):
    (host.project / 'twodoors-website').mkdir()
    subprocess.run(['git', 'init', '-q', str(host.project / 'twodoors-website')], check=True)
    subprocess.run(['git', '-C', str(host.project / 'twodoors-website'), 'remote', 'add', 'origin', 'https://github.com/someone/else.git'], check=True)
    with pytest.raises(repo_setup.RepoSetupError, match='not a clone'):
        go(host)


def test_it_explains_a_missing_or_signed_out_gh(host, monkeypatch):
    with pytest.raises(repo_setup.RepoSetupError, match='Use a repository name'):
        repo_setup.setup(host.settings, 2, str(host.project), 'Bad Name', 't', runner=host.runner)
    with pytest.raises(repo_setup.RepoSetupError, match='not signed in'):
        repo_setup.setup(host.settings, 2, str(host.project), 'ok', 't', runner=lambda argv, **k: (1, 'auth required'))
    monkeypatch.setattr(repo_setup, 'gh_path', lambda settings: None)
    with pytest.raises(repo_setup.RepoSetupError, match='gh is not installed'):
        repo_setup.setup(host.settings, 2, str(host.project), 'ok', 't', runner=host.runner)


def test_submission_runs_setup_after_the_checks_and_records_it(make_client, monkeypatch, tmp_path):
    from agents import AgentSpec
    from settings import get_settings
    import projects
    from project_schemas import Action
    monkeypatch.setattr(AgentSpec, 'available', lambda self, settings: True)
    client = make_client()
    settings = get_settings(); settings.agent_git_grants_file = tmp_path / 'grants.json'
    workspace = tmp_path / 'ws' / 'proj'
    seen = []

    def fake(settings, pid, working_dir, name, title, github_store=None):
        seen.append((pid, name))
        if name == 'broken':
            raise repo_setup.RepoSetupError('gh is not signed in on this host.')
        return {'repo': f'gptkiosk/{name}', 'folder': name, 'branch': f'project-{pid}/setup', 'done': ['Created private repository.']}

    monkeypatch.setattr(repo_setup, 'setup', fake)
    node = dict(key='a', title='A', description='Do it.', scope='Here.', acceptance='Works.', assignee='claude', model='claude-haiku-5-5', mode='read',
                work_kind='research', size='xs', risk='low', estimate_minutes=10, route_reason='Cheap.')
    with client:
        client.patch('/api/billing', json={'accounts': {'claude': {'mode': 'subscription', 'monthly_usd': 20}}})
        with client.app.state.sessions() as s:
            bad = projects.create(s, dict(title='X', brief='B', working_dir=str(workspace), repository={'name': 'broken'}, nodes=[node]), settings, 'operator')
            with pytest.raises(Exception, match='not signed in'):
                projects.submit(s, bad, Action(revision=1, approve_coordination=True, approve_api_work=True), settings, 'operator')
            assert projects.document(bad)['repository'] == {'name': 'broken', 'repo': '', 'folder': '', 'branch': ''}   # unchanged; retry later
            p = projects.create(s, dict(title='Arcade', brief='B', working_dir=str(workspace), repository={'name': 'twodoors-website'}, nodes=[node]), settings, 'operator')
            projects.submit(s, p, Action(revision=1, approve_coordination=True, approve_api_work=True), settings, 'operator')
            s.commit()
            repo = projects.document(p)['repository']
            assert repo == {'name': 'twodoors-website', 'repo': 'gptkiosk/twodoors-website', 'folder': 'twodoors-website', 'branch': f'project-{p.id}/setup'}
            assert p.state in ('active', 'dispatching')
            built = projects.context_payload(s, p, 'a') if hasattr(projects, 'context_payload') else projects.context(s, p, 'a')
            text = built if isinstance(built, str) else __import__('json').dumps(built)
            assert 'gptkiosk/twodoors-website' in text and f'project-{p.id}/setup' in text
