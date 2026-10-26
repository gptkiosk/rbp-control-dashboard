"""Project packet generation: private storage, freshness, redaction and ownership. Never calls an LLM."""
import json
import subprocess

from models import Project
import project_packet
import projects
from tests.test_projects import app  # noqa: F401  (fixture)


def git(wd, *args):
    return subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', '-C', str(wd), *args],
                          check=True, capture_output=True, text=True).stdout


def repo(wd):
    wd.mkdir(parents=True, exist_ok=True)
    git(wd, 'init', '-q', '-b', 'main')
    (wd / 'app.py').write_text("import os\nTOKEN = os.environ['SERVICE_TOKEN']\n")
    (wd / '.env').write_text('SERVICE_TOKEN=packet-secret-value-123\n')
    (wd / '.gitignore').write_text('.env\n')
    git(wd, 'add', 'app.py', '.gitignore')
    git(wd, 'commit', '-q', '-m', 'start')
    return wd


def create(c, wd, **kw):
    r = c.post('/api/projects', json={'title': 'Packet site', 'brief': 'Build the site. api_key: sk-or-abcdefgh12345678',
        'working_dir': str(wd), 'project_type': 'local-website', 'nodes': [], **kw})
    assert r.status_code == 201, r.text
    return r.json()['id']


def packet(c, pid, **params):
    r = c.get(f'/api/projects/{pid}/packet', params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_packet_is_written_privately_with_every_document_and_leaves_the_workspace_untouched(app):
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd)
    before = git(wd, 'status', '--porcelain=v1', '--untracked-files=all')
    data = packet(c, pid)
    m = data['manifest']
    assert m['schema'] == 'bamcio.project-packet/1' and m['generator']['product'] == settings.product_short_name
    assert m['source']['project_id'] == pid and m['workspace']['head'] == git(wd, 'rev-parse', 'HEAD').strip()
    out = project_packet.folder(settings, pid)
    assert [d['path'] for d in m['documents']] == [name for name, _ in project_packet.DOCUMENTS]
    for d in m['documents']:
        assert (out / d['path']).is_file() and (out / d['path']).stat().st_mode & 0o077 == 0
    assert len(data['start_here'].encode()) <= project_packet.START_LIMIT and 'AGENTS.md' in data['start_here']
    assert m['freshness']['state'] == 'current' and 'Baseline set' in m['freshness']['reasons'][0]
    # The packet never writes into the workspace, so it cannot dirty the checkout.
    assert git(wd, 'status', '--porcelain=v1', '--untracked-files=all') == before
    assert not (wd / 'docs').exists()


def test_values_and_tokens_never_reach_the_packet_but_variable_names_do(app):
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd)
    packet(c, pid)
    out = project_packet.folder(settings, pid)
    text = '\n'.join(p.read_text() for p in out.rglob('*') if p.is_file())
    assert 'packet-secret-value-123' not in text and 'sk-or-abcdefgh12345678' not in text
    assert 'SERVICE_TOKEN' in (out / '03-environment.md').read_text()


def test_unreported_changes_make_the_packet_stale_until_work_is_recorded(app):
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd)
    assert packet(c, pid)['manifest']['freshness']['state'] == 'current'
    (wd / 'app.py').write_text("print('changed')\n")
    git(wd, 'commit', '-qam', 'native edit')
    fresh = packet(c, pid)['manifest']['freshness']
    assert fresh['state'] == 'stale' and 'unreported' in fresh['reasons'][0] and 'authorship is unknown' in fresh['reasons'][0]
    # An operator note is not a report of work and does not hide the change.
    with sessions() as s:
        projects.memory(s, s.get(Project, pid), 'decision', 'Prefer blue.', 'op'); s.commit()
    assert packet(c, pid)['manifest']['freshness']['state'] == 'stale'
    with sessions() as s:
        projects.memory(s, s.get(Project, pid), 'checkpoint', 'Native edit reviewed: app.py prints.', 'op'); s.commit()
    assert packet(c, pid)['manifest']['freshness']['state'] == 'current'


def test_a_rolled_back_report_does_not_move_the_baseline(app):
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd)
    packet(c, pid)
    git(wd, 'commit', '-q', '--allow-empty', '-m', 'native')
    with sessions() as s:
        projects.memory(s, s.get(Project, pid), 'checkpoint', 'never committed', 'op'); s.rollback()
    assert packet(c, pid)['manifest']['freshness']['state'] == 'stale'


def test_living_docs_are_indexed_by_hash_never_rewritten_and_regeneration_is_stamp_gated(app):
    c, sessions, wd, settings = app
    repo(wd)
    (wd / 'docs/project').mkdir(parents=True)
    (wd / 'docs/project/architecture.md').write_text('# Mine\nHand-written.\n')
    git(wd, 'add', 'docs'); git(wd, 'commit', '-qm', 'docs')
    pid = create(c, wd)
    packet(c, pid)  # the first read sets the freshness baseline and says so
    m = packet(c, pid)['manifest']
    assert [f['path'] for f in m['living_docs']['files']] == ['docs/project/architecture.md']
    stamp_file = project_packet.folder(settings, pid) / 'PACKET.json'
    first = stamp_file.stat().st_mtime_ns
    again = packet(c, pid)['manifest']
    assert again['stamp'] == m['stamp'] and stamp_file.stat().st_mtime_ns == first
    assert (wd / 'docs/project/architecture.md').read_text() == '# Mine\nHand-written.\n'
    assert 'docs/project/architecture.md' in (project_packet.folder(settings, pid) / '02-architecture.md').read_text()


def test_a_folder_without_git_reports_unknown_instead_of_guessing(app):
    c, sessions, wd, settings = app
    wd.mkdir(parents=True, exist_ok=True)
    pid = create(c, wd)
    m = packet(c, pid)['manifest']
    assert m['freshness']['state'] == 'unknown'
    assert 'unknown' in (project_packet.folder(settings, pid) / '02-architecture.md').read_text()


def test_story_states_keep_accepted_and_reported_apart(app):
    from tests.test_projects import node
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd, nodes=[node('a'), node('b', depends_on=['a'])])
    state = (project_packet.folder(settings, pid) / '04-state.md')
    packet(c, pid)
    text = state.read_text()
    assert 'Planned (not submitted) (2)' in text and 'accepted' not in text.lower().split('## next actions')[0]
    # A planned story waits for its unaccepted prerequisite; only `a` is ready next.
    assert 'b: b · codex / gpt-6.1-sol · waits for a' in text
    assert text.split('## Next actions')[1].strip() == '- a: a'
    assert '  - Done when:' in text  # Markdown nesting survives redaction


def test_another_profile_cannot_read_the_packet_and_delete_removes_it(app):
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd)
    packet(c, pid)
    with sessions() as s:
        s.get(Project, pid).created_by = 'someone-else'; s.commit()
    assert c.get(f'/api/projects/{pid}/packet').status_code == 403
    projects.forget_project_files(settings, pid)
    assert not project_packet.folder(settings, pid).exists()


def test_manifest_json_is_valid_and_lists_hashes_of_what_was_written(app):
    import hashlib
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd)
    packet(c, pid)
    out = project_packet.folder(settings, pid)
    m = json.loads((out / 'PACKET.json').read_text())
    for d in m['documents']:
        assert hashlib.sha256((out / d['path']).read_bytes()).hexdigest() == d['sha256']


def test_reported_work_stays_reported_until_the_operator_accepts_it(app):
    from dispatcher import Dispatcher
    from tests.test_projects import active, finish, node
    c, sessions, wd, settings = app
    repo(wd)
    p = active(app, [node('a'), node('b', depends_on=['a'])])
    a, b = [t['card_id'] for t in p['tasks'] if t['role'] == 'story']
    Dispatcher(sessions, settings)._claim(2)
    rid = finish(app, a, 'Changed app.py; checks passed.')
    state = project_packet.folder(settings, p['id']) / '04-state.md'
    packet(c, p['id'])
    text = state.read_text()
    assert 'Reported, awaiting operator review (1)' in text and f'- a: a · codex / gpt-6.1-sol · task #{a}' in text
    assert '## Accepted' not in text and f'blocked by #{a}' in text
    git(wd, 'commit', '-q', '--allow-empty', '-m', 'story a')  # the story's own change, reported by its handoff
    fresh = packet(c, p['id'])['manifest']['freshness']
    assert fresh['state'] == 'in_progress' and f'Task #{a} reported a result that awaits operator review' in fresh['reasons'][0]
    assert c.post(f"/api/projects/{p['id']}/stories/{a}/accept", json={'run_id': rid, 'summary': 'Accepted A after review.'}).status_code == 200
    m = packet(c, p['id'])['manifest']
    text = state.read_text()
    assert '## Accepted (1)' in text and f'blocked by #{a}' not in text
    assert m['freshness']['state'] == 'current'  # the accepted handoff recorded the workspace change
    decisions = (project_packet.folder(settings, p['id']) / '05-decisions.md').read_text()
    assert 'accepted handoff' in decisions and 'Accepted A after review.' in decisions


def test_workspace_read_works_for_a_submitted_project(app):
    # MCD 0.6.73 raised AttributeError here: the shared workspace view called a helper MCD lacked.
    from tests.test_projects import active, node
    c, sessions, wd, settings = app
    p = active(app, [node('a'), node('b', depends_on=['a'])])
    r = c.get(f"/api/projects/coordinator?operation=workspace&project_id={p['id']}")
    assert r.status_code == 200, r.text
    a = [t['card_id'] for t in p['tasks'] if t['role'] == 'story'][0]
    assert [t['id'] for t in r.json()['next_tasks']] == [a]
