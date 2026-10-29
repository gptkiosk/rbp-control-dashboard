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


def test_a_scratch_folder_without_git_is_tracked_by_file_snapshot(app):
    c, sessions, wd, settings = app
    wd.mkdir(parents=True, exist_ok=True)
    (wd / 'index.html').write_text('<h1>draft</h1>')
    pid = create(c, wd)
    first = packet(c, pid)['manifest']
    assert first['freshness']['state'] == 'current' and 'Baseline set' in first['freshness']['reasons'][0]
    assert 'no Git; 1 files tracked' in (project_packet.folder(settings, pid) / 'START-HERE.md').read_text()
    assert 'unavailable' in (project_packet.folder(settings, pid) / '02-architecture.md').read_text()
    (wd / 'site.css').write_text('body{}')
    fresh = packet(c, pid)['manifest']['freshness']
    assert fresh['state'] == 'stale' and 'no Git' in fresh['reasons'][0] and '1 → 2 files' in fresh['reasons'][0]
    with sessions() as s:
        projects.memory(s, s.get(Project, pid), 'checkpoint', 'Styles added and reviewed.', 'op'); s.commit()
    assert packet(c, pid)['manifest']['freshness']['state'] == 'current'
    assert not any(p.name.startswith('.') or p.suffix == '.tmp' for p in wd.rglob('*'))  # nothing written into the folder


def test_a_missing_folder_or_one_too_large_to_list_reports_unknown(app, monkeypatch):
    import shutil
    c, sessions, wd, settings = app
    wd.mkdir(parents=True, exist_ok=True)
    (wd / 'a.txt').write_text('a'); (wd / 'b.txt').write_text('b')
    pid = create(c, wd)
    monkeypatch.setattr(project_packet, 'SNAPSHOT_FILES', 1)
    fresh = packet(c, pid)['manifest']['freshness']
    assert fresh['state'] == 'unknown' and 'More than 1 files' in fresh['reasons'][0]
    monkeypatch.setattr(project_packet, 'SNAPSHOT_FILES', 5000)
    shutil.rmtree(wd)
    fresh = packet(c, pid)['manifest']['freshness']
    assert fresh['state'] == 'unknown' and 'missing' in fresh['reasons'][0]


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


PNG = b'\x89PNG\r\n\x1a\n' + b'\0' * 32


def export_zip(c, pid, **params):
    import io, zipfile
    r = c.get(f'/api/projects/{pid}/packet.zip', params=params)
    assert r.status_code == 200, r.text
    return r, zipfile.ZipFile(io.BytesIO(r.content))


def visual_project(c, wd):
    repo(wd)
    (wd / 'media/references').mkdir(parents=True)
    (wd / 'media/references/style.png').write_bytes(PNG)
    (wd / 'media/slots.json').write_text(json.dumps({'slots': [{'name': 'hero', 'kind': 'image', 'prompt': 'A hero image'},
                                                              {'name': 'later', 'kind': 'image', 'prompt': 'Not made yet'}]}))
    (wd / 'assets/img').mkdir(parents=True)
    (wd / 'assets/img/hero.jpg').write_bytes(b'\xff\xd8\xff' + b'\0' * 64)
    (wd / 'docs/project').mkdir(parents=True)
    (wd / 'docs/project/decisions.md').write_text('# Decisions\nUse plain CSS.\n')
    (wd / 'docs/project/leak.md').symlink_to(wd / '.env')
    return create(c, wd)


def test_export_carries_documents_living_docs_and_reference_art_but_no_source_or_secrets(app):
    import hashlib
    c, sessions, wd, settings = app
    pid = visual_project(c, wd)
    before = git(wd, 'status', '--porcelain=v1', '--untracked-files=all')
    r, z = export_zip(c, pid)
    assert r.headers['content-disposition'] == f'attachment; filename="{r.headers["content-disposition"].split(chr(34))[1]}"'
    assert r.headers['content-disposition'].split('"')[1].startswith(f'{settings.product_short_name.lower()}-project-{pid}-packet-')
    names = set(z.namelist())
    m = json.loads(z.read('project-packet/PACKET.json'))
    for member in m['export']['members']:
        assert hashlib.sha256(z.read('project-packet/' + member['path'])).hexdigest() == member['sha256']
    assert {'project-packet/START-HERE.md', 'project-packet/history/ledger.md', 'project-packet/living/docs/project/decisions.md',
            'project-packet/media/references/style.png'} <= names
    assert not any(n.endswith(('app.py', '.env', 'hero.jpg')) for n in names)
    every = b''.join(z.read(n) for n in names)
    assert b'packet-secret-value-123' not in every
    by = {(a['kind'], a.get('path') or a.get('slot')): a for a in m['assets']}
    assert by[('reference', 'media/references/style.png')]['included'] is True
    assert by[('living_doc', 'docs/project/leak.md')]['included'] is False  # a link is listed, never followed
    assert 'opt-in' in by[('published', 'assets/img/hero.jpg')]['missing_reason'] and by[('slot', 'later')]['missing_reason'] == 'Not published yet.'
    assert 'Not included' in m['export']['source_code']
    assert git(wd, 'status', '--porcelain=v1', '--untracked-files=all') == before


def test_published_media_is_included_only_when_asked(app):
    c, sessions, wd, settings = app
    pid = visual_project(c, wd)
    r, z = export_zip(c, pid, include_media='true')
    m = json.loads(z.read('project-packet/PACKET.json'))
    hero = next(a for a in m['assets'] if a.get('slot') == 'hero')
    assert hero['included'] and 'project-packet/assets/img/hero.jpg' in z.namelist()


def test_an_asset_over_the_packet_limit_is_listed_with_where_to_copy_it(app, monkeypatch):
    c, sessions, wd, settings = app
    pid = visual_project(c, wd)
    monkeypatch.setattr(project_packet, 'EXPORT_LIMIT', 1)
    r, z = export_zip(c, pid)
    m = json.loads(z.read('project-packet/PACKET.json'))
    ref = next(a for a in m['assets'] if a['kind'] == 'reference')
    assert ref['included'] is False and 'copy it from' in ref['missing_reason']


def test_export_and_context_download_respect_ownership_and_name_the_product(app):
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd)
    r = c.get(f'/api/projects/{pid}/context')
    assert r.headers['content-disposition'] == f'attachment; filename="{settings.product_short_name.lower()}-project-{pid}-context.md"'
    with sessions() as s:
        s.get(Project, pid).created_by = 'someone-else'; s.commit()
    assert c.get(f'/api/projects/{pid}/packet.zip').status_code == 403


# ------------------------------------------------------------- import

def rezip(z, change=None, extra=None):
    """A copy of a packet archive with members replaced, removed (None) or added."""
    import io, zipfile
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as w:
        for info in z.infolist():
            name = info.filename
            data = z.read(name)
            if change and name in change:
                if change[name] is None:
                    continue
                data = change[name]
            w.writestr(zipfile.ZipInfo(name, date_time=info.date_time), data)
        for info, data in (extra or []):
            w.writestr(info, data)
    return out.getvalue()


def upload(c, raw):
    return c.post('/api/projects/packet-import', content=raw, headers={'Content-Type': 'application/zip'})


def test_round_trip_creates_one_draft_with_intent_history_and_references_but_no_authority(app):
    from tests.test_projects import active, finish, node
    from dispatcher import Dispatcher
    c, sessions, wd, settings = app
    visual_project(c, wd)
    p = active(app, [node('a'), node('b', depends_on=['a'])], title='Packet site', brief='Build the site.')
    a = [t['card_id'] for t in p['tasks'] if t['role'] == 'story'][0]
    Dispatcher(sessions, settings)._claim(2)
    rid = finish(app, a, 'Done A.')
    assert c.post(f"/api/projects/{p['id']}/stories/{a}/accept", json={'run_id': rid, 'summary': 'Accepted A.'}).status_code == 200
    r, z = export_zip(c, p['id'])
    review = upload(c, r.content)
    assert review.status_code == 201, review.text
    body = review.json()
    assert body['intent']['title'] == 'Packet site' and body['references'] == ['media/references/style.png']
    assert [s['status'] for s in body['stories']][0] == 'accepted' and 'not instructions' in body['rule']
    dest = wd.parent / 'continued'
    dest.mkdir()
    made = c.post(f"/api/projects/packet-import/{body['import_id']}/create", json={'working_dir': str(dest), 'copy_references': True})
    assert made.status_code == 201, made.text
    q = made.json()
    assert q['state'] == 'draft' and q['tasks'] == [] and q['document']['nodes'] == [] and q['revision'] == 1
    assert 'Continuation from project packet' in q['document']['brief'] and 'Accepted in the source project:\n- a: a' in q['document']['brief']
    assert q['handoff_approval']['mode'] != 'automatic' and not q['model_lock']
    assert (dest / 'media/references/style.png').read_bytes() == PNG
    imported = project_packet.folder(settings, q['id']) / 'imported'
    assert (imported / 'START-HERE.md').is_file() and str(imported) in q['document']['brief']
    note = [m for m in q['memory'] if m['kind'] == 'decision' and 'Imported project packet' in m['text']][0]['text']
    assert 'not the source commit' in note and 'no tasks, approvals, routes, grants or spending decisions' in note
    # The staged upload is used once.
    assert c.post(f"/api/projects/packet-import/{body['import_id']}/create", json={'working_dir': str(dest)}).status_code == 404


def test_altered_unsafe_or_newer_packets_are_refused_with_a_reason(app):
    import zipfile
    c, sessions, wd, settings = app
    pid = visual_project(c, wd)
    r, z = export_zip(c, pid)
    m = json.loads(z.read('project-packet/PACKET.json'))
    cases = {
        'does not match its recorded hash': rezip(z, {'project-packet/01-brief.md': b'# changed'}),
        'file list does not match': rezip(z, {'project-packet/04-state.md': None}),
        'Unsafe path': rezip(z, extra=[(zipfile.ZipInfo('project-packet/../evil.md'), b'x')]),
        'newer version': rezip(z, {'project-packet/PACKET.json': json.dumps({**m, 'schema': 'bamcio.project-packet/2'}).encode()}),
        'not a project packet': b'not a zip at all',
    }
    stored = rezip(z, {'project-packet/01-brief.md': None}, extra=[(zipfile.ZipInfo('project-packet/01-brief.md'), b'# Unique brief marker')])
    cases['Damaged file'] = stored.replace(b'# Unique brief marker', b'# Unique brief markeR')  # same size, CRC no longer matches
    link = zipfile.ZipInfo('project-packet/living/docs/project/link.md'); link.external_attr = (0o120777 << 16)
    cases['Links and special files'] = rezip(z, extra=[(link, b'/etc/passwd')])
    secret = b'token: ghp_' + b'a' * 36
    import hashlib
    members = m['export']['members'] + [{'path': 'living/docs/project/keys.md', 'bytes': len(secret), 'sha256': hashlib.sha256(secret).hexdigest()}]
    cases['appears to contain a credential'] = rezip(z, {'project-packet/PACKET.json': json.dumps({**m, 'export': {**m['export'], 'members': members}}).encode()},
                                                     extra=[(zipfile.ZipInfo('project-packet/living/docs/project/keys.md'), secret)])
    for reason, raw in cases.items():
        res = upload(c, raw)
        assert res.status_code == 422 and reason in res.json()['detail'], (reason, res.text)
    assert not project_packet_import_root(settings).exists()  # nothing refused is staged


def project_packet_import_root(settings):
    import project_packet_import
    return project_packet_import.stage_root(settings)


def test_a_staged_import_belongs_to_its_uploader_and_needs_an_approved_destination(app):
    c, sessions, wd, settings = app
    pid = visual_project(c, wd)
    r, z = export_zip(c, pid)
    body = upload(c, r.content).json()
    owner = project_packet_import_root(settings) / body['import_id'] / 'owner.json'
    owner.write_text(json.dumps({'owner': 'someone-else', 'created_at': 0}))
    assert c.post(f"/api/projects/packet-import/{body['import_id']}/create", json={'working_dir': str(wd)}).status_code == 403
    body = upload(c, r.content).json()
    outside = c.post(f"/api/projects/packet-import/{body['import_id']}/create", json={'working_dir': '/etc'})
    assert outside.status_code == 422
    assert c.post('/api/projects/packet-import/not-an-id/create', json={'working_dir': str(wd)}).status_code == 404


def test_coordinator_packet_read_returns_the_summary_and_web_only_links(app):
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd)
    r = c.get(f'/api/projects/coordinator?operation=packet&project_id={pid}')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['download'] == f'/api/projects/{pid}/packet.zip' and 'web-only' in body['instructions'] and body['start_here'].startswith('# Start here')
    caps = c.get('/api/projects/coordinator?operation=capabilities').json()
    assert 'packet' in caps['reads']
    assert any(f['feature'] == 'project_packet_export_import' and f['discord_actions'] == [] for f in caps['workflow'])


def test_story_context_and_copy_handoff_point_to_the_packet(app):
    from tests.test_projects import active, node
    c, sessions, wd, settings = app
    repo(wd)
    p = active(app, [node('a')])
    with sessions() as s:
        payload = json.loads(projects.context(s, s.get(Project, p['id']), 'a').rsplit('\n', 1)[1])  # both products end with the JSON payload
    pointer = payload['project_packet']
    assert pointer['start_here'].endswith(f"project-{p['id']}/START-HERE.md") and pointer['living_docs'] == 'docs/project/'
    assert len(json.dumps(pointer)) < 450
    keys = list(payload)
    assert keys.index('project_packet') < keys.index('stories') < keys.index('current_story')
    handoff = c.get(f"/api/projects/coordinator?operation=workspace&project_id={p['id']}").json()['packet']
    assert 'Project packet (this host):' in handoff and 'START-HERE.md' in handoff


def test_concurrent_readers_rebuild_the_packet_without_colliding(app):
    from concurrent.futures import ThreadPoolExecutor
    c, sessions, wd, settings = app
    repo(wd)
    pid = create(c, wd)

    def build(_):
        with sessions() as s:
            return project_packet.ensure(s, s.get(Project, pid), settings)['stamp']
    with ThreadPoolExecutor(8) as pool:
        stamps = list(pool.map(build, range(16)))
    assert len(set(stamps)) <= 2  # the first build sets the baseline; later ones agree
    assert not list(project_packet.folder(settings, pid).rglob('*.tmp'))


def test_story_context_carries_setup_facts_and_the_read_story_deliverable(app):
    """Pilot 2026-10-28: a read-only readiness story could not see the dashboard's setup facts and tried to write a file."""
    from tests.test_projects import active, node
    c, sessions, wd, settings = app
    repo(wd)
    p = active(app, [node('a', mode='read'), node('b', depends_on=['a'], mode='edit')])
    with sessions() as s:
        project = s.get(Project, p['id'])
        read = json.loads(projects.context(s, project, 'a').rsplit('\n', 1)[1])
        edit = json.loads(projects.context(s, project, 'b').rsplit('\n', 1)[1])
    assert read['current_story']['mode'] == 'read' and 'final report is the deliverable' in read['current_story']['deliverable']
    assert 'mode' not in edit['current_story'] and 'deliverable' not in edit['current_story']
    assert any(check.startswith('workspace=') for check in read['host_setup']['checks'])
    assert 'quota' in read['host_setup']['not_story_checks'] and 'Do not list either as a blocker' in read['host_setup']['not_story_checks']
    keys = list(read)
    assert keys.index('host_setup') < keys.index('current_story')
    assert 'media_slots_format' not in read['host_setup']          # only projects that generate media


def test_a_media_project_story_is_told_the_slots_format(app, monkeypatch):
    """Pilot 2026-10-29: the media inventory story invented id/type keys and the studio rejected the whole file."""
    from tests.test_projects import active, node
    import media_generate, project_contract
    c, sessions, wd, settings = app
    repo(wd)
    p = active(app, [node('a', mode='edit')])
    monkeypatch.setattr(project_contract, 'generated_media', lambda document: True)
    with sessions() as s:
        story = json.loads(projects.context(s, s.get(Project, p['id']), 'a').rsplit('\n', 1)[1])
    assert story['host_setup']['media_slots_format'] == media_generate.SLOTS_FORMAT
    assert '## Format' in project_packet._media_doc([], [], None) and media_generate.SLOTS_FORMAT in project_packet._media_doc([], [], None)
