"""Parallel scheduling facts: concurrency, the longest chain, touches overlap, and that none of it applies to a serial project."""
import pytest

import project_schedule as ps
import projects


def n(key, deps=(), est=60, mode='edit', touches=(), assignee='codex', kind='story', **extra):
    return {'key': key, 'kind': kind, 'depends_on': list(deps), 'estimate_minutes': est, 'mode': mode, 'touches': list(touches), 'assignee': assignee, **extra}


DIAMOND = [n('a', est=30, touches=['site/a']), n('b', est=90, touches=['site/b']), n('c', est=60, touches=['site/c']), n('d', ('a', 'b', 'c'), est=45, touches=['site/'], integration=True)]


def test_stats_find_the_longest_chain_the_best_case_speedup_and_the_width():
    s = ps.stats(DIAMOND)
    assert s == {'stories': 4, 'total_minutes': 225, 'critical_minutes': 135, 'speedup': 1.67, 'width': 3, 'critical_path': ['b', 'd']}
    chain = [n('x', est=10), n('y', ('x',), est=20), n('z', ('y',), est=30)]
    c = ps.stats(chain)
    assert c['speedup'] == 1.0 and c['width'] == 1 and c['critical_path'] == ['x', 'y', 'z'] and c['critical_minutes'] == 60
    assert ps.stats([])['stories'] == 0 and ps.stats([n('p', kind='phase')])['stories'] == 0       # phases are not work


def test_size_hints_and_the_default_stand_in_for_a_missing_estimate():
    assert ps.estimate({'size': 'm'}) == 120 and ps.estimate({}) == 45 and ps.estimate({'estimate_minutes': 7, 'size': 'm'}) == 7


def test_the_longest_remaining_chain_starts_first_and_the_order_stays_valid():
    order = ps.critical_order(DIAMOND)
    assert order == ['b', 'c', 'a', 'd']                                  # b (90) before c (60) before a (30); the join last
    assert order.index('d') == 3
    tie = [n('p'), n('q'), n('r', ('p', 'q'))]
    assert ps.critical_order(tie) == ['p', 'q', 'r']                      # equal chains keep the plan's own order
    with pytest.raises(ValueError):
        ps.critical_order([n('a', ('b',)), n('b', ('a',))])


def test_only_stories_no_chain_orders_can_overlap():
    assert ps.can_overlap(DIAMOND) == [('a', 'b'), ('a', 'c'), ('b', 'c')]
    assert ps.can_overlap([n('x'), n('y', ('x',)), n('z', ('y',))]) == []


@pytest.mark.parametrize('a,b,expected', [
    ('site/a', 'site/b', False), ('site/', 'site/a/page.html', True), ('site', 'site/a', True), ('docs/**', 'src/app.py', False),
    ('**', 'anything/at/all', True), ('src/*.py', 'src/util/x.py', True), ('src/a.py', 'src/a.py', True), ('./src/a', 'src/b', False),
])
def test_two_patterns_overlap_when_one_is_rooted_at_or_inside_the_other(a, b, expected):
    assert ps.touches_overlap(a, b) is expected and ps.touches_overlap(b, a) is expected


def test_a_changed_file_must_fall_under_a_declared_pattern():
    assert ps.inside_touches(['site/a/index.html', 'site/a/css/x.css'], ['site/a']) is True
    assert ps.inside_touches(['site/b/index.html'], ['site/a']) is False
    assert ps.inside_touches(['docs/x.md', 'README.md'], ['docs/**', 'README.md']) is True
    assert ps.inside_touches(['src/a.py'], ['src/*.py']) is True and ps.inside_touches(['src/sub/a.py'], ['src/*.py']) is False      # * stays in one folder
    assert ps.inside_touches(['src/sub/a.py'], ['src/**']) is True and ps.inside_touches(['src/sub/a.py'], ['src/**/a.py']) is True and ps.inside_touches(['src/a.py'], ['src/**/a.py']) is True
    assert ps.inside_touches(['a.txt'], []) is False and ps.inside_touches([], ['a']) is True       # nothing declared means never inside


def test_overlap_problems_name_stories_that_can_run_together_without_their_own_files():
    assert ps.overlap_problems(DIAMOND) == []
    clash = [n('a', touches=['site/']), n('b', touches=['site/b']), n('c', ('a', 'b'))]
    found = ps.overlap_problems(clash)
    assert len(found) == 1 and found[0].startswith('a and b can run at the same time but both change')
    bare = [n('a'), n('b', touches=['site/b'])]
    assert 'a: can run alongside other editing stories' in ps.overlap_problems(bare)[0]
    # nothing is asked of read-only, human, or ordered stories
    safe = [n('a', mode='read'), n('b', assignee='human', mode='read'), n('c'), n('d', ('c',))]
    assert ps.overlap_problems(safe) == []


# ------------------------------------------------------------------------------------- the project toggle: parallel build is opt-in
from tests.test_projects import app, active, new, node, init_repo      # noqa: E402,F401  (fixtures and helpers)
from models import Card, ProjectTask                         # noqa: E402


def submit(app, project):
    return app[0].post(f'/api/projects/{project["id"]}/submit', json={'revision': project['revision'], 'approve_coordination': True, 'approve_api_work': True})


def editing(key, **kw):
    return node(key, mode='edit', **kw)


def test_a_serial_build_ignores_touches_overlap_and_the_schedule_is_not_shown(app):
    plan = [editing('a'), editing('b')]                                   # two editing stories, no touches: fine when built one at a time
    p = new(app, plan)
    assert p['document']['dispatch_mode'] == 'sequential' and p['schedule'] is None
    assert submit(app, p).status_code == 200


def test_a_parallel_build_refuses_overlapping_or_unlisted_files_at_submission_and_says_how_to_fix_it(app):
    init_repo(app[2])
    p = new(app, [editing('a'), editing('b')], dispatch_mode='parallel')
    refused = submit(app, p)
    assert refused.status_code == 422 and 'must list the files or folders it changes' in refused.text and 'turn parallel build off' in refused.text
    shown = app[0].get(f'/api/projects/{p["id"]}').json()['schedule']
    assert shown['problems'] and shown['max_concurrent_runs'] >= 1 and shown['width'] == 2
    clash = new(app, [editing('a', touches=['site/']), editing('b', touches=['site/b'])], dispatch_mode='parallel')
    assert 'both change' in submit(app, clash).text
    fine = new(app, [editing('a', touches=['site/a'], estimate_minutes=30), editing('b', touches=['site/b'], estimate_minutes=90)], dispatch_mode='parallel')
    assert fine['schedule']['problems'] == [] and submit(app, fine).status_code == 200


def test_an_integration_story_must_join_at_least_two_stories(app):
    p = new(app, [editing('a', touches=['x/a']), editing('j', depends_on=['a'], integration=True, touches=['x/'])], dispatch_mode='parallel')
    r = submit(app, p)
    assert r.status_code == 422 and 'integration story but depends on fewer than two' in r.text


def test_a_parallel_build_creates_the_longest_chain_first(app):
    init_repo(app[2])
    plan = [editing('a', touches=['s/a'], estimate_minutes=30), editing('b', touches=['s/b'], estimate_minutes=90), editing('c', touches=['s/c'], estimate_minutes=60),
            editing('j', depends_on=['a', 'b', 'c'], integration=True, touches=['s/'], estimate_minutes=45)]
    p = active(app, plan, dispatch_mode='parallel')
    with app[1]() as s:
        links = {t.node_key: t.card_id for t in s.query(ProjectTask).filter(ProjectTask.project_id == p['id'], ProjectTask.role == 'story')}
        position = {k: s.get(Card, cid).position for k, cid in links.items()}
    assert sorted(position, key=position.get) == ['b', 'c', 'a', 'j']
    serial = active(app, [editing('a', estimate_minutes=30), editing('b', depends_on=['a'], estimate_minutes=90)])
    with app[1]() as s:
        order = [t.node_key for t in s.query(ProjectTask).filter(ProjectTask.project_id == serial['id'], ProjectTask.role == 'story').order_by(ProjectTask.card_id)]
    assert order == ['a', 'b']                                            # serial stays in dependency order


# ------------------------------------------------------------------------------------- the lighter gate for a parallel build (off by default)
import subprocess                                             # noqa: E402
from pathlib import Path                                       # noqa: E402
from dispatcher import Dispatcher                              # noqa: E402
from tests.test_projects import finish, advance, git           # noqa: E402


def stories_of(p):
    return {t['node_key']: t for t in p['tasks'] if t['role'] == 'story'}


def column(app, card_id):
    with app[1]() as s:
        return s.get(Card, card_id).column


def write(path, name, text='x'):
    target = Path(path) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def run_story(app, story, files, result='Done. Checks pass.'):
    for name in files:
        write(story['working_dir'], name)
    return finish(app, story['card_id'], result)


def build(app, plan):
    init_repo(app[2])
    p = active(app, plan, dispatch_mode='parallel')
    Dispatcher(app[1], app[3])._claim(4)
    return p, stories_of(p)


def card_to_review(app, card_id):
    with app[1].begin() as s:
        s.get(Card, card_id).column = 'review'


def test_the_gate_is_off_by_default_so_a_low_risk_story_still_waits_for_a_person(app):
    p, st = build(app, [editing('a', touches=['a/'], risk='low')])
    run_story(app, st['a'], ['a/a.txt']); card_to_review(app, st['a']['card_id'])
    advance(app)
    assert column(app, st['a']['card_id']) == 'review'


def test_a_low_risk_story_inside_its_files_is_accepted_on_its_own_and_recorded_as_auto_accept(app):
    app[3].project_auto_accept_low = True
    p, st = build(app, [editing('a', touches=['a/'], risk='low'), editing('b', touches=['b/'], risk='low')])
    run_story(app, st['a'], ['a/a.txt']); card_to_review(app, st['a']['card_id'])
    run_story(app, st['b'], ['b/b.txt']); card_to_review(app, st['b']['card_id'])
    advance(app)
    assert column(app, st['a']['card_id']) == 'done' and column(app, st['b']['card_id']) == 'done'
    ledger = app[0].get(f'/api/projects/{p["id"]}').json()
    assert any(m['actor'] == 'auto-accept' and m['kind'] == 'handoff' and 'Auto-accepted under the low-risk gate' in m['text'] for m in ledger['memory'])
    manifest_artifacts = ledger['artifacts']
    assert set(manifest_artifacts) == {'a', 'b'} and manifest_artifacts['a']['files'] == ['a/a.txt']


def test_the_gate_leaves_everything_else_for_a_person(app):
    app[3].project_auto_accept_low = True
    plan = [editing('out', touches=['x/'], risk='low'),                    # changes a file outside its declared files
            editing('med', touches=['m/'], risk='medium'),                 # not low risk
            editing('none', touches=['n/'], risk='low'),                   # changes nothing
            editing('inc', touches=['i/'], risk='low'),                    # reports itself incomplete
            editing('j1', touches=['j1/'], risk='low'), editing('j2', touches=['j2/'], risk='low'),
            editing('join', depends_on=['j1', 'j2'], integration=True, touches=['j1/', 'j2/'], risk='low')]
    p, st = build(app, plan)
    run_story(app, st['out'], ['elsewhere/oops.txt']); run_story(app, st['med'], ['m/m.txt']); run_story(app, st['none'], [])
    run_story(app, st['inc'], ['i/i.txt'], result='**Status: not done.** The checks were blocked.')
    for key in ('out', 'med', 'none'):
        card_to_review(app, st[key]['card_id'])
    advance(app)
    for key in ('out', 'med', 'none'):
        assert column(app, st[key]['card_id']) == 'review', key
    assert column(app, st['inc']['card_id']) == 'failed'                    # an incomplete report is already refused by the existing rule
    for key in ('j1', 'j2'):
        run_story(app, st[key], [f'{key}/f.txt']); card_to_review(app, st[key]['card_id'])
    advance(app)
    assert column(app, st['j1']['card_id']) == 'done' and column(app, st['j2']['card_id']) == 'done'
    Dispatcher(app[1], app[3])._claim(4)
    run_story(app, st['join'], ['j1/joined.txt']); card_to_review(app, st['join']['card_id'])
    advance(app)
    assert column(app, st['join']['card_id']) == 'review'                  # an integration story always gets a person


def test_timing_compares_agent_minutes_with_elapsed_minutes_and_integration_stories_get_their_instructions(app):
    p, st = build(app, [editing('a', touches=['a/'], estimate_minutes=30), editing('b', touches=['b/'], estimate_minutes=30),
                        editing('j', depends_on=['a', 'b'], integration=True, touches=['a/', 'b/'], estimate_minutes=20)])
    assert app[0].get(f'/api/projects/{p["id"]}').json()['timing'] is None
    with app[1].begin() as db:
        from models import Run
        for key, (start, end) in {'a': (1000, 1600), 'b': (1100, 1700)}.items():
            run = Run(card_id=st[key]['card_id'], agent='codex', stage='succeeded', started_at=start, ended_at=end, command='[]', log_path='t', working_dir=st[key]['working_dir'])
            db.add(run)
    t = app[0].get(f'/api/projects/{p["id"]}').json()['timing']
    assert t == {'runs': 2, 'busy_minutes': 20.0, 'elapsed_minutes': 11.7, 'overlap': 1.71}        # 1200 s of work in 700 s: two overlapped runs
    # the join is only claimed after both branches are accepted
    for key in ('a', 'b'):
        run_id = finish(app, st[key]['card_id'], 'Done.')
        write(st[key]['working_dir'], f'{key}/f.txt')
        with app[1].begin() as db:
            db.get(Card, st[key]['card_id']).column = 'review'
        r = app[0].post(f'/api/projects/{p["id"]}/stories/{st[key]["card_id"]}/accept', json={'run_id': run_id, 'summary': 'ok', 'snapshot': True, 'files': [f'{key}/f.txt']})
        assert r.status_code == 200, r.text
    with app[1].begin() as db:
        text = projects.claim_context(db, db.get(Card, st['j']['card_id']))
    assert 'INTEGRATION STORY (parallel build)' in text and 'a, b' in text and 'never delete another branch' in text
    assert (Path(st['j']['working_dir']) / 'a/f.txt').exists() and (Path(st['j']['working_dir']) / 'b/f.txt').exists()     # both branches joined into its workspace
